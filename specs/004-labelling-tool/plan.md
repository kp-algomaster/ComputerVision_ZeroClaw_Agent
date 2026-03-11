# Implementation Plan: Label Studio Integration

**Branch**: `004-labelling-tool` | **Date**: 2026-03-11 | **Spec**: [spec.md](spec.md)

## Summary

Integrate Label Studio (Apache 2.0, ≥1.10) as a managed local subprocess exposing annotation capabilities via `@tool` functions and a Labelling sidebar view. The agent can create projects, import images, and register DAG workflow checkpoints that pause until a user clicks "Mark Complete".

---

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: label-studio ≥ 1.10 (Apache 2.0), httpx (sync), FastAPI, Pydantic V2
**Storage**: Label Studio's own SQLite DB at `output/.label-studio/`; exports to `output/labels/`
**Testing**: pytest + pytest-asyncio; mocked httpx for unit tests
**Target Platform**: macOS / Linux local workstation
**Project Type**: web-service + agent tool extension
**Performance Goals**: Server ready within 30–60 s of start; import progress visible within 1 s
**Constraints**: No blocking I/O in async context; line-length 100; no AGPL deps
**Scale/Scope**: Up to 10,000 images per project; single Label Studio instance per session

---

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I. Async-First | ✅ | All FastAPI endpoints async; tools use sync httpx (same pattern as `hardware_probe.py`) |
| II. Tool-Centric | ✅ | New tools in `tools/labelling.py`; explicit registration in `build_tools()` |
| III. Config-Driven | ✅ | `LabellingConfig` in `config.py`; secrets/port via `.env` |
| IV. Streaming-First | ✅ | Import progress via SSE; startup status polls to frontend |
| V. Spec-Driven | N/A | Research pipeline spec principle; not applicable here |

No violations. Gate **passes**.

---

## Project Structure

### Documentation

```
specs/004-labelling-tool/
├── plan.md              ← this file
├── spec.md
├── research.md
├── data-model.md
└── contracts/
    └── labelling-api.md
```

### Source Code Changes

```
src/cv_agent/
├── config.py                    # ADD: LabellingConfig + AgentConfig field
├── server_manager.py            # ADD: register_label_studio(), auto-restart loop
├── labelling_client.py          # NEW: sync Label Studio REST client
├── agent.py                     # ADD: import + register labelling tools
├── tools/
│   └── labelling.py             # NEW: @tool functions
├── web.py                       # ADD: /api/labelling/* endpoints + SSE + startup hook
└── ui/
    ├── index.html               # ADD: Labelling nav item + view section
    └── app.js                   # ADD: lsStart/Stop/Status/MarkComplete JS

config/agent_config.yaml         # ADD: labelling: section
pyproject.toml                   # ADD: label-studio dependency
```

---

## Implementation Phases

### Phase 1 — Config + Dependency ✅

**`pyproject.toml`**: added `"label-studio>=1.10.0"` to dependencies.

**`config.py`**: added `LabellingConfig(BaseModel)` with `port`, `host`, `data_dir`, `auto_restart`, `api_token`; added `labelling: LabellingConfig` field to `AgentConfig`.

**`config/agent_config.yaml`**: added `labelling:` section with env-var-resolved fields.

---

### Phase 2 — Label Studio REST Client ✅

**`src/cv_agent/labelling_client.py`** — synchronous httpx client.

Key methods:
- `health() -> bool` — `GET /api/health`
- `create_project(title) -> dict` — `POST /api/projects/` with all-4-types XML label config
- `list_projects() -> list[dict]`
- `get_project(project_id) -> dict`
- `import_images(project_id, image_dir) -> Generator[dict]` — yields `{"imported", "total", "file"}` progress
- `_upload_one(project_id, path)` — `multipart/form-data` per file
- `trigger_export(project_id, export_format) -> int` — returns `export_id`
- `poll_export(project_id, export_id, max_wait=60) -> bool`
- `download_export(project_id, export_id) -> bytes`

**Label config XML**: always includes all 4 annotation types (RectangleLabels, PolygonLabels, KeyPointLabels, BrushLabels) to avoid post-creation config lock.

**Auth**: `Authorization: Token {api_token}` header; empty token = unauthenticated (local dev default).

**Export path**: `output/labels/{YYYY-MM-DD}_{dataset_name}/{format}/{project_id}.{ext}`

---

### Phase 3 — Server Manager Extension ✅

**`server_manager.py`** additions:
- `_restart_tasks: dict[str, asyncio.Task] = {}` — module-level registry
- `register_label_studio(cfg)` — creates `ServerSpec` and registers in `SERVER_REGISTRY`/`_BY_ID`
- `_auto_restart_loop(server_id)` — async task polling every 5 s, restarts on crash
- `enable_auto_restart(server_id)` / `disable_auto_restart(server_id)`
- `stop_server()` modified to call `disable_auto_restart()` before terminating

---

### Phase 4 — `@tool` Functions ✅

**`src/cv_agent/tools/labelling.py`**:

