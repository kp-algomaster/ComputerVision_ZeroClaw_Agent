# Research: GitHub Copilot SDK Chat Integration

**Branch**: `005-copilot-sdk-chat` | **Phase**: 0 | **Date**: 2026-03-11

---

## R-001: SDK Installation & Python Compatibility

**Decision**: Use `github-copilot-sdk` from PyPI.

**Rationale**: Officially published by GitHub, MIT-licensed, Pydantic V2 native, 100% async/await — all aligned with project constitution.

**Findings**:
- Package: `pip install github-copilot-sdk`
- Python 3.11–3.14 supported (project uses 3.12 ✅)
- Version 0.1.0 (Technical Preview)
- Uses ruff at line-length 100 (matches project linting config ✅)
- Core deps: `pydantic>=2.0`, `python-dateutil`

**Alternatives considered**: Direct Copilot REST API — rejected because the SDK abstracts JSON-RPC session management, tool dispatch, and streaming; re-implementing this is out of scope.

---

## R-002: SDK Async Model — Constitution Principle I Alignment

**Decision**: Integrate with `async/await` throughout; no thread offloading needed.

**Rationale**: The SDK is fully async-native (`CopilotClient.start()`, `CopilotSession.send()`, event handlers). No blocking calls exist. Aligns perfectly with Principle I (Async-First Architecture).

**Findings**:
- All `CopilotClient` and `CopilotSession` methods are `async def`
- Event handlers (`@session.on(...)`) are synchronous callbacks but are invoked from async context
- `session.abort()` for task cancellation is async
- No `asyncio.to_thread()` needed

---

## R-003: Tool/Skill Registration Strategy

**Decision**: Wrap existing `@tool`-decorated LangChain tools as Copilot `define_tool` skills via a conversion layer in `src/cv_agent/tools/copilot_skills.py`.

**Rationale**: Preserves Constitution Principle II (Tool-Centric Design) — tools stay in `src/cv_agent/tools/` and are registered explicitly via `build_tools()`. The Copilot skill wrapper is a thin adapter; no logic moves.

**Findings**:
- `define_tool(description, handler, params_type)` from `copilot` package accepts a Pydantic `BaseModel` for params
- Existing tools use LangChain `@tool` with docstring descriptions and typed args
- Conversion: extract `tool.name`, `tool.description`, and arg schema from `BaseTool.args_schema` → build Pydantic model → wrap with `define_tool`
- `handler(params: YourModel, invocation: ToolInvocation)` signature supported
- Tools registered at session creation: `client.create_session({"tools": [skill1, skill2, ...]})`

**Alternatives considered**: Re-decorating each tool natively — rejected; would scatter Copilot-specific code across all tool files and violate single-responsibility.

---

## R-004: Streaming Bridge — WebSocket Event Mapping

**Decision**: Bridge Copilot SDK session events to the existing WebSocket event format used by `run_agent_stream()`.

**Rationale**: The frontend already consumes `{type: "stream_start"}`, `{type: "stream_token", content}`, `{type: "tool_start", name, input}`, `{type: "tool_end", name, output}`, `{type: "stream_end", content}`. Reusing this format requires zero frontend changes for P1.

**Findings — SDK event types → existing WS event mapping**:

| Copilot SDK Event | WS Event Type | Notes |
|-------------------|---------------|-------|
| `message` (text chunk) | `stream_token` | streamed content |
| `reasoning` | `stream_token` (prefixed) | internal reasoning steps |
| `tool_call` (start) | `tool_start` | `event.tool_name`, `event.params` |
| `tool_call` (end) | `tool_end` | `event.result` |
| `send_and_wait` returns | `stream_end` | full final response |
| session error | `error` | maps to existing error event |

**Implementation**: `CopilotStreamBridge` class in `src/cv_agent/copilot_session.py` — async generator yielding the same dict shape as `run_agent_stream()`.

---

## R-005: Session State Management

**Decision**: Store one `CopilotSession` per WebSocket connection in a server-side dict keyed by `websocket.client` ID.

**Rationale**: `CopilotSession` is stateful (holds conversation history across turns) — this maps naturally to a single WebSocket lifetime. On disconnect, call `session.disconnect()` to clean up.

**Findings**:
- `CopilotClient` is process-level singleton (start once, shared across sessions)
- `create_session()` → unique `CopilotSession` per user conversation
- `resume_session(session_id)` enables cross-request history if needed later
- `session.abort()` → clean cancellation for in-flight requests
- `client.stop()` on server shutdown

