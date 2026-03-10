# Tasks: CV-Playground

**Input**: Design documents from `/specs/002-cv-playground/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/ ✅ quickstart.md ✅

**Tests**: Unit tests included for the DAG runner (critical backend logic). No tests for frontend tasks (manual browser verification per quickstart.md).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on in-progress tasks)
- **[Story]**: Which user story this task belongs to (US1–US4)

---

## Phase 1: Setup

**Purpose**: Create the new `pipeline` package skeleton and test directories.

- [X] T001 Create `src/cv_agent/pipeline/__init__.py` (empty package marker)
- [X] T002 [P] Create `tests/unit/` directory with `__init__.py` (pytest discovery)
- [X] T003 [P] Create `tests/integration/` directory with `__init__.py` (pytest discovery)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core backend models, DAG runner, skill registry adapter, new API endpoints, and base frontend scaffolding. ALL must be complete before any user story implementation begins.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Backend — Models & Logic

- [X] T004 Implement Pydantic V2 models (`BlockStatus`, `Position`, `BlockInstance`, `Edge`, `PipelineGraph`, `SkillDefinition`, `RunContext`, `RunStatus`) in `src/cv_agent/pipeline/models.py` per data-model.md
- [X] T005 [P] Implement `SkillRegistryAdapter` in `src/cv_agent/pipeline/skill_registry.py` — calls `build_tools()`, maps tools to `SkillDefinition` list using module-filename-to-category table from research.md; includes `__inputs__` and `__outputs__` special nodes
- [X] T006 Implement async DAG runner in `src/cv_agent/pipeline/dag_runner.py`: Kahn's topological sort, `asyncio.to_thread` wrapping for sync `@tool` calls, `asyncio.gather(return_exceptions=True)` for fan-out branches, per-node status callback, independent error branch isolation; implement FR-024 implicit pass-through binding: inject upstream output string as the downstream block's first required parameter (key-match from Inputs node config; fallback to first-required-param for all other blocks) (depends on T004)
- [X] T007 Write unit tests for DAG runner in `tests/unit/test_dag_runner.py`: linear pipeline, fan-out fan-in, error isolation (errored branch halts; sibling continues), cycle detection rejection, missing Inputs node rejection (depends on T006)

### Backend — API Endpoints

- [X] T008 Add `GET /api/playground/skills` endpoint to `src/cv_agent/web.py`: calls `SkillRegistryAdapter`, returns `{"skills": [...]}` JSON (used /api/playground/skills to avoid conflict with existing /api/skills skills-readiness endpoint) (depends on T005)
- [X] T009 Add pipeline WebSocket runner in `src/cv_agent/web.py`: extend `/ws/workflows/{run_id}` to handle pipeline `RunContext`; emit `node_status`, `node_output`, `node_error`, `pipeline_done` events per `contracts/websocket.md`; forward `node_output` to chat panel as `[Pipeline · <block_name>]` message (depends on T006)
- [X] T010 Add pipeline persistence helper in `src/cv_agent/pipeline/storage.py`: `async save_pipeline(graph: PipelineGraph) -> Path`, `async load_pipeline(pipeline_id: str) -> PipelineGraph`, `async list_pipelines() -> list[dict]`; all file I/O via `asyncio.to_thread(open(...))` (Constitution Principle I); reads `config.workflow.storage_dir`; distinguishes pipeline files from Eko templates by presence of `"nodes"` key (depends on T004)

### Frontend — Base Scaffolding

- [X] T011 Add Drawflow CDN script tag and playground sidebar HTML skeleton to `src/cv_agent/ui/index.html`: `<aside id="playground-panel">` with skill library, canvas, parameter panel flyout; toolbar with Save, Load, Run controls; keyboard shortcut Cmd/Ctrl+Shift+P
- [X] T012 [P] Add playground CSS to `src/cv_agent/ui/style.css`: sidebar split layout (chat + playground side-by-side ≥ 1280 px); Drawflow node colour variables (`--pg-pending`, `--pg-running`, `--pg-done`, `--pg-error`); skill library column; parameter panel flyout; responsive breakpoint < 1280 px (full-width switch)
- [X] T013 Add base playground JS to `src/cv_agent/ui/app.js`: `initPlayground()` function; Drawflow instance creation on `#pgCanvas`; `pgFetchSkills()` → `GET /api/playground/skills`; populate skill library grouped by category with collapsible sections; keyboard shortcut handler; `togglePlayground()` wired to nav item

