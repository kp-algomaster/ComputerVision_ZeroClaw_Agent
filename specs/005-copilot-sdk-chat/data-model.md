# Data Model: GitHub Copilot SDK Chat Integration

**Branch**: `005-copilot-sdk-chat` | **Phase**: 1 | **Date**: 2026-03-11

---

## Entities

### CopilotConfig *(extends AgentConfig)*

New Pydantic V2 model added to `src/cv_agent/config.py`, nested under `AgentConfig`.

| Field | Type | Default | Source | Notes |
|-------|------|---------|--------|-------|
| `enabled` | `bool` | `False` | `config.yaml` / env | Feature flag; opt-in |
| `github_token` | `str` | `""` | `.env` `COPILOT_GITHUB_TOKEN` | Never logged or sent to client |
| `byok_provider` | `dict \| None` | `None` | `config.yaml` | e.g. `{"type": "ollama", "base_url": "..."}` |
| `default_model` | `str` | `""` | `config.yaml` | Falls back to first listed model |
| `cli_path` | `str \| None` | `None` | `config.yaml` | Path to copilot CLI binary if not on PATH |
| `cli_url` | `str \| None` | `None` | `config.yaml` | TCP server URL (overrides stdio mode) |
| `session_timeout_s` | `int` | `120` | `config.yaml` | Max wait for `send_and_wait()` |

**Validation rules**:
- If `enabled=True` and `github_token=""` and `byok_provider=None`, emit a WARNING at startup (SDK may still succeed via CLI credentials)
- `byok_provider` if set MUST contain `"type"` key

---

### CopilotSessionState *(server-side, in-memory)*

Stored in `app.state.copilot_sessions: dict[str, CopilotSessionState]`.
Key = WebSocket connection ID (str form of `id(websocket)`).

| Field | Type | Notes |
|-------|------|-------|
| `session` | `CopilotSession` | Live SDK session object |
| `session_id` | `str` | SDK-assigned session ID |
| `model_id` | `str` | Active model for this session |
| `turn_count` | `int` | Number of completed turns |
| `is_running` | `bool` | True while a `send_and_wait` is in flight |
| `created_at` | `float` | `time.monotonic()` timestamp |

**Lifecycle**:
- Created on first chat message after WS connect (lazy init)
- `is_running` set True before `send_and_wait`, False after `done` / `cancelled` / `error`
- Deleted and `session.disconnect()` called on WS close

---

### AgentTurn *(event stream shape — no DB persistence)*

Shape of events yielded by `CopilotStreamBridge` — identical to existing `run_agent_stream()` output.

| Event Type | Fields | Notes |
|------------|--------|-------|
| `stream_start` | `{}` | New assistant bubble |
| `stream_token` | `content: str` | Text chunk |
| `tool_start` | `name: str, input: str` | Tool being invoked |
| `tool_end` | `name: str, output: str` | Tool result (truncated if >500 chars) |
| `stream_end` | `content: str` | Full final response |
| `cancelled` | `{}` | Task was aborted |
| `error` | `message: str` | SDK or auth error |

---

### ModelOption *(runtime, not persisted)*

Shape of items returned by `GET /api/copilot/models`.

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | SDK model ID |
| `name` | `str` | Display name |
| `has_vision` | `bool` | From `capabilities.vision` |
| `max_tokens` | `int` | From `limits.max_tokens` |
| `is_default` | `bool` | True if matches `CopilotConfig.default_model` |

---

### CopilotSkill *(adapter, not persisted)*

Created at session init time from existing `@tool` functions.

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | From `BaseTool.name` |
| `description` | `str` | From `BaseTool.description` |
| `params_schema` | `type[BaseModel]` | Dynamically built from `BaseTool.args_schema` |
| `handler` | `Callable` | Wraps `tool._run()` |

---

## State Transitions

### WebSocket Chat Session (Copilot mode)

```
WS Connect
    │
    ▼
[idle] ──────────── user sends {message}
    │
    ▼
[running] ── session.abort() / {type:"cancel"} ──► [cancelled] ──► [idle]
    │
    ▼ stream_end / error
[idle]
```

### CopilotClient Lifecycle

```
Server startup
    │
    ▼
client.start() ──► [connected]
    │
    ├── create_session() per WS connection ──► [CopilotSession active]
    │
    └── Server shutdown ──► client.stop()
```

### Fallback Decision

```
Request arrives at /ws/chat
    │
    ▼
copilot.enabled? ──No──► run_agent_stream() [existing LangGraph]
    │ Yes
    ▼
client.get_state() == "connected"? ──No──► log WARNING + run_agent_stream()
    │ Yes
    ▼
CopilotStreamBridge (SDK path)
```
