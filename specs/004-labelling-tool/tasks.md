# Tasks: Label Studio Integration

**Input**: Design documents from `specs/004-labelling-tool/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/labelling-api.md ✅

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths included in all descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies, config, and data-dir structure for Label Studio integration.

- [X] T001 Add `label-studio>=1.10.0` to `pyproject.toml` dependencies
- [X] T002 Add `LabellingConfig(BaseModel)` to `src/cv_agent/config.py` with `port`, `host`, `data_dir`, `auto_restart`, `api_token` fields
- [X] T003 Add `labelling: LabellingConfig` field to `AgentConfig` in `src/cv_agent/config.py`
- [X] T004 [P] Add `labelling:` section to `config/agent_config.yaml` with env-var-resolved fields (`LABEL_STUDIO_PORT`, `LABEL_STUDIO_TOKEN`, `OUTPUT_DIR`)
- [X] T005 [P] Add `output/.label-studio/` and `output/labels/` to `.gitignore`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure shared by all user stories — Label Studio REST client and server lifecycle management.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 Create `src/cv_agent/labelling_client.py` with `LabelStudioClient` class (sync httpx) including `health()`, `create_project()`, `list_projects()`, `get_project()`, `import_images()` generator, `_upload_one()`, `trigger_export()`, `poll_export()`, `download_export()` methods
- [X] T007 Add `_LABEL_CONFIG_XML` constant (all 4 annotation types: RectangleLabels, PolygonLabels, KeyPointLabels, BrushLabels) to `src/cv_agent/labelling_client.py`
- [X] T008 Add `export_path()` helper to `src/cv_agent/labelling_client.py` returning `output/labels/{date}_{name}/{format}/{id}.{ext}`
- [X] T009 Add `_restart_tasks: dict[str, asyncio.Task] = {}` and `register_label_studio(cfg)` to `src/cv_agent/server_manager.py`
- [X] T010 Add `_auto_restart_loop()`, `enable_auto_restart()`, `disable_auto_restart()` to `src/cv_agent/server_manager.py`
- [X] T011 Modify `stop_server()` in `src/cv_agent/server_manager.py` to call `disable_auto_restart()` before terminating

**Checkpoint**: `LabelStudioClient` and `server_manager` extension complete — user story implementation can now proceed.

---

## Phase 3: User Story 1 — Launch Labelling Session (Priority: P1) 🎯 MVP

**Goal**: User can start Label Studio from the agent sidebar and reach an annotation-ready workspace within 30 s.

**Independent Test**: Navigate to Labelling in sidebar → click Start → verify green status dot within 60 s → iframe or "Connect at" URL appears.

### Implementation for User Story 1

- [X] T012 Create `src/cv_agent/tools/labelling.py` with `_pending_nodes` dict, `_client()`, `_project_title()`, `_register_pending_node()` helpers
- [X] T013 [US1] Implement `start_labelling_server` `@tool` in `src/cv_agent/tools/labelling.py` (starts via server_manager, polls health 60 s, returns URL JSON)
- [X] T014 [US1] Add `@app.on_event("startup")` hook in `src/cv_agent/web.py` calling `register_label_studio(config.labelling)` + `enable_auto_restart("label-studio")`
- [X] T015 [US1] Add `POST /api/labelling/start` endpoint to `src/cv_agent/web.py` (start + 60 s health poll)
- [X] T016 [US1] Add `POST /api/labelling/stop` endpoint to `src/cv_agent/web.py` (disable auto-restart + stop)
- [X] T017 [US1] Add `GET /api/labelling/status` endpoint to `src/cv_agent/web.py` (returns status/url/port/pid)
- [X] T018 [US1] Add Labelling nav item to Research group in `src/cv_agent/ui/index.html` (`data-view="labelling"`, icon `🏷️`)
- [X] T019 [US1] Add `<section id="view-labelling">` with status bar, Start/Stop/Status buttons, iframe wrapper, and progress bar to `src/cv_agent/ui/index.html`
- [X] T020 [US1] Add `labelling: loadLabellingView` to `loaders` dict in `src/cv_agent/ui/app.js`
- [X] T021 [US1] Implement `loadLabellingView()`, `lsRefreshStatus()`, `_lsApplyStatus()`, `lsStart()`, `lsStop()` in `src/cv_agent/ui/app.js`
- [X] T022 [US1] Use `window.location.hostname` (not `localhost`) for "Connect at" URL display in `src/cv_agent/ui/app.js` (FR-001a)
- [X] T023 [US1] Register `start_labelling_server` tool in `src/cv_agent/agent.py:build_tools()`

**Checkpoint**: US1 complete — user can start/stop Label Studio from the sidebar and see live status.

---

## Phase 4: User Story 2 — Create and Manage Labelling Projects (Priority: P2)

**Goal**: User can create named projects with selected annotation types; projects are listed and manageable.

**Independent Test**: POST `/api/labelling/projects` → confirm project_id returned → GET `/api/labelling/projects` → confirm project in list with correct title.

### Implementation for User Story 2

- [X] T024 [US2] Implement `create_labelling_project` `@tool` in `src/cv_agent/tools/labelling.py` (auto-names `YYYY-MM-DD_<name>`, creates project via client, optionally imports images)
- [X] T025 [US2] Implement `list_labelling_projects` `@tool` in `src/cv_agent/tools/labelling.py` (returns JSON list with task/annotation counts)
- [X] T026 [US2] Add `POST /api/labelling/projects` endpoint to `src/cv_agent/web.py` (JSON body: dataset_name, annotation_types)
- [X] T027 [US2] Add `GET /api/labelling/projects` endpoint to `src/cv_agent/web.py`
- [X] T028 [US2] Register `create_labelling_project` and `list_labelling_projects` tools in `src/cv_agent/agent.py:build_tools()`

**Checkpoint**: US2 complete — agent can create/list projects; projects are stored in Label Studio's SQLite DB.

---

## Phase 5: User Story 3 — Import Datasets and Annotate (Priority: P3)

**Goal**: User can import images from a local path into a project with live progress; files appear as annotation tasks.

**Independent Test**: Point import-stream SSE endpoint at a directory with 5 images → confirm SSE events stream with `imported/total/file` fields → tasks appear in Label Studio UI.

### Implementation for User Story 3

- [X] T029 [US3] Add `_async_gen` helper to `src/cv_agent/web.py` bridging sync generator → async SSE via `ThreadPoolExecutor`
- [X] T030 [US3] Add `GET /api/labelling/projects/{id}/import-stream` SSE endpoint to `src/cv_agent/web.py` (streams per-file progress, emits `{"done": true}` on completion)
- [X] T031 [US3] Validate supported extensions (`.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`, `.tiff`) in import endpoint and SSE error event for unsupported types
- [X] T032 [US3] Add import progress bar UI to `src/cv_agent/ui/index.html` (`#lsImportProgress`, `#lsProgressFill`, `#lsProgressText`)
- [X] T033 [US3] Implement `lsLoadPendingNodes()` and SSE listener for import progress in `src/cv_agent/ui/app.js`

