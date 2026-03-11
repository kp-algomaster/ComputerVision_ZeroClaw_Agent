# Research: Label Studio Integration

**Feature**: 004-labelling-tool | **Date**: 2026-03-11

## Decision Log

### D-001: Label Studio as Annotation Backend
- **Decision**: Use Label Studio ≥ 1.10 (Apache 2.0)
- **Rationale**: Fully open-source, Apache 2.0 compatible with project policy, supports all 4 required annotation types natively, ships its own SQLite persistence, and provides a documented REST API
- **Alternatives considered**: CVAT (AGPL-3.0 — rejected by licensing policy), Labelbox (proprietary — rejected), custom annotation UI (too much work)

### D-002: Subprocess vs. Docker
- **Decision**: Run Label Studio as a managed subprocess via `server_manager.py`, same pattern as `img-gen` and `ocr` servers
- **Rationale**: No Docker dependency on developer machines; consistent with existing server lifecycle patterns; `asyncio.create_subprocess_exec` with health-check polling is already proven in this codebase
- **Alternatives considered**: Docker Compose (rejected — adds dependency, breaks on machines without Docker)

### D-003: Synchronous Tool Functions
- **Decision**: `@tool` functions in `labelling.py` use synchronous `httpx.Client` (not async)
- **Rationale**: `@tool` functions from `zeroclaw_tools` are called synchronously by the LangGraph ReAct loop; all other tools (`hardware_probe.py`, `ocr.py`) follow the same sync httpx pattern. No `asyncio.run()` wrapping needed
- **Alternatives considered**: Async tools with `asyncio.run()` inside (rejected — cannot call `asyncio.run` from inside a running event loop)

### D-004: Always-Include-All-4 Annotation Types in Label Config XML
- **Decision**: The Label Studio project XML config always includes all 4 annotation elements (RectangleLabels, PolygonLabels, KeyPointLabels, BrushLabels)
- **Rationale**: Label Studio's label config becomes read-only after annotations are created — changing it resets all annotations. Including all 4 types upfront avoids this risk. Annotators simply use the tools they need
- **Alternatives considered**: Per-project XML based on `annotation_types` arg (rejected — risk of accidental annotation loss on config change)

### D-005: DAG Suspension via Module-Level Dict + Mark Complete Button
- **Decision**: `create_labelling_dag_node` registers a pending node in `_pending_nodes` dict and returns immediately with a `node_id`. Completion is triggered by a POST to `/api/labelling/complete/{node_id}` from the UI
- **Rationale**: The existing ReAct loop in `zeroclaw_tools` does not support LangGraph's `interrupt()` / `Command` checkpointing API. True async suspension inside the loop would require significant shim changes. The simple approach (tool returns immediately, user manually signals completion) works correctly and is maintainable
- **Alternatives considered**: LangGraph `interrupt()` (rejected — requires checkpointer which is not wired in the shim), asyncio.Future awaited inside the tool (rejected — tools are synchronous)

### D-006: File Upload Strategy
- **Decision**: Upload images one-by-one via `multipart/form-data` POST to `/api/projects/{id}/import`
- **Rationale**: Reliable for local files of any size; allows per-file progress reporting via SSE; matches the Label Studio REST API documentation
- **Alternatives considered**: JSON task array import with local file path references (deferred — requires Label Studio local storage connector setup which adds configuration complexity)

### D-007: Export Path Convention
- **Decision**: `output/labels/{YYYY-MM-DD}_{dataset_name}/{format}/{project_id}.{ext}`
- **Rationale**: Human-readable, collision-free, groups by dataset and format, predictable for downstream tools
- **Format extensions**: COCO → `.json`, YOLO → `.zip`, VOC → `.zip`

## Label Studio REST API Reference (v1.10+)

All requests use `Authorization: Token {api_token}` header. Empty token = unauthenticated (local dev default).

| Operation | Method | Path | Body |
|---|---|---|---|
| Health | GET | `/api/health` | — |
| List projects | GET | `/api/projects/?page_size=100` | — |
| Create project | POST | `/api/projects/` | `{"title": "...", "label_config": "<xml>"}` |
| Get project | GET | `/api/projects/{id}/` | — |
| Upload image | POST | `/api/projects/{id}/import` | `multipart/form-data` |
| Trigger export | POST | `/api/projects/{id}/exports/` | `{"exportType": "COCO"}` |
| Poll export | GET | `/api/projects/{id}/exports/{eid}` | — |
| Download export | GET | `/api/projects/{id}/exports/{eid}/download` | — |

## Known Risks (from planning)

- **Iframe X-Frame-Options**: Label Studio may block iframe embedding. Mitigation: set `LABEL_STUDIO_DISABLE_SECURE_COOKIE=true` and `LABEL_STUDIO_ALLOW_ORIGIN=*` env vars; fallback to open-link button if iframe is blocked.
- **Cold-start latency**: First launch runs Django migrations (~30–60s). Health poll timeout set to 60s.
- **API token bootstrap**: Fresh install has no token. Document first-run step; status endpoint returns advisory if health passes but API calls fail.