**Checkpoint**: Backend endpoints (`/api/skills`, `/ws/workflows/{run_id}` pipeline mode) and frontend scaffold are ready. User story implementation can now begin.

---

## Phase 3: User Story 1 — Assemble and Run a Vision Pipeline (Priority: P1) 🎯 MVP

**Goal**: User can open the Playground sidebar, drag Inputs → OCR → Outputs blocks onto the canvas, wire them, click Run, and see streaming OCR results in the chat and on the canvas nodes.

**Independent Test**: Open Playground → drag Inputs + Run OCR + Outputs blocks → connect edges → enter an image path in Inputs config → click Run → verify OCR text appears in chat labelled `[Pipeline · run_ocr]` and all three blocks turn green.

### Implementation

- [X] T014 [US1] Implement sidebar toggle in `src/cv_agent/ui/app.js`: `togglePlayground()` opens/closes `#playground-panel` without shifting or covering the chat panel; `Cmd+Shift+P` / `Ctrl+Shift+P` keyboard shortcut; toolbar button click handler; sidebar open within 500 ms (SC-002)
- [X] T015 [US1] Implement drag-from-library-to-canvas in `src/cv_agent/ui/app.js`: each skill block in the library is `draggable`; Drawflow `addNode()` call on drop with correct input/output port count; block displays display_name and category badge colour
- [X] T016 [US1] Implement Special node rendering in `src/cv_agent/ui/app.js`: `__inputs__` node renders with 0 inputs/1 output; `__outputs__` node renders with 1 input/0 outputs; both are draggable from library like regular blocks with "Special" badge
- [X] T017 [US1] Add Run button activation logic in `src/cv_agent/ui/app.js`: `_pgUpdateRunBtn()` — scans Drawflow graph for `__inputs__` and `__outputs__` nodes; Run button enabled/disabled reactively; FR-011
- [X] T018 [US1] Add `POST /api/pipelines/run` (ad-hoc) endpoint to `src/cv_agent/web.py`: accepts full `PipelineGraph` JSON + `"inputs"` object in body (no prior save required); starts DAG runner as background `asyncio.Task`; returns `{"run_id": "uuid", "ws_url": "/ws/workflows/uuid"}`; also added `POST /api/pipelines/{pipeline_id}/run` variant (depends on T009, T010)
- [X] T019 [US1] Implement pipeline run WebSocket client in `src/cv_agent/ui/app.js`: on Run click → `POST /api/pipelines/run` → connect to returned `ws_url`; on `node_status` → update Drawflow node CSS class; on `node_output` → append message to chat panel; on `pipeline_done` → restore Run button
- [X] T020 [US1] Implement block error state rendering in `src/cv_agent/ui/app.js`: on `node_error` event → set node class `pg-status-error` (red border); render short error message text inside node via `#pg-err-{nodeId}` span

**Checkpoint**: US1 fully functional — open sidebar, assemble two-block pipeline, run, see streaming output. MVP demonstrable.

---

## Phase 4: User Story 2 — Configure a Block's Parameters Inline (Priority: P2)

