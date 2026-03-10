# Research: CV-Playground

**Branch**: `002-cv-playground` | **Date**: 2026-03-10 | **Phase**: 0

## Decision Log

### 1. Canvas Library — Drawflow (MIT)

**Decision**: Use [Drawflow](https://github.com/jerosoler/Drawflow) v0.0.59 via CDN `unpkg.com`.

**Rationale**:
- Pure vanilla JS, zero dependencies — matches the existing `app.js` ES6 style (no React, no bundler)
- MIT licensed — complies with CLAUDE.md dependency policy
- Built-in drag-and-drop from external DOM elements → canvas blocks
- Native port/connection model matches the Pipeline spec (input port left, output port right)
- Ships with built-in delete node/edge support; easily extended with keyboard Delete handler
- 14 KB minified — opens in < 50 ms on localhost

**Alternatives considered**:
- **React Flow** (MIT): Ruled out — React dependency conflicts with vanilla JS app architecture; ~200 KB bundle
- **litegraph.js** (MIT): More powerful but overkill; ComfyUI-style API is significantly more complex for the scope here
- **Custom SVG/Canvas**: Full control but weeks of effort for hit-testing, port routing, zoom/pan — not justified for this feature
- **Rete.js** (MIT): Module bundler required; CDN usage unsupported

### 2. DAG Execution Strategy — asyncio.gather Fan-Out

**Decision**: Python DAG runner in `src/cv_agent/pipeline/dag_runner.py` using Kahn's algorithm for topological ordering and `asyncio.gather` for concurrent fan-out branches.

**Rationale**:
- The spec mandates direct Python orchestration (no Eko sidecar involvement)
- `asyncio.gather` provides native concurrent branch execution with independent error isolation (`return_exceptions=True`)
- Kahn's algorithm is O(V+E), produces stable topological order, and naturally detects cycles — eliminating a separate cycle-detection pass
- All `@tool` functions are already sync; `asyncio.to_thread(tool_fn, **args)` wraps them per Constitution Principle I

**Alternatives considered**:
- **Eko sidecar**: Explicitly ruled out in spec (Eko doesn't speak DAG JSON natively; avoids brittle IPC)
- **ThreadPoolExecutor**: Lower-level, does not integrate naturally with existing async FastAPI/WebSocket context
- **Celery / task queue**: Massively over-engineered for single-user local dev

### 3. WebSocket Protocol — Reuse /ws/workflows/{run_id}

**Decision**: Reuse the existing `/ws/workflows/{run_id}` WebSocket endpoint with new per-node event types added alongside the existing Eko event schema.

**Rationale**:
- Frontend already has `connectWorkflowStream(runId)` logic; minimal new JS code needed
- Reuse avoids a second WebSocket connection for pipeline execution
- New event types (`node_status`, `node_output`, `node_error`) are additive and do not break existing Eko streaming

**New event types added**:
```json
{"type": "node_status",  "node_id": "...", "status": "running|done|error"}
{"type": "node_output",  "node_id": "...", "output": "..."}
{"type": "node_error",   "node_id": "...", "error":  "..."}
{"type": "pipeline_done","run_id": "..."}
```

### 4. Pipeline Persistence — output/.workflows JSON

**Decision**: Store pipeline JSON files in `output/.workflows/` using the same path as existing Eko workflow templates (`config.workflow.storage_dir`).

**Rationale**:
- Pipelines appear in the existing **Workflows** nav section automatically (Terminology spec: "Workflow" = storage layer)
- Reuses `WorkflowManager.save_workflow_template()` pattern; no new storage infrastructure
- JSON format is human-readable and version-controllable

**Pipeline JSON schema** (stored file):
```json
{
  "id": "uuid",
  "name": "My Pipeline",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "nodes": [...],
  "edges": [...]
}
```

### 5. /api/skills Endpoint — Live build_tools() Reflection

**Decision**: New `GET /api/skills` endpoint reads the live `build_tools()` result at request time and returns a serialized `SkillDefinition` list (name, description, category, parameter_schema).

**Rationale**:
- Spec FR-004 mandates no hardcoded block catalogue — live registry reflection is the only compliant approach
- `build_tools()` already returns LangChain `StructuredTool` objects with `.name`, `.description`, and `.args_schema` (Pydantic model)
- Category assignment: mapped by tool module name prefix (tools in `vision.py` → "Vision", `paper_fetch.py` → "Research", etc.)
- `args_schema.schema()` serializes to JSON Schema for the frontend parameter panel

**Category mapping** (from module filename):
| Module | Category |
|--------|----------|
| `vision.py`, `mlx_vision.py`, `segment_anything.py`, `ocr.py` | Vision |
| `paper_fetch.py`, `equation_extract.py`, `knowledge_graph.py`, `spec_generator.py` | Research |
| `blog_writer.py`, `text_to_diagram.py` | Content |
| `delegate_*` (dynamic wrappers) | Agents |
| `remote.py`, `hardware_probe.py`, built-in shim tools | Utility |

### 6. Undo/Redo — Immutable History Stack (client-side)

**Decision**: Client-side undo/redo using a JavaScript history stack of serialized Drawflow graph snapshots. Each canvas mutation pushes a snapshot; Ctrl+Z pops; Ctrl+Y re-applies.

**Rationale**:
- Drawflow's `export()` / `import()` API serializes the full graph state in < 1 ms for typical pipeline sizes (< 20 nodes)
- No server round-trip required for undo/redo — pure UI state
- Spec FR-012a requires undo/redo for: add block, move block, delete block, add edge, delete edge, edit block parameters, clear canvas — all captured by full snapshot approach
- Stack bounded at 50 steps to limit memory (< 1 MB for typical pipelines)

**Alternatives considered**:
- **Command pattern** (individual inverse operations): More memory-efficient but significantly more code to implement per mutation type. Snapshot approach is simpler and sufficient for the scale.

### 7. Inline Parameter Panel — Right-click / Click Flyout

**Decision**: Clicking a block node opens a flyout panel rendered in a fixed right-column within the Playground sidebar (not a modal). Panel auto-populates fields from the block's parameter schema (JSON Schema → form inputs).

**Rationale**:
- Keeps user's eyes on the canvas; no context switch to a modal overlay
- JSON Schema `type` field drives input widget: `string` → `<input type="text">`, `integer`/`number` → `<input type="number">`, `boolean` → `<input type="checkbox">`, `enum` → `<select>`
- Required fields (JSON Schema `required[]`) get a red asterisk and prevent Run if empty (FR-015)

### 8. Cycle Detection — Kahn's Algorithm Reuse

**Decision**: Cycle detection runs on the frontend in JavaScript (before creating an edge) and again on the backend in the DAG runner (before execution).

**Rationale**:
- Frontend check provides immediate UX feedback with tooltip (FR-010)
- Backend check provides safety guarantee for any API client
- Kahn's algorithm implementation shared conceptually (< 30 LOC in JS, < 30 LOC in Python) — no library dependency needed
