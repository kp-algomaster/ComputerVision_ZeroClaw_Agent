# Implementation Plan: CV-Playground

**Branch**: `002-cv-playground` | **Date**: 2026-03-10 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-cv-playground/spec.md`

## Summary

Add a collapsible right-sidebar Playground panel to the existing FastAPI + ES6 web UI that renders a node-graph pipeline builder. Users drag skill blocks (derived live from `build_tools()`) onto a canvas, wire them into a DAG, configure block parameters inline, and execute the pipeline via a new Python DAG runner. Execution status streams per-node over the existing `/ws/workflows/{run_id}` WebSocket protocol. Pipelines are saved/loaded from `output/.workflows` and appear in the existing Workflows nav section.

## Technical Context

**Language/Version**: Python 3.12 (backend DAG runner + REST endpoint); ES6 Vanilla JS (frontend canvas — no framework, matches existing `app.js` style)
**Primary Dependencies**:
- Backend: FastAPI (existing), asyncio (existing, for concurrent fan-out via `asyncio.gather`), Pydantic V2 (existing, for pipeline graph validation)
- Frontend: [Drawflow](https://github.com/jerosoler/Drawflow) v0.0.59 (MIT, CDN) — pure-JS node graph library; no new Python deps
**Storage**: JSON files in `output/.workflows/` (existing `WorkflowManager` pattern, same directory as Eko templates)
**Testing**: pytest + pytest-asyncio for DAG runner unit tests; manual E2E via browser
**Target Platform**: macOS / Linux local dev server (uvicorn on port 8420)
**Project Type**: Feature addition to existing web application
**Performance Goals**: Sidebar open ≤ 500 ms; status updates ≤ 200 ms after backend event; DAG runner overhead < 50 ms per block transition
**Constraints**: No new Python server dependencies for canvas rendering (pure-JS client-side); pipeline execution MUST NOT route through Eko sidecar; reuse `/ws/workflows/{run_id}` streaming protocol verbatim
**Scale/Scope**: Single-user local session; pipelines up to ~20 nodes; no auth/isolation required

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Async-First** | ✅ PASS | DAG runner uses `async/await` throughout; fan-out via `asyncio.gather`; no blocking calls in async context; per-node events streamed over existing WebSocket — no polling |
| **II. Tool-Centric Agent Design** | ✅ PASS | No new tool capability logic in `agent.py`; Playground reads `build_tools()` registry dynamically; DAG runner calls `@tool` functions directly; explicit registration preserved |
| **III. Config-Driven, Secret-Safe** | ✅ PASS | `output/.workflows/` path sourced from `config.workflow.storage_dir`; no hardcoded paths; no new secrets required |
| **IV. Streaming-First UI** | ✅ PASS | Per-node status events (pending→running→done/error) streamed via existing WebSocket; no blocking spinners; Drawflow state updates triggered by WS events ≤ 200 ms |
| **V. Spec-Driven Research Output** | N/A | Playground is a UI feature, not a research pipeline component |

**Gate result: PASS** — all applicable principles satisfied. Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/002-cv-playground/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── rest-api.md      # /api/skills + /api/pipelines endpoints
│   └── websocket.md     # /ws/workflows/{run_id} event schema (per-node)
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/cv_agent/
├── web.py                         # ADD: /api/skills, /api/pipelines/* endpoints; pipeline WS runner
├── ui/
│   ├── index.html                 # ADD: playground sidebar HTML, Drawflow CDN script tag
│   ├── style.css                  # ADD: playground-specific CSS variables and layout rules
│   └── app.js                     # ADD: playground init, Drawflow integration, pipeline save/load/run
├── tools/                         # NO CHANGES — read-only at runtime via build_tools()
├── agents/                        # NO CHANGES — delegated via existing delegate_* tools
└── pipeline/                      # NEW package
    ├── __init__.py
    ├── dag_runner.py              # Async DAG executor (topological sort + asyncio.gather fan-out)
    ├── models.py                  # Pydantic V2: PipelineGraph, BlockInstance, Edge, BlockStatus
    └── skill_registry.py          # Thin adapter: build_tools() → SkillDefinition list for /api/skills

output/.workflows/                  # EXISTING — pipeline JSON files saved here (same as Eko templates)

tests/
├── unit/
│   └── test_dag_runner.py         # pytest-asyncio: topological sort, fan-out, error isolation
└── integration/
    └── test_pipeline_api.py       # FastAPI TestClient: /api/skills, /api/pipelines CRUD
```

**Structure Decision**: Single-project layout extending the existing monorepo. New `src/cv_agent/pipeline/` package isolates DAG runner logic. UI changes are additive to the three existing files (`index.html`, `style.css`, `app.js`). No new top-level directories.

## Complexity Tracking

> No constitution violations requiring justification.