**Goal**: Clicking a block opens an inline parameter panel showing all configurable fields (derived from the skill's parameter schema). Edits persist to the pipeline graph state and are used on the next Run.

**Independent Test**: Place a Vision Analysis (or `analyze_image`) block on the canvas → click it → edit the `prompt` field → run a one-block pipeline (Inputs → analyze_image → Outputs) → verify the custom prompt appears in the output.

### Implementation

- [X] T021 [US2] Implement block click handler in `src/cv_agent/ui/app.js`: Drawflow `nodeSelected` event → `pgOpenParamPanel(nodeId)` → reads `parameter_schema` for the selected node; renders panel as flyout over canvas
- [X] T022 [P] [US2] Implement JSON Schema → form widget renderer in `src/cv_agent/ui/app.js`: `pgOpenParamPanel()` maps `type: string/number/integer/boolean/enum` to appropriate input widgets; required fields marked with red asterisk per FR-015
- [X] T023 [US2] Implement config persistence in `src/cv_agent/ui/app.js`: `pgApplyParam()` writes form values into `_pg.nodeConfigs[nodeId].config`; config survives sidebar close/reopen (persists in `_pg.nodeConfigs` in-memory state); FR-016
- [X] T024 [US2] Implement pre-run required-field validation in `src/cv_agent/ui/app.js`: `_pgValidate()` — iterates all nodes, checks required schema fields against stored config; highlights non-conforming blocks with `pg-invalid` CSS class; blocks Run if any violations found; FR-015
- [X] T025 [US2] `pg-invalid` CSS class and validation warning styles in `src/cv_agent/ui/style.css`: yellow/orange border for blocks with empty required fields; distinct from `pg-status-error` (red = runtime failure)

**Checkpoint**: US1 + US2 both functional — blocks are configurable inline, configs survive sidebar toggles, custom params flow into run.

---

## Phase 5: User Story 3 — Save and Reload a Pipeline (Priority: P3)

**Goal**: User names and saves the current canvas as a pipeline. On reload the pipeline appears in the Workflows nav section and can be fully restored (all blocks, edges, and parameter values) from the Load dropdown.

**Independent Test**: Build a three-block pipeline → Save as `test-pipeline` → reload page → open Playground → click Load → select `test-pipeline` → verify all blocks, edges, and config values are restored exactly.

### Implementation

- [X] T026 [US3] Add `POST /api/pipelines` endpoint to `src/cv_agent/web.py`: accept `PipelineGraph` JSON body; call `storage.save_pipeline()`; return 200 `{"status": "created", ...}` or 409 `{"status": "conflict", ...}` on name collision per `contracts/rest-api.md` (depends on T010)
- [X] T027 [P] [US3] Add `GET /api/pipelines` endpoint to `src/cv_agent/web.py`: call `storage.list_pipelines()`; return summary list with `id`, `name`, `created_at`, `updated_at`, `node_count`, `edge_count` (depends on T010)
- [X] T028 [P] [US3] Add `GET /api/pipelines/{pipeline_id}` endpoint to `src/cv_agent/web.py`: load full `PipelineGraph` JSON by ID; 404 if not found (depends on T010)
- [X] T029 [US3] Implement Save button flow in `src/cv_agent/ui/app.js`: `pgSavePipeline()` / `pgConfirmSave()` — prompts for pipeline name via inline dialog; `POST /api/pipelines`; on 409 response displays native confirm() dialog ("A pipeline named '[X]' already exists. Overwrite?"); re-POSTs with `"overwrite": true` if confirmed; FR-021a
- [X] T030 [US3] Implement Load dropdown in `src/cv_agent/ui/app.js`: `pgToggleLoadMenu()` → `GET /api/pipelines` → populates dropdown; on selection → `GET /api/pipelines/{id}` → `_pgImportGraph(graph)` to restore canvas; FR-023
- [X] T031 [US3] Surface saved pipelines in existing Workflows nav section in `src/cv_agent/ui/app.js`: extend `loadWorkflows()` to merge pipeline list from `GET /api/pipelines` into the Workflows view; clicking a pipeline entry opens Playground and loads it; FR-022

**Checkpoint**: US1 + US2 + US3 all functional — complete named pipelines can be saved, reloaded, and overwritten with confirmation.

---

## Phase 6: User Story 4 — Use an Agent Block in a Pipeline (Priority: P4)

**Goal**: Agent delegation blocks (Blog Writer, Paper to Code, etc.) are available as draggable blocks in the Agents category. Running a pipeline containing an Agent block streams the agent's tool-call events into the chat with block attribution.

**Independent Test**: Build Inputs → Blog Writer Agent → Outputs pipeline; provide an ArXiv URL as input; run; verify a blog draft appears in chat with tool-call events attributed to the Blog Writer block.

### Implementation

- [X] T032 [US4] `delegate_*` tool wrappers appear in "Agents" category in `src/cv_agent/pipeline/skill_registry.py`: tools whose `name` starts with `delegate_` are mapped to `SkillCategory.AGENTS`; display names strip the `delegate_` prefix and title-case the remainder (e.g. `delegate_blog_writer` → "Blog Writer Agent")
- [X] T033 [US4] Extend DAG runner in `src/cv_agent/pipeline/dag_runner.py` to handle agent blocks: for blocks whose `skill_name` starts with `delegate_`, call the **underlying async runner** (e.g., `run_blog_writer_agent()`) directly via `agent_runner_map` — not the `@tool` wrapper; pass the agent's final output string to downstream blocks per FR-024 binding rule; FR-019
- [X] T034 [US4] Forward agent sub-events to chat in `src/cv_agent/ui/app.js`: on `node_output` events → render in chat with `[Pipeline · <AgentName>]` label via `addMessage('assistant', ...)`; FR-019 / US4 acceptance scenario 1

**Checkpoint**: All four user stories functional — full end-to-end pipeline with agent delegation, streaming attribution, and nested tool events in chat.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Undo/redo, edge-case UX guards, responsive layout, and validation against quickstart.md.

- [X] T035 [P] Implement full multi-step undo/redo in `src/cv_agent/ui/app.js`: `_pg.undoStack[]` / `_pg.redoStack[]` of Drawflow `export()` snapshots (max 50); push snapshot on every canvas mutation; `Cmd+Z` / `Ctrl+Z` → `pgUndo()`; `Cmd+Y` / `Ctrl+Shift+Z` → `pgRedo()`; FR-012a
- [X] T036 [P] Implement client-side cycle detection in `src/cv_agent/ui/app.js`: `_pgCheckCycle()` DFS on `connectionCreated` event; on cycle → reject connection + show toast "Cycles are not allowed in pipelines"; FR-010
- [X] T037 [P] Implement block deletion cascade in `src/cv_agent/ui/app.js`: Drawflow `nodeRemoved` event → cleans up `_pg.nodeConfigs[id]`; updates run button state; closes param panel if deleted node was selected; FR-012
- [X] T038 [P] Verify Drawflow pan and zoom in `src/cv_agent/ui/app.js`: Drawflow provides built-in mouse-drag pan and scroll-wheel zoom; added `pgResetZoom()` button to toolbar (⊙); FR-013
- [X] T039 [P] Implement skill block search/filter in `src/cv_agent/ui/app.js`: `pgFilterSkills(query)` filters visible blocks by display_name/skill_name substring match in real time; hides empty category groups; FR-004
- [X] T040 [P] Add responsive < 1280 px layout to `src/cv_agent/ui/style.css`: media query sets `position:fixed; width:100vw` for playground panel on narrow screens so it covers full viewport; FR-003
- [ ] T041 Run quickstart.md Steps 1–6 manually and fix any deviations found in `src/cv_agent/` files; extend Step 4 to time the assembly-to-run flow and confirm it completes in < 3 minutes (SC-001); build a 5-block sequential pipeline to verify SC-003
- [ ] T042 [P] Verify chat + pipeline concurrency in browser (SC-006): start a pipeline run → immediately type and send a chat message → confirm both streams return independently with no event-loop stalling; if blocking is observed, isolate the DAG runner `asyncio.Task` creation in `web.py` and fix

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — blocks all user stories
- **Phase 3 (US1)**: Depends on Phase 2 — primary MVP deliverable
- **Phase 4 (US2)**: Depends on Phase 2 — can start alongside US1 after Phase 2
- **Phase 5 (US3)**: Depends on Phase 2 + T018/T019 (needs run_id pattern) — start after US1 checkpoint
- **Phase 6 (US4)**: Depends on Phase 3 (US1 end-to-end working) + T006 (DAG runner)
- **Phase 7 (Polish)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Starts after Foundational (Phase 2) — no dependency on other stories
- **US2 (P2)**: Starts after Foundational (Phase 2) — no dependency on US1 (separate files)
- **US3 (P3)**: Starts after Foundational; T026–T028 backend tasks can parallel US1/US2; T029–T031 frontend tasks need US1 Run flow working
- **US4 (P4)**: Starts after US1 is at checkpoint — extends DAG runner and chat rendering

### Within Each User Story

- Backend endpoint tasks before frontend integration tasks that call them
- Models (T004) before DAG runner (T006) before endpoint (T009/T018)
- `SkillRegistryAdapter` (T005) before `/api/skills` endpoint (T008)

### Parallel Opportunities

- T002, T003 (test dirs) → parallel with each other
- T005 (skill registry), T012 (CSS) → parallel in Phase 2
- T011, T012 (HTML + CSS) → parallel in Phase 2
- T026, T027, T028 (US3 backend endpoints) → all parallel after T010
- T035–T040 (all polish tasks) → all parallel in Phase 7

---

## Parallel Example: Phase 2 Backend + Frontend

```
# Backend (parallel after T004):
Task T005: skill_registry.py
Task T006: dag_runner.py (after T004)

# Frontend (parallel with backend):
Task T011: index.html skeleton
Task T012: style.css playground layout

# API endpoints (after T005/T006):
Task T008: GET /api/skills
Task T009: WS pipeline runner
Task T010: pipeline storage helper
```

## Parallel Example: US3 Backend Endpoints

```
# After T010 (storage helper) — all parallel:
Task T026: POST /api/pipelines
Task T027: GET /api/pipelines
Task T028: GET /api/pipelines/{id}
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004–T013) — **critical gate**
3. Complete Phase 3: US1 (T014–T020)
4. **STOP and VALIDATE**: Run quickstart.md Steps 1–4; verify two-block OCR pipeline runs end-to-end
5. Demo/validate with user — full feature value delivered at this point

### Incremental Delivery

1. Setup + Foundational → backend API + frontend scaffold ready
2. US1 → open sidebar, drag blocks, run pipeline, streaming in chat (MVP!)
3. US2 → inline block configuration (no-code research tool)
4. US3 → save/reload named pipelines (research accelerator)
5. US4 → agent blocks in pipelines (full multi-step automations)
6. Polish → undo/redo, cycle detection, responsive layout

### Parallel Team Strategy

After Phase 2 completes:
- **Developer A**: US1 (T014–T020) — run pipeline end-to-end
- **Developer B**: US2 (T021–T025) — inline parameter panel
- **Developer C**: US3 backend (T026–T028) — save/load endpoints

---

## Summary

| Phase | Tasks | Story | Parallelisable |
|-------|-------|-------|---------------|
| 1 Setup | T001–T003 | — | T002, T003 |
| 2 Foundational | T004–T013 | — | T005, T008, T011, T012 |
| 3 US1 (P1 MVP) | T014–T020 | US1 | — |
| 4 US2 (P2) | T021–T025 | US2 | T022 |
| 5 US3 (P3) | T026–T031 | US3 | T027, T028 |
| 6 US4 (P4) | T032–T034 | US4 | — |
| 7 Polish | T035–T042 | — | T035–T040, T042 |
| **Total** | **42 tasks** | | |

**Suggested MVP scope**: Phase 1 + Phase 2 + Phase 3 (US1) — 20 tasks to a fully runnable pipeline.

---

## Notes

- `[P]` tasks target different files and have no dependencies on in-progress tasks in the same phase
- Each user story phase produces an independently demonstrable increment
- Drawflow `export()` / `import()` is the serialisation boundary between frontend and backend pipeline JSON
- The `"nodes"` key in JSON distinguishes pipeline files from legacy Eko workflow templates in `output/.workflows/`
- Commit after each task or logical group; do not batch large diffs
