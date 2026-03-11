# Contract: WebSocket Chat Events (Copilot Extension)

**Branch**: `005-copilot-sdk-chat` | **Phase**: 1 | **Date**: 2026-03-11

This contract extends the existing `/ws/chat` WebSocket protocol.
All existing event types are **preserved unchanged** — Copilot mode emits the same shapes.

---

## Client → Server Messages

### Send Chat Message (existing, unchanged)

```json
{ "message": "string", "model": "string" }
```

### Cancel Running Task *(new)*

```json
{ "type": "cancel" }
```

Triggers `session.abort()` in Copilot mode; ignored if no task is running.

### Set Copilot Model *(new, optional)*

```json
{ "type": "set_model", "model_id": "string" }
```

Calls `session.set_model(model_id)` for subsequent turns. Persisted for the WebSocket session lifetime.

---

## Server → Client Events

All existing event types are preserved. Two new types added for Copilot mode:

### Existing (unchanged)

| `type` | Additional Fields | Description |
|--------|------------------|-------------|
| `typing` | `value: bool` | Typing indicator |
| `stream_start` | — | New assistant message bubble |
| `stream_token` | `content: str` | Streamed text chunk |
| `tool_start` | `name: str, input: str` | Tool invocation began |
| `tool_end` | `name: str, output: str` | Tool result returned |
| `stream_end` | `content: str` | Final response (full text) |
| `error` | `message: str` | Unrecoverable error |

### New (Copilot mode only)

| `type` | Additional Fields | Description |
|--------|------------------|-------------|
| `cancelled` | — | Task was successfully aborted via `cancel` |
| `copilot_status` | `state: str` | SDK connection state change (`"connected"`, `"error"`, `"fallback"`) |

---

## REST Endpoints (new)

### GET `/api/copilot/models`

Returns enumerated Copilot models. Cached server-side for 5 minutes.

**Response** `200 OK`:
```json
{
  "models": [
    {
      "id": "gpt-4o",
      "name": "GPT-4o",
      "has_vision": true,
      "max_tokens": 8192,
      "is_default": true
    }
  ],
  "copilot_enabled": true,
  "sdk_state": "connected"
}
```

**Response when Copilot disabled or unavailable** `200 OK`:
```json
{
  "models": [],
  "copilot_enabled": false,
  "sdk_state": "disconnected"
}
```

### GET `/api/copilot/status`

Auth and connection health check.

**Response** `200 OK`:
```json
{
  "connected": true,
  "auth_ok": true,
  "sdk_state": "connected",
  "byok_mode": false,
  "active_sessions": 2
}
```

---

## Config Keys (`.env` additions)

| Key | Required | Notes |
|-----|----------|-------|
| `COPILOT_GITHUB_TOKEN` | No (if BYOK) | GitHub token with Copilot access |

| Key | Required | Notes |
|-----|----------|-------|
| `agent_config.yaml` → `copilot.enabled` | Yes | `false` by default |
| `agent_config.yaml` → `copilot.default_model` | No | First available model used if empty |
| `agent_config.yaml` → `copilot.byok_provider` | No | `{type: ollama, base_url: ...}` for local mode |