**Checkpoint**: US3 complete — images import in background with live progress bar in the UI.

---

## Phase 6: User Story 4 — Export Annotations (Priority: P4)

**Goal**: User can export annotations as COCO JSON, YOLO TXT, or Pascal VOC XML to `output/labels/`.

**Independent Test**: POST `/api/labelling/projects/{id}/export` with `export_format=COCO` → confirm file written to `output/labels/.../coco/{id}.json` → validate JSON is parseable.

### Implementation for User Story 4

- [X] T034 [US4] Implement `export_annotations` `@tool` in `src/cv_agent/tools/labelling.py` (trigger export, poll, download, write to `export_path()`)
- [X] T035 [US4] Add `POST /api/labelling/projects/{id}/export` endpoint to `src/cv_agent/web.py` (JSON body: export_format, dataset_name; writes file and returns output_path)
- [X] T036 [US4] Register `export_annotations` tool in `src/cv_agent/agent.py:build_tools()`

**Checkpoint**: US4 complete — annotations can be exported to disk in all 3 formats.

---

## Phase 7: User Story 5 — Labelling as Workflow DAG Node (Priority: P5)

**Goal**: A labelling task can be inserted into a workflow DAG; node waits for user's "Mark Complete" click before signalling done.

**Independent Test**: Call `create_labelling_dag_node` tool → confirm `node_id` returned → GET `/api/labelling/nodes` shows `pending` node → POST `/api/labelling/complete/{node_id}` → node status becomes `completed`.

