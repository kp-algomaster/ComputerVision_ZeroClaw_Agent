# Tasks: GitHub Copilot SDK Chat Integration

**Input**: Design documents from `/specs/005-copilot-sdk-chat/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/ ✅ quickstart.md ✅

**Tests**: Not requested — no test tasks included.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable (different files, no shared state dependency)
- **[Story]**: User story this task belongs to (`US1`–`US4`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Install SDK, add config scaffold, no source logic yet.

- [x] T001 Add `github-copilot-sdk==0.1.0` to `pyproject.toml` dependencies and run `.venv/bin/pip install github-copilot-sdk`
- [x] T002 Add `copilot:` section to `config/agent_config.yaml` with fields: `enabled: false`, `default_model: ""`, `session_timeout_s: 120`, commented-out `byok_provider` example (see quickstart.md)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure all user stories depend on — config model, manager skeleton, lifespan wiring, and routing gate. **Must complete before any user story begins.**

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 [P] Add `CopilotConfig` Pydantic V2 model to `src/cv_agent/config.py` with fields: `enabled: bool = False`, `github_token: str = Field(default="", exclude=True)`, `byok_provider: dict | None = None`, `default_model: str = ""`, `cli_path: str | None = None`, `cli_url: str | None = None`, `session_timeout_s: int = 120`; add `copilot: CopilotConfig = Field(default_factory=CopilotConfig)` to `AgentConfig`; load `COPILOT_GITHUB_TOKEN` from env
- [x] T004 [P] Create `src/cv_agent/copilot_session.py` with `CopilotManager` class skeleton: `__init__`, `async start(config)` (calls `client.start()`), `async stop()` (calls `client.stop()`), `is_connected() -> bool` (checks `client.get_state() == "connected"`), module-level `copilot_manager = CopilotManager()` singleton
- [x] T005 Wire `CopilotManager` into FastAPI lifespan in `src/cv_agent/web.py`: call `await copilot_manager.start(config)` on startup and `await copilot_manager.stop()` on shutdown; import from `cv_agent.copilot_session`
- [x] T006 Add feature-flag routing gate inside the `/ws/chat` WebSocket handler in `src/cv_agent/web.py`: if `config.copilot.enabled and copilot_manager.is_connected()` → yield placeholder `{"type": "error", "message": "Copilot path not yet implemented"}` (filled in Phase 3); else → existing `run_agent_stream()` path unchanged

**Checkpoint**: Server starts cleanly; `config.copilot.enabled = false` keeps existing chat working; `enabled = true` returns placeholder error (not a crash).

---

## Phase 3: User Story 1 — Agentic Chat with Multi-Step Reasoning (Priority: P1) 🎯 MVP

**Goal**: Chat window streams a multi-step agentic response with tool-invocation events visible, using the Copilot SDK runtime.

**Independent Test**: Set `copilot.enabled: true` in config; open chat; submit "what tools do you have available?" — verify streamed tokens appear turn by turn and the agent lists registered skills without a page reload.

- [x] T007 [US1] Implement `CopilotStreamBridge` async generator in `src/cv_agent/copilot_session.py`: accepts `(session: CopilotSession, prompt: str, timeout: int)`, registers `session.on("message")` → yield `{type: "stream_token", content}`, `session.on("reasoning")` → yield `{type: "stream_token", content}`, `session.on("tool_call")` start/end → yield `{type: "tool_start", name, input}` / `{type: "tool_end", name, output}`; wraps `await session.send_and_wait(...)` and yields `{type: "stream_end", content}` on completion
- [x] T008 [US1] Add `CopilotSessionState` dataclass to `src/cv_agent/copilot_session.py` (fields: `session`, `session_id`, `model_id`, `turn_count`, `is_running`, `created_at`) and `app.state.copilot_sessions: dict[str, CopilotSessionState]` initialised in FastAPI lifespan in `src/cv_agent/web.py`
- [x] T009 [US1] Implement `CopilotManager.get_or_create_session(ws_id, model_id, skills)` in `src/cv_agent/copilot_session.py`: lazily calls `client.create_session(...)` on first message; stores result in `app.state.copilot_sessions`; reuses existing session on subsequent messages from same WebSocket
- [x] T010 [US1] Replace Phase 2 placeholder in `/ws/chat` Copilot branch (`src/cv_agent/web.py`) with real call: `async for event in CopilotStreamBridge.stream(state.session, message, timeout)`: yield `stream_start`, each event dict, then `stream_end` to WebSocket; set `state.is_running` True/False around the call
- [x] T011 [US1] Handle WebSocket close in `/ws/chat` (`src/cv_agent/web.py`): in the `finally` block call `await copilot_manager.close_session(ws_id)` which calls `await session.disconnect()` and removes entry from `app.state.copilot_sessions`; implement `close_session` in `src/cv_agent/copilot_session.py`

**Checkpoint**: Agentic chat streams live tokens via Copilot SDK; tool events visible in chat bubble; WebSocket close cleans up session. US1 independently testable.

---

## Phase 4: User Story 2 — Stateful Multi-Turn Conversation (Priority: P2)

**Goal**: Follow-up messages in the same chat session use prior context without the user repeating themselves.

**Independent Test**: Send two related messages in one WebSocket session; verify the second response references artefacts from the first turn (session ID is reused, not recreated).

- [x] T012 [US2] Ensure `CopilotManager.get_or_create_session()` in `src/cv_agent/copilot_session.py` reuses the existing `CopilotSession` object across turns (do NOT call `client.create_session()` again on the same `ws_id`); increment `state.turn_count` on each turn
- [x] T013 [US2] Add `{type: "cancel"}` WebSocket message handling to `/ws/chat` in `src/cv_agent/web.py`: if `state.is_running`, call `await state.session.abort()` and yield `{type: "cancelled"}`; set `state.is_running = False`; if no active session or not running, silently ignore

**Checkpoint**: Multi-turn context preserved across ≥5 turns; cancel halts in-flight task and yields `{type: "cancelled"}` within 3s. US2 independently testable on top of US1.

---

## Phase 5: User Story 3 — Model Selection in Chat (Priority: P3)

**Goal**: Users can enumerate and select Copilot models; selected model is used for that session and all subsequent turns.

**Independent Test**: `GET /api/copilot/models` returns a non-empty list; send `{type: "set_model", model_id: "<id>"}` over WebSocket; verify next response uses that model (check via Copilot status/log).

- [x] T014 [P] [US3] Add `ModelOption` TypedDict (or inline Pydantic model) to `src/cv_agent/web.py` with fields: `id: str`, `name: str`, `has_vision: bool`, `max_tokens: int`, `is_default: bool`
- [x] T015 [P] [US3] Implement `CopilotManager.list_models(default_model_id) -> list[ModelOption]` in `src/cv_agent/copilot_session.py`: calls `await client.list_models()`, maps to `ModelOption` dicts, caches result for 300 seconds; marks `is_default` on match; returns `[]` if not connected
- [x] T016 [US3] Add `GET /api/copilot/models` endpoint in `src/cv_agent/web.py`: returns `{models: [...], copilot_enabled: bool, sdk_state: str}` per contract in `contracts/websocket-events.md`; calls `copilot_manager.list_models(config.copilot.default_model)`
- [x] T017 [US3] Handle `{type: "set_model", model_id}` WebSocket message in `/ws/chat` (`src/cv_agent/web.py`): call `await state.session.set_model(model_id)` if session exists; update `state.model_id`; ignore if no active session

**Checkpoint**: `/api/copilot/models` returns model list; model switching works mid-session. US3 independently testable on top of US1.

---

## Phase 6: User Story 4 — Custom CV Tool Registration (Priority: P4)

**Goal**: All existing `@tool`-decorated CV tools are auto-wrapped as Copilot SDK skills and available to the agent at session creation — no changes to tool implementation files.

**Independent Test**: Start a session with `copilot.enabled: true`; ask the agent "use the segment_with_text tool on image X" — verify the tool is invoked (tool_start/tool_end events appear in chat) without any modification to `segment_anything.py`.

- [x] T018 [P] [US4] Create `src/cv_agent/tools/copilot_skills.py` with `build_copilot_skills(tools: list[BaseTool]) -> list` function signature and imports (`define_tool` from `copilot`, `BaseTool` from `langchain_core.tools`, `BaseModel`, `Field` from `pydantic`, `create_model` from `pydantic`)
- [x] T019 [P] [US4] Implement `_schema_to_pydantic(tool: BaseTool) -> type[BaseModel]` in `src/cv_agent/tools/copilot_skills.py`: reads `tool.args_schema` JSON schema fields; uses `pydantic.create_model()` to build a `BaseModel` subclass with matching field names and types; falls back to a single `input: str` field for tools with no structured schema
- [x] T020 [US4] Implement the `build_copilot_skills` body in `src/cv_agent/tools/copilot_skills.py`: for each tool, call `_schema_to_pydantic(tool)`, wrap `tool._run` as a sync handler, call `define_tool(description=tool.description, handler=wrapped, params_type=ParamsModel)`, return list of skills
- [x] T021 [US4] Integrate `build_copilot_skills` into `CopilotManager.get_or_create_session()` in `src/cv_agent/copilot_session.py`: call `build_copilot_skills(build_tools(config))` once per session; pass result as `tools=[...]` to `client.create_session(...)`; verify SAM3 (`segment_with_text`), Label Studio (`create_labelling_project`), and a dataset tool wrap without raising at session init

**Checkpoint**: All existing CV tools invocable by Copilot agent via chat; no tool file modified. US4 independently testable on top of US1.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Error surfacing, security hardening, observability, and final validation.

- [x] T022 [P] Add `GET /api/copilot/status` endpoint in `src/cv_agent/web.py`: returns `{connected, auth_ok, sdk_state, byok_mode, active_sessions}` per contract; calls `copilot_manager.get_status()` and `await client.get_auth_status()`; implement `get_status()` in `src/cv_agent/copilot_session.py`
- [x] T023 [P] Add graceful fallback logging in `src/cv_agent/copilot_session.py`: when `CopilotManager.start()` fails (auth error, CLI not found), log `WARNING: Copilot SDK unavailable — falling back to LangGraph backend` and set internal `_connected = False`; ensure `is_connected()` returns `False` so routing gate falls through to `run_agent_stream()`
- [x] T024 Add `{type: "copilot_status", state: str}` event emission from `CopilotManager` in `src/cv_agent/copilot_session.py` on connection state changes (`client.on("state_change", ...)`); forward to active WebSocket connections in `src/cv_agent/web.py`
- [x] T025 Validate `github_token` is excluded from all JSON serialization: confirm `CopilotConfig` field uses `Field(exclude=True)` or `model_config = ConfigDict(json_schema_exclude={"github_token"})` in `src/cv_agent/config.py`; verify `GET /api/status` does not leak the token value
- [x] T026 Run quickstart.md validation end-to-end: install SDK, set `enabled: true`, start server, hit `/api/copilot/status`, `/api/copilot/models`, send a chat message, send `{type: "cancel"}`; confirm all responses match contract shapes in `contracts/websocket-events.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — **blocks all user stories**
- **US1 (Phase 3)**: Depends on Phase 2 — core agentic streaming
- **US2 (Phase 4)**: Depends on Phase 3 (reuses `CopilotSessionState` from T008)
- **US3 (Phase 5)**: Depends on Phase 2 only — can run in parallel with US1/US2
- **US4 (Phase 6)**: Depends on Phase 3 (needs session creation from T009) — can run in parallel with US2/US3
- **Polish (Phase 7)**: Depends on all story phases complete

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational only — no story dependencies
- **US2 (P2)**: Depends on US1 (needs `CopilotSessionState` and `session.abort()` from Phase 3)
- **US3 (P3)**: Depends on Foundational only — model enumeration is independent of streaming
- **US4 (P4)**: Depends on US1 (needs `get_or_create_session()` from T009)

