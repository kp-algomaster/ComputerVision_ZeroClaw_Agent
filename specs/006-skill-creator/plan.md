# Implementation Plan: Skill Creator

**Branch**: `006-skill-creator` | **Date**: 2026-03-12 | **Spec**: [spec.md](spec.md)

---

## Summary

Add a Skill Creator that lets users define custom skills from a Python script + optional model + power config. Skills are persisted as JSON manifests in `output/.skills/`, hot-loaded at runtime, and integrated into the Skills panel, Playground, and chat agent. Reuses existing `local_model_manager` for models and `server_manager` for power/server dependencies.

---

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: FastAPI, Pydantic V2 (existing); CodeMirror 6 via CDN (frontend editor)
**Storage**: JSON manifests at `output/.skills/<id>/manifest.json`; scripts at `output/.skills/<id>/skill.py`
**Testing**: pytest + pytest-asyncio; unit tests for validator, loader, runner
**Target Platform**: macOS (Apple Silicon primary), Linux
**Constraints**: Scripts run in-process (no container); restricted import allowlist; 120s default timeout

---

## Constitution Check

| Principle | Check | Status |
|-----------|-------|--------|
| Async-First | Skill invocation wrapped in `asyncio.to_thread()` | ✅ PASS |
| Tool-Centric | Custom skills registered via same `@tool` interface | ✅ PASS |
| Config-Driven | No hardcoded paths; `output/.skills/` follows `OUTPUT_DIR` | ✅ PASS |
| Streaming-First | Skill results returned as JSON; long-running skills emit SSE | ✅ PASS |
| Licensing | CodeMirror 6 (MIT), all deps permissive | ✅ PASS |

---

## Project Structure

### New Files

```
src/cv_agent/
├── skill_creator.py           # SkillManifest model, validator, loader, runner
specs/006-skill-creator/
├── spec.md                    # Feature specification
├── data-model.md              # Entity definitions & API contracts
├── plan.md                    # This file
└── tasks.md                   # Implementation tasks
```

### Modified Files

```
src/cv_agent/web.py            # New endpoints: /api/skills/custom/*
src/cv_agent/ui/app.js          # Skill Creator UI panel
src/cv_agent/ui/index.html      # Skill Creator section markup
src/cv_agent/ui/style.css       # Skill Creator styles
src/cv_agent/agent.py           # Load custom skills into build_tools()
```

---

## Phase 1: Core Skill CRUD (P1)

### 1.1 — SkillManifest & Validator (`skill_creator.py`)

- Pydantic V2 models: `SkillManifest`, `SkillModel`, `SkillPower`, `EnvVarSpec`
- `validate_script(source: str) -> ValidationResult`:
  - `ast.parse()` for syntax check
  - Walk AST for import nodes → check against `BLOCKED_IMPORTS` set
  - Detect entry points: functions decorated with `@tool` or named `run`
  - Return `{valid, entry_points, imports, blocked_imports, errors}`
- `BLOCKED_IMPORTS`: `subprocess`, `os.system`, `shutil.rmtree`, `eval`, `exec`, `__import__`, `importlib.import_module` (the runner uses it internally but scripts cannot)

### 1.2 — Skill Loader & Runner (`skill_creator.py`)

- `load_skill(skill_id: str) -> module`:
  - `importlib.import_module()` with custom spec loader pointing to `output/.skills/<id>/skill.py`
  - Injects env vars: `MODEL_PATH`, `MODEL_ID`, `DEVICE`, custom env vars
  - Caches loaded modules in `_SKILL_CACHE: dict[str, ModuleType]`
- `run_skill(skill_id: str, params: dict) -> dict`:
  - Load module, call `entry_point(**params)`
  - Enforce timeout via `concurrent.futures.ThreadPoolExecutor` with `timeout_s`
  - Return `{result, duration_s, output_path?}`
- `reload_skill(skill_id: str)`:
  - Evict from `sys.modules` and `_SKILL_CACHE`, re-import
- `list_skills() -> list[SkillManifest]`:
  - Scan `output/.skills/*/manifest.json`, parse, compute status
- `delete_skill(skill_id: str)`:
  - Remove directory, evict from cache

### 1.3 — API Endpoints (`web.py`)

| Endpoint | Method | Handler |
|----------|--------|---------|
| `/api/skills/custom` | GET | `list_custom_skills()` |
| `/api/skills/custom` | POST | `create_custom_skill()` |
| `/api/skills/custom/{id}` | GET | `get_custom_skill()` |
| `/api/skills/custom/{id}` | PUT | `update_custom_skill()` |
| `/api/skills/custom/{id}` | DELETE | `delete_custom_skill()` |
| `/api/skills/custom/{id}/run` | POST | `run_custom_skill()` |
| `/api/skills/custom/validate` | POST | `validate_skill_script()` |

### 1.4 — Integration with `/api/skills`

- Modify `load_skills_view()` in `web.py` to append custom skills from `list_skills()` with `category: "custom"`
- Custom skills inherit the same card format: icon, label, status badge, description

---

## Phase 2: Model & Power Attachment (P2)

### 2.1 — Model Attachment

- In Skill Creator UI: model source selector (HuggingFace / Local / Ollama)
- HuggingFace: reuse existing `/api/local-models/{id}/download` SSE stream
- Local: picker showing `get_catalog_with_status()` results
- Ollama: model name validated against `/api/models`
- Manifest stores `SkillModel` with source + id
- Runner sets `MODEL_PATH` and `MODEL_ID` env vars before calling entry point

### 2.2 — Power Configuration

- Device selector: dropdown with CPU / MPS / CUDA / Auto
- Env vars: dynamic form — add rows with name, description, required flag, default
- Server linkage: dropdown of registered servers from `get_all_statuses()`
- Runner sets `DEVICE` env var, checks env vars are present, checks server health

---

## Phase 3: UI & Playground Integration (P3)

### 3.1 — Skill Creator Panel (`app.js` + `index.html`)

- New nav item: "Skill Creator" with 🧩 icon
- Three-section form:
  - **Script**: CodeMirror 6 editor (loaded via CDN) with Python mode, inline error markers
  - **Model**: Collapsible section with source selector and model picker/download
  - **Power**: Collapsible section with device dropdown, env var rows, server picker
- Metadata fields: name, description, icon picker
- Buttons: Validate, Create/Save, Cancel
- Edit mode: pre-populate all fields from manifest

### 3.2 — Custom Skills in Skills Panel

- Custom skills appear under a "Custom" category tab
- Card actions: Run, Edit, Delete
- Status badges: ready / needs-model / needs-power

### 3.3 — Playground Integration

- Custom skills auto-appear in `/api/playground/skills` with `category: "custom"`
- Parameter schema derived from function signature → JSON Schema
- Blocks use the same execution path as built-in skills

### 3.4 — Chat Agent Integration

- `build_tools()` in `agent.py` loads custom skills via `list_skills()`
- Each ready custom skill is wrapped as a LangChain `Tool` with the manifest's description and parameter schema
- Agent can invoke custom skills by name during agentic workflows

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Malicious script code | Import allowlist + AST checks at creation; no raw `exec`/`eval` |
| Script crashes server | `asyncio.to_thread()` + ThreadPoolExecutor timeout; catch all exceptions |
| Model path injection | `MODEL_PATH` validated to be under `output/.models/` or explicit `path_override` |
| Module name conflicts | Custom skill modules loaded with unique spec names: `_cv_skill_<id>` |
| Hot-reload race | In-flight calls complete with old module; next call gets new version |
