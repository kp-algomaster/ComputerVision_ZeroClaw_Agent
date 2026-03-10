# Developer Quickstart: CV-Playground

**Branch**: `002-cv-playground` | **Date**: 2026-03-10

This guide walks a developer from zero to a working CV-Playground integration in the existing dev environment.

---

## Prerequisites

- Existing dev environment set up (`.venv/`, Ollama running, uvicorn on port 8420)
- Branch checked out: `git checkout 002-cv-playground`
- Web server not required to be running — it will be started below

---

## Step 1 — Verify /api/playground/skills returns blocks

Start the server and confirm the new endpoint works:

```bash
.venv/bin/uvicorn src.cv_agent.web:app --reload --port 8420
curl -s http://127.0.0.1:8420/api/playground/skills | python3 -m json.tool | head -40
```

Expected output: JSON array of skill definitions including `Vision`, `Research`, `Content`, `Agents`, `Utility` categories, plus `__inputs__` and `__outputs__` special nodes.

> **Note**: The playground uses `/api/playground/skills` (not `/api/skills`) to avoid conflict with the existing Skills readiness endpoint.

---

## Step 2 — Open the Playground sidebar

1. Open `http://127.0.0.1:8420` in a browser
2. In the **left nav sidebar**, scroll to the **Research** section and click **⚡ Playground** (or press `Cmd+Shift+P` / `Ctrl+Shift+P`)
3. The right playground panel slides open. The chat panel remains visible and interactive alongside it on screens ≥ 1280 px.

The skill block library on the left column of the playground panel lists all blocks grouped by category. Each category is collapsible. Use the search box at the top to filter blocks.

---

## Step 3 — Build a minimal pipeline (Inputs → OCR → Outputs)

1. Drag the **Inputs** block from the `Special` category onto the canvas
2. Drag the **Run OCR** block from the `Vision` category onto the canvas
3. Drag the **Outputs** block from the `Special` category onto the canvas
4. Hover over the Inputs block's right port (circle on right edge) → drag to Run OCR's left port
5. Hover over Run OCR's right port → drag to Outputs' left port
6. Click the **Inputs** block → the parameter panel opens on the right column
7. Enter an `image_path` value (e.g. a path to any PNG on disk)
8. Click the green **Run** button in the toolbar

Expected: Each block cycles through grey → blue → green. OCR text appears in the chat panel labelled `[Pipeline · run_ocr]`.

---

## Step 4 — Test undo/redo

1. With blocks on the canvas, press `Cmd+Z` (or `Ctrl+Z`) twice
2. Two blocks disappear (most recently added)
3. Press `Cmd+Y` (or `Ctrl+Shift+Z`) — the last deleted block reappears

---

## Step 5 — Save and reload a pipeline

1. Click **Save** in the Playground toolbar
2. Name the pipeline `test-ocr` and confirm
3. Refresh the browser page (`Cmd+R`)
4. Open the Playground sidebar
5. Click **Load** → select `test-ocr`
6. The canvas restores with all blocks, edges, and parameter values intact

Saved file location: `output/.workflows/test-ocr.json`

---

## Step 6 — Run the unit tests

```bash
.venv/bin/python -m pytest tests/unit/test_dag_runner.py -v
```

Expected: All tests pass (topological sort, fan-out, error isolation, cycle detection).

---

## Key File Locations

| Component | File |
|-----------|------|
| DAG runner | `src/cv_agent/pipeline/dag_runner.py` |
| Pydantic models | `src/cv_agent/pipeline/models.py` |
| Skill registry adapter | `src/cv_agent/pipeline/skill_registry.py` |
| REST endpoints | `src/cv_agent/web.py` — search `# CV-Playground` |
| Frontend — init | `src/cv_agent/ui/app.js` — search `initPlayground` |
| Frontend — HTML | `src/cv_agent/ui/index.html` — search `playground-panel` |
| Frontend — CSS | `src/cv_agent/ui/style.css` — search `CV Playground` |
| Saved pipelines | `output/.workflows/*.json` (files with `"nodes"` key) |

---

## Common Issues

**Playground button missing from toolbar**
→ Clear browser cache or do a hard refresh (`Cmd+Shift+R`). The toolbar button is added to `index.html`; a stale cached page won't show it.

**Skill blocks not loading**
→ `GET /api/playground/skills` returned an error. Check the server console — usually a `build_tools()` import error in one of the tool modules.

**Run button stays disabled**
→ The canvas is missing a required Inputs node or Outputs node. Both must be present and connected for Run to activate.

**Canvas is blank after Load**
→ The pipeline JSON in `output/.workflows/` may be malformed. Validate it with:
```bash
python3 -c "import json; json.load(open('output/.workflows/<name>.json'))"
```

**Edge rejected (tooltip: cycles not supported)**
→ Drawing the edge would create a cycle in the graph. Restructure the blocks to maintain a DAG.