### Within Each User Story

- Foundational types/classes before dependent implementations
- `copilot_session.py` changes before `web.py` changes that call them
- Tool adapter (`copilot_skills.py`) before session integration that consumes it

### Parallel Opportunities

Within Phase 2: T003 and T004 can run in parallel (different files)
Within Phase 5: T014 and T015 can run in parallel (different concerns in same file — keep separate)
Within Phase 6: T018 and T019 can run in parallel (both in `copilot_skills.py` but non-overlapping functions)
Within Phase 7: T022, T023, T025 can run in parallel

---

## Parallel Example: Phase 2 (Foundational)

```
Parallel group A (can start together):
  T003 — CopilotConfig in config.py
  T004 — CopilotManager skeleton in copilot_session.py

Sequential after A:
  T005 — lifespan wiring in web.py  (needs T004)
  T006 — routing gate in web.py     (needs T005)
```

## Parallel Example: User Story 3

```
Parallel group:
  T014 — ModelOption type in web.py
  T015 — list_models() in copilot_session.py

Sequential after:
  T016 — GET /api/copilot/models endpoint (needs T014 + T015)
  T017 — set_model WS handler (needs session from T009)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T006) — **critical gate**
3. Complete Phase 3: US1 (T007–T011)
4. **STOP and VALIDATE**: Open chat, submit a multi-step prompt, verify streamed tool events appear
5. Optionally demo before continuing to US2–US4

### Incremental Delivery

1. Setup + Foundational → existing chat unaffected (flag is off)
2. US1 → agentic streaming live; validate independently → enable for demo
3. US2 → context retention; cancel button works
4. US3 → model selector populated; switching works
5. US4 → all existing CV tools auto-registered; SAM3/Label Studio callable via chat
6. Polish → status endpoint, fallback logging, token security, quickstart validation

### Parallel Team Strategy (if applicable)

After Phase 2 completes:
- **Dev A**: US1 (T007–T011) → US2 (T012–T013)
- **Dev B**: US3 (T014–T017)
- **Dev C**: US4 (T018–T021) — starts after T009 is merged from Dev A

---

## Notes

- `[P]` tasks touch different files or non-overlapping functions — safe to run concurrently
- `[Story]` label maps each task to its user story for traceability
- Each story phase ends with a **Checkpoint** — validate before moving on
- `github_token` must never appear in any API response or log line (T025)
- Pin `github-copilot-sdk==0.1.0` (T001) — Technical Preview may have breaking changes
- `copilot.enabled: false` is the default — zero risk to existing chat functionality until opted in
