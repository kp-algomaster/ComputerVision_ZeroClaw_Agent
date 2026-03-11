# Claude Code Instructions

## Commit Rules

- NEVER add `Co-Authored-By` trailers or any Claude attribution to commit messages
- Keep commit messages concise: one-line subject + optional bullet body
- Use present tense imperative ("add", "fix", "update") not past tense
- Stage specific files by name — never `git add -A` or `git add .`
- Do NOT push unless explicitly asked

## Code Style

- Python 3.12+, PydanticV2, ruff line-length 100
- Async-first: use `async/await` for I/O bound operations
- Tools decorated with `@tool` from `zeroclaw_tools`
- No docstrings on trivial functions; only where logic isn't self-evident

## Dependency Licensing

- **Only use MIT or Apache 2.0 licensed libraries** (BSD-2/3-Clause also acceptable — all permissive)
- NEVER add AGPL, GPL, LGPL, or proprietary dependencies without explicit user approval
- Known rejections: `ultralytics` (AGPL-3.0)
- Preferred open-source CV stack:
  - Detection: `torchvision` (BSD-3), `transformers` (Apache 2.0), `mmdetection` (Apache 2.0)
  - Tracking: `supervision` (MIT), `norfair` (Apache 2.0), `deep_sort_realtime` (MIT)
  - Stitching/geometry: `opencv-python` (Apache 2.0), `kornia` (Apache 2.0)
  - Segmentation: SAM 2/3 via `transformers` (Apache 2.0)

## Project Conventions

- Config loaded via `load_config()` — never hardcode paths or keys
- Secrets live in `.env` only — never commit `.env`
- New tools go in `src/cv_agent/tools/` and are registered in `agent.py:build_tools()`
- `src/zeroclaw_tools/__init__.py` is the local shim — edit it if the tool interface changes

## Active Technologies
- Python 3.12 (backend DAG runner + REST endpoint); ES6 Vanilla JS (frontend canvas — no framework, matches existing `app.js` style) (002-cv-playground)
- JSON files in `output/.workflows/` (existing `WorkflowManager` pattern, same directory as Eko templates) (002-cv-playground)
- Python 3.12 + label-studio ≥ 1.10 (Apache 2.0), httpx (sync), FastAPI, Pydantic V2 (004-labelling-tool)
- Label Studio's own SQLite DB at `output/.label-studio/`; exports to `output/labels/` (004-labelling-tool)

## Recent Changes
- 002-cv-playground: Added Python 3.12 (backend DAG runner + REST endpoint); ES6 Vanilla JS (frontend canvas — no framework, matches existing `app.js` style)
