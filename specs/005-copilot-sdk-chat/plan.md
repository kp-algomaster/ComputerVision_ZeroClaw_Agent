# Implementation Plan: GitHub Copilot SDK Chat Integration

**Branch**: `005-copilot-sdk-chat` | **Date**: 2026-03-11 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-copilot-sdk-chat/spec.md`

---

## Summary

Integrate `github-copilot-sdk` (MIT, PyPI) as an opt-in chat backend for the CV Zero Claw Agent. When `copilot.enabled: true` in config, the existing `/ws/chat` WebSocket routes through a `CopilotStreamBridge` instead of LangGraph/Ollama — delivering multi-step agentic reasoning, stateful multi-turn context, real-time streaming, and model selection. Existing `@tool`-decorated CV tools are auto-wrapped as Copilot skills. A feature flag and graceful fallback ensure zero regression for users without a GitHub token (BYOK Ollama mode also supported).

---

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: `github-copilot-sdk` (MIT, 0.1.0), FastAPI, Pydantic V2, LangChain `BaseTool`
**Storage**: No new persistence; `CopilotSessionState` is in-memory per WebSocket connection
**Testing**: pytest + pytest-asyncio (existing); new integration tests against SDK stub
**Target Platform**: macOS (Apple Silicon primary), Linux server
**Project Type**: Web service (FastAPI + WebSocket)
**Performance Goals**: Streaming first token within 2s; cancel response ≤3s
**Constraints**: No blocking calls in async context; secrets never sent to browser; SDK Technical Preview — feature-flagged
**Scale/Scope**: Single-user local agent; no multi-tenancy concerns

---

## Constitution Check

*GATE: Must pass before implementation.*

| Principle | Check | Status | Notes |
|-----------|-------|--------|-------|
| I. Async-First | `CopilotClient`/`CopilotSession` are fully async; all bridge code uses `async/await` | ✅ PASS | No `asyncio.to_thread()` needed |
| II. Tool-Centric | Tools stay in `src/cv_agent/tools/`; `build_tools()` drives registration; Copilot skill wrapper is a thin adapter | ✅ PASS | No logic moves to `agent.py` |
| III. Config-Driven | `COPILOT_GITHUB_TOKEN` in `.env`; `copilot.*` in `agent_config.yaml`; no hardcoded values | ✅ PASS | `load_config()` handles all |
| IV. Streaming-First | Copilot SDK events bridged to existing WS stream format token-by-token | ✅ PASS | Matches existing SSE/WS contract |
| V. Spec-Driven | N/A — not a research pipeline feature | N/A | — |
| Licensing | `github-copilot-sdk` MIT (verified) | ✅ PASS | No AGPL/GPL risk |
| Linting | ruff line-length 100, Python 3.12 baseline | ✅ PASS | SDK itself uses same config |

**GATE RESULT: ALL CHECKS PASS — proceed to implementation.**

---

## Project Structure

### Documentation (this feature)

```text
specs/005-copilot-sdk-chat/
├── spec.md              ✅ Feature specification
├── plan.md              ✅ This file
├── research.md          ✅ Phase 0 research output
├── data-model.md        ✅ Entities and state transitions
├── quickstart.md        ✅ Dev setup guide
├── contracts/
│   └── websocket-events.md  ✅ WS + REST API contract
└── tasks.md             ⬜ Phase 2 output (/speckit.tasks — not yet created)
```

### Source Code Changes

```text
src/cv_agent/
├── config.py                        # Add CopilotConfig nested model to AgentConfig
├── copilot_session.py               # NEW: CopilotClient lifecycle + CopilotStreamBridge
├── tools/
│   └── copilot_skills.py            # NEW: @tool → define_tool adapter
└── web.py                           # Add /api/copilot/models, /api/copilot/status;
                                     # extend /ws/chat to route to CopilotStreamBridge