**Alternatives considered**: One session per server (shared) — rejected; mixing conversation histories from different users.

---

## R-006: Authentication

**Decision**: Support `COPILOT_GITHUB_TOKEN` in `.env`, loaded via `load_config()`. Pass to `CopilotClientOptions.github_token`.

**Rationale**: Aligns with Principle III (Config-Driven, Secret-Safe). SDK also auto-reads `GH_TOKEN` / `GITHUB_TOKEN` as fallback.

**Findings**:
- SDK checks env vars in priority order: explicit option → `COPILOT_GITHUB_TOKEN` → `GH_TOKEN` → `GITHUB_TOKEN` → Copilot CLI credentials → BYOK
- BYOK supports `ollama` provider type (`{"type": "ollama", "base_url": "http://localhost:11434"}`) — enables local-only use without a GitHub subscription
- Auth status checkable: `await client.get_auth_status()`
- `client.get_state()` → `"disconnected" | "connecting" | "connected" | "error"`

**Config addition**: New `CopilotConfig` Pydantic model added to `AgentConfig` with fields: `enabled`, `github_token`, `byok_provider`, `default_model`, `feature_flag`.

---

## R-007: Model Enumeration

**Decision**: Expose `GET /api/copilot/models` endpoint backed by `client.list_models()` with response caching (TTL = 5 min).

**Rationale**: Models are enumerated at runtime (not compile-time). SDK has built-in caching for `list_models()`. A dedicated endpoint keeps frontend model selector simple.

**Findings**:
- `list_models()` returns `List[ModelInfo]` with: `id`, `name`, `capabilities` (vision, reasoning_effort), `limits` (max_tokens)
- `session.set_model(model_id)` allows mid-session switching
- Default model configurable via `CopilotConfig.default_model`

---

## R-008: Cancellation

**Decision**: Frontend sends `{type: "cancel"}` JSON over the existing WebSocket; backend calls `await session.abort()`.

**Rationale**: `session.abort()` is the SDK's native cancellation path. Reuses existing WebSocket connection so no new channel needed.

**Findings**:
- `await session.abort()` cleanly halts in-flight requests
- After abort, session can be reused for new messages
- SC-004 target: ≤3 seconds for cancel to clear — `abort()` is immediate; frontend clears indicator on `{type: "cancelled"}` event

---

## R-009: Feature Flag & Graceful Fallback

**Decision**: `CopilotConfig.enabled: bool = False` (off by default). When disabled or when `CopilotClient` fails to connect, fall back silently to existing LangGraph/Ollama `run_agent_stream()`.

**Rationale**: SDK is Technical Preview. An opt-in flag prevents regressions for users without a GitHub token. Principle III requires no hardcoded behaviour.

**Findings**:
- Feature flag set in `config/agent_config.yaml` under `copilot.enabled`
- Fallback triggered if: `copilot.enabled == False`, auth fails, `client.get_state() != "connected"`, or `CopilotClientOptions` missing token
- Fallback logged at WARNING level; user sees existing chat behaviour

---

## R-010: BYOK / Local Ollama Mode

**Decision**: Support BYOK Ollama provider via `CopilotConfig.byok_provider = {"type": "ollama", "base_url": "http://localhost:11434"}`.

**Rationale**: Allows project users without a GitHub Copilot subscription to benefit from the agentic runtime using their local Ollama instance. Critical for the local-first ethos of the project.

**Findings**:
- SDK `create_session` accepts `provider` dict with `type: "ollama"` and `base_url`
- Requires no GitHub token in BYOK mode
- Model from `CopilotConfig.default_model` or `config.llm.model`

---

## Resolved Unknowns Summary

| Unknown | Resolution |
|---------|-----------|
| SDK Python package name | `github-copilot-sdk` (PyPI) |
| Tool registration API | `define_tool(description, handler, params_type)` |
| Streaming bridge | Event handlers map to existing WS event dict format |
| Session state storage | Per-WS-connection dict in `app.state` |
| Auth mechanism | `COPILOT_GITHUB_TOKEN` in `.env`; BYOK Ollama as alternative |
| Model enumeration | `client.list_models()` → `/api/copilot/models` endpoint |
| Cancellation | `session.abort()` triggered by `{type: "cancel"}` WS message |
| Fallback strategy | Feature flag; fall back to existing `run_agent_stream()` |
