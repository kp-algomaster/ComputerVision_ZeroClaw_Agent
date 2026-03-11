# Quickstart: GitHub Copilot SDK Chat Integration

**Branch**: `005-copilot-sdk-chat` | **Date**: 2026-03-11

---

## Prerequisites

- Python 3.12 (project standard)
- `.venv/` active: `source .venv/bin/activate`
- Existing agent server runnable: `uvicorn cv_agent.web:app --reload --port 8420`
- One of:
  - A GitHub account with a Copilot subscription + a PAT/OAuth token, **or**
  - A local Ollama instance (BYOK mode — no GitHub subscription needed)

---

## Install

```bash
.venv/bin/pip install github-copilot-sdk
```

---

## Configure

### Option A — GitHub Copilot (token auth)

Add to `.env`:
```
COPILOT_GITHUB_TOKEN=ghp_your_token_here
```

Add to `config/agent_config.yaml`:
```yaml
copilot:
  enabled: true
  default_model: ""        # leave empty to use first available
```

### Option B — BYOK Ollama (no GitHub subscription)

Add to `config/agent_config.yaml`:
```yaml
copilot:
  enabled: true
  byok_provider:
    type: ollama
    base_url: http://localhost:11434
  default_model: qwen2.5-coder:latest
```

No `.env` changes needed.

---

## Run

```bash
uvicorn cv_agent.web:app --reload --port 8420
```

Open `http://127.0.0.1:8420` — the chat window now routes through the Copilot SDK when `copilot.enabled: true`.

---

## Verify Integration

Check SDK status:
```
GET http://127.0.0.1:8420/api/copilot/status
```

Expected response:
```json
{"connected": true, "auth_ok": true, "sdk_state": "connected", "byok_mode": false, "active_sessions": 0}
```

List available models:
```
GET http://127.0.0.1:8420/api/copilot/models
```

---

## Disable / Rollback

Set `copilot.enabled: false` in `config/agent_config.yaml` (or remove the key).
Server falls back to the existing LangGraph/Ollama backend with no other changes.

---

## Registering a New CV Tool as a Copilot Skill

Tools in `src/cv_agent/tools/` decorated with `@tool` are automatically wrapped as Copilot skills at session init. No extra registration step needed — just ensure the tool is returned by `build_tools()` in `agent.py`.

To verify a tool is available to the Copilot agent:
1. Start a chat session
2. Ask: *"What tools do you have available?"*
3. The agent will list all registered skills by name

---

## Development Notes

- Copilot session objects are stored per WebSocket connection; they are cleaned up automatically on disconnect
- `session.abort()` is called when the frontend sends `{type: "cancel"}` — the in-progress task halts within ~1s
- All tokens/secrets remain server-side; nothing is sent to the browser
- SDK Technical Preview: pin `github-copilot-sdk==0.1.0` in `pyproject.toml` to avoid unintended upgrades