```python
_pending_nodes: dict[str, dict] = {}   # module-level DAG node registry

@tool def start_labelling_server() -> str
@tool def create_labelling_project(dataset_name, annotation_types, image_dir) -> str
@tool def list_labelling_projects() -> str
@tool def export_annotations(project_id, export_format, output_path) -> str
@tool def create_labelling_dag_node(dataset_name, image_dir, annotation_types, export_format) -> str
```

**DAG suspension**: tool registers pending node and returns `node_id`; completion is user-triggered via POST to `/api/labelling/complete/{node_id}`.

**Registration in `agent.py:build_tools()`**: all 5 tools imported and added to tools list.

---

### Phase 5 — FastAPI Endpoints ✅

**`web.py`** additions:

`_async_gen` helper: bridges sync generator → async generator using `ThreadPoolExecutor` + `loop.run_in_executor`.

Startup hook (`@app.on_event("startup")`): calls `register_label_studio(config.labelling)` + `enable_auto_restart("label-studio")`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/labelling/start` | Start LS; poll health 60 s |
| POST | `/api/labelling/stop` | Stop + disable auto-restart |
| GET | `/api/labelling/status` | Return status/url/port/pid |
| POST | `/api/labelling/projects` | Create project |
| GET | `/api/labelling/projects` | List projects |
| GET | `/api/labelling/projects/{id}/import-stream` | SSE import progress |
| POST | `/api/labelling/projects/{id}/export` | Trigger + download + write export |
| GET | `/api/labelling/nodes` | List pending DAG nodes |
| POST | `/api/labelling/complete/{node_id}` | Mark complete + auto-export |

---

### Phase 6 — Frontend ✅

**`index.html`**:
- Nav item in Research group: `<li class="nav-item" data-view="labelling">🏷️ Labelling</li>`
- `<section id="view-labelling">` with status bar, pending nodes panel, import progress bar, iframe wrapper

**`app.js`**:
- `labelling: loadLabellingView` added to `loaders` dict in `switchView()`
- Functions: `loadLabellingView`, `lsRefreshStatus`, `_lsApplyStatus`, `lsStart`, `lsStop`, `lsLoadPendingNodes`, `lsMarkComplete`
- Uses `window.location.hostname` (not `localhost`) for remote team access URL display (FR-001a)

---

## Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | Label Studio cold-start 30–60 s (Django migrations) | Medium | Poll health 60 s; frontend polls until `ready` |
| 2 | API token empty on first run | Medium | Document first-run step; advisory in status endpoint |
| 3 | Iframe blocked by X-Frame-Options | High | `LABEL_STUDIO_DISABLE_SECURE_COOKIE=true` + `LABEL_STUDIO_ALLOW_ORIGIN=*` in `start_cmd`; fallback: `window.open()` link |
| 4 | Large dataset upload slow (per-file multipart) | Low | Acceptable ≤10k; JSON task array import as future optimisation |
| 5 | Port 8080 conflict | Low | Configurable via `LABEL_STUDIO_PORT` in `.env` |

---

## Verification

### End-to-End Test Flow

1. `pip install label-studio` in `.venv`
2. Start agent: `uvicorn cv_agent.web:app --reload --port 8420`
3. Open `http://localhost:8420`, navigate to **Labelling**
4. Click **▶ Start** → verify status dot goes green within 60 s
5. Verify iframe loads (or "Connect at" URL opens Label Studio)
6. In agent chat: `"create a labelling project for road_damage dataset at output/.datasets/Emanyaser--road-damage-zero-shot/"`
7. Confirm project appears in Label Studio UI
8. Annotate 2–3 images manually
9. Click **Mark Complete** in sidebar pending nodes panel
10. In agent chat: `"export road_damage annotations as COCO"`
11. Confirm file at `output/labels/2026-03-11_road_damage/coco/<id>.json`

### Unit Tests

- `tests/test_labelling_client.py` — `test_build_label_config`, `test_project_name_format`, `test_export_path_convention` (mock httpx)
- `tests/test_labelling_tools.py` — `test_register_pending_node`, `test_create_dag_node_returns_node_id`
- `tests/test_server_manager_labelling.py` — `test_register_label_studio_spec_port`, `test_auto_restart_loop_fires`

---

## Critical Files Modified

| File | Change |
|---|---|
| `pyproject.toml` | Added `label-studio>=1.10.0` ✅ |
| `src/cv_agent/config.py` | Added `LabellingConfig`; `labelling` field in `AgentConfig` ✅ |
| `config/agent_config.yaml` | Added `labelling:` section ✅ |
| `src/cv_agent/server_manager.py` | Added `register_label_studio()`, auto-restart functions ✅ |
| `src/cv_agent/web.py` | Added startup hook + `/api/labelling/*` endpoints + SSE ✅ |
| `src/cv_agent/agent.py` | Imported + registered 5 labelling tools ✅ |
| `src/cv_agent/ui/index.html` | Added nav item + `view-labelling` section ✅ |
| `src/cv_agent/ui/app.js` | Added `loaders["labelling"]` + LS control functions ✅ |
| `src/cv_agent/labelling_client.py` | **NEW** — sync httpx REST client ✅ |
| `src/cv_agent/tools/labelling.py` | **NEW** — 5 `@tool` functions ✅ |