config/
└── agent_config.yaml                # Add copilot: section (enabled, default_model, byok_provider)
```

**Structure Decision**: Single-project layout (existing). Two new source files, three files extended. Zero new directories in `src/`.

---

## Complexity Tracking

No constitution violations. No entries required.

---

## Phase 0: Research

**Status**: ✅ Complete — see [research.md](research.md)

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| `github-copilot-sdk` from PyPI | Official, MIT, fully async, Pydantic V2 native |
| Thin adapter in `copilot_skills.py` | Preserves tool-centric design; no changes to existing tool files |
| Bridge SDK events to existing WS format | Zero frontend changes required for P1 agentic chat |
| `COPILOT_GITHUB_TOKEN` in `.env` | Aligns with Principle III; SDK also reads `GH_TOKEN` as fallback |
| Feature flag `copilot.enabled: false` (default off) | SDK is Technical Preview; no regression risk |
| BYOK Ollama provider support | Enables local-only use without GitHub subscription |
| Per-WS-connection `CopilotSessionState` | Maps naturally to WebSocket lifetime; history isolated per user |
| `session.abort()` on `{type: "cancel"}` WS message | SDK native cancellation; reuses existing WS channel |

---

## Phase 1: Design & Contracts

**Status**: ✅ Complete

### Data Model — [data-model.md](data-model.md)

Four entities:

1. **`CopilotConfig`** — Pydantic V2 model added to `AgentConfig`; fields: `enabled`, `github_token`, `byok_provider`, `default_model`, `cli_path`, `cli_url`, `session_timeout_s`
2. **`CopilotSessionState`** — In-memory server state per WS connection; holds live `CopilotSession`, `is_running` flag, `model_id`, `turn_count`
3. **`AgentTurn`** — Event stream shape (unchanged from existing format); two new types: `cancelled`, `copilot_status`
4. **`ModelOption`** — Runtime shape for `/api/copilot/models` response

### Interface Contracts — [contracts/websocket-events.md](contracts/websocket-events.md)

**WS Client → Server** (new):
- `{type: "cancel"}` — abort in-flight task
- `{type: "set_model", model_id: "..."}` — switch model mid-session

**WS Server → Client** (new):
- `{type: "cancelled"}` — task aborted
- `{type: "copilot_status", state: "..."}` — connection state change

**REST** (new):
- `GET /api/copilot/models` — runtime model list
- `GET /api/copilot/status` — auth + SDK health

### Quickstart — [quickstart.md](quickstart.md)

Covers: install, token-auth config, BYOK-Ollama config, run, verify, disable/rollback, tool registration.

---

## Implementation Design

### `src/cv_agent/copilot_session.py` (new file)

**`CopilotManager`** — singleton managing `CopilotClient` lifecycle:
```
startup: await client.start()
shutdown: await client.stop()
get_or_create_session(ws_id, model_id, skills) → CopilotSessionState
close_session(ws_id)
list_models() → List[ModelOption]  (5-min cache)
get_status() → dict
```

**`CopilotStreamBridge`** — async generator bridging SDK events to WS dict format:
```
stream(session, prompt) → AsyncGenerator[dict, None]
  registers on("message"), on("reasoning"), on("tool_call")
  yields stream_start → stream_token* → tool_start/end* → stream_end
  on abort → yields {type: "cancelled"}
  on error → yields {type: "error", message: ...}
```

### `src/cv_agent/tools/copilot_skills.py` (new file)

**`build_copilot_skills(tools: list[BaseTool])`** — converts LangChain tools to Copilot skills:
```
for tool in tools:
    ParamsModel = _schema_to_pydantic(tool.args_schema)
    skill = define_tool(description=tool.description, handler=_wrap(tool), params_type=ParamsModel)
    yield skill
```

**`_schema_to_pydantic(schema)`** — dynamically builds a Pydantic `BaseModel` from the tool's JSON schema. Falls back to a generic `{input: str}` model for tools with no structured args.

### `src/cv_agent/config.py` changes

Add `CopilotConfig` model and `copilot: CopilotConfig = CopilotConfig()` field to `AgentConfig`.

### `src/cv_agent/web.py` changes

1. **Startup/shutdown**: `await copilot_manager.start()` / `await copilot_manager.stop()` in FastAPI lifespan
2. **`/ws/chat` extension**:
   - Incoming `{type: "cancel"}` → `await copilot_manager.abort(ws_id)`
   - Incoming `{type: "set_model"}` → `copilot_manager.set_model(ws_id, model_id)`
   - Chat message routing:
     ```
     if config.copilot.enabled and copilot_manager.is_connected():
         async for event in CopilotStreamBridge.stream(session, message):
             await ws.send_json(event)
     else:
         async for event in run_agent_stream(message, config, history):
             await ws.send_json(event)
     ```
3. **New endpoints**:
   - `GET /api/copilot/models`
   - `GET /api/copilot/status`

### `config/agent_config.yaml` addition

```yaml
copilot:
  enabled: false
  default_model: ""
  session_timeout_s: 120
  # byok_provider:
  #   type: ollama
  #   base_url: http://localhost:11434
```

---

## Constitution Check (Post-Design)

Re-evaluated after Phase 1 design — all principles still satisfied:

- **Principle I**: `CopilotManager`, `CopilotStreamBridge`, all web handlers are `async def`. `build_copilot_skills` is called once at session init (sync OK — no I/O).
- **Principle II**: `copilot_skills.py` wraps tools; `build_tools()` remains the single source. No auto-discovery.
- **Principle III**: `CopilotConfig.github_token` sourced from `COPILOT_GITHUB_TOKEN` env var via `load_config()`. Never returned by any API endpoint.
- **Principle IV**: `CopilotStreamBridge` emits `stream_token` events incrementally. Frontend renders tokens as they arrive.
- **Security (FR-009)**: `github_token` field excluded from all JSON serialisation (`Field(exclude=True)` or `model_config = ConfigDict(json_schema_exclude={'github_token'})`).