### Implementation for User Story 5

- [X] T037 [US5] Implement `create_labelling_dag_node` `@tool` in `src/cv_agent/tools/labelling.py` (creates project, imports images, registers in `_pending_nodes`, returns node_id JSON)
- [X] T038 [US5] Add `GET /api/labelling/nodes` endpoint to `src/cv_agent/web.py` (lists all pending/completed nodes from `_pending_nodes`)
- [X] T039 [US5] Add `POST /api/labelling/complete/{node_id}` endpoint to `src/cv_agent/web.py` (marks node completed, triggers auto-export if project_id stored)
- [X] T040 [US5] Add pending nodes panel `#lsPendingNodes` to `src/cv_agent/ui/index.html`
- [X] T041 [US5] Implement `lsMarkComplete(nodeId)` in `src/cv_agent/ui/app.js` (POST complete, refresh node list)
- [X] T042 [US5] Register `create_labelling_dag_node` tool in `src/cv_agent/agent.py:build_tools()`

**Checkpoint**: US5 complete — labelling nodes appear in the sidebar panel with a "Mark Complete" button.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Resilience, observability, edge-case handling, and spec documentation artifacts.

- [X] T043 [P] Write `specs/004-labelling-tool/research.md` with decisions D-001 → D-007
- [X] T044 [P] Write `specs/004-labelling-tool/data-model.md` with all entities, state transitions, file layout
- [X] T045 [P] Write `specs/004-labelling-tool/contracts/labelling-api.md` with all 9 REST endpoint contracts
- [X] T046 [P] Fill `specs/004-labelling-tool/plan.md` with full implementation plan (replace template)
- [X] T047 Run `.specify/scripts/bash/update-agent-context.sh claude` to update CLAUDE.md with Label Studio tech stack
- [X] T048 [P] Write `tests/unit/test_labelling_client.py` — unit tests for `build_label_config`, `project_name_format`, `export_path_convention` with mocked httpx
- [X] T049 [P] Write `tests/unit/test_labelling_tools.py` — unit tests for `register_pending_node`, `create_dag_node_returns_node_id`
- [X] T050 Add `LABEL_STUDIO_DISABLE_SECURE_COOKIE=true` and `LABEL_STUDIO_ALLOW_ORIGIN=*` env vars to `ServerSpec.env` in `server_manager.py` to mitigate iframe X-Frame-Options block (Risk 3)

---

## Dependencies

```
T001-T005 (Phase 1) → T006-T011 (Phase 2) → Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3) → Phase 6 (US4) → Phase 7 (US5)
Phase 8 tasks [P] are independent and can run anytime after Phase 2
```

## Parallel Execution Opportunities

- **Phase 1**: T004, T005 can run in parallel with T002/T003
- **Phase 2**: T007, T008 can run in parallel once T006 exists
- **Phase 3**: T018–T022 (frontend) can run in parallel with T013–T017 (backend)
- **Phase 4**: T026, T027 can run in parallel
- **Phase 8**: T043–T047 are all fully parallel

## Implementation Strategy (MVP Scope)

**MVP** = Phase 1 + Phase 2 + Phase 3 (US1 only): user can launch Label Studio from the sidebar.

**Full delivery** = all 8 phases as described above.

All Phase 3–7 tasks are pre-completed in the current codebase. Remaining work is Phase 8 unit tests (T048, T049) and iframe mitigation verification (T050).
