# Tasks: Skill Creator

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

---

## Phase 1 — Core Skill CRUD

### T1.1 Pydantic Models & Validator
- [ ] Create `src/cv_agent/skill_creator.py`
- [ ] Define `SkillModel`, `SkillPower`, `EnvVarSpec`, `SkillManifest` (Pydantic V2)
- [ ] Define `ValidationResult` model
- [ ] Implement `BLOCKED_IMPORTS` set
- [ ] Implement `validate_script()` — ast.parse, import walk, entry-point detection
- [ ] Unit test: valid script → `{valid: true, entry_points: ["run"]}`
- [ ] Unit test: blocked import (`subprocess`) → `{valid: false, blocked_imports: ["subprocess"]}`
- [ ] Unit test: syntax error → `{valid: false, errors: [...]}`

### T1.2 Skill Loader & Runner
- [ ] Implement `_skills_dir()` — returns `output/.skills/`
- [ ] Implement `save_skill()` — write manifest.json + skill.py
- [ ] Implement `load_skill()` — importlib spec loader with env injection
- [ ] Implement `run_skill()` — thread executor with timeout
- [ ] Implement `reload_skill()` — evict from sys.modules + cache
- [ ] Implement `list_skills()` — scan manifests, compute status
- [ ] Implement `delete_skill()` — remove dir, evict cache
- [ ] Unit test: save → load → run round-trip
- [ ] Unit test: timeout enforcement (script that sleeps)
- [ ] Unit test: reload picks up new code

### T1.3 API Endpoints
- [ ] Add `POST /api/skills/custom/validate` — calls `validate_script()`
- [ ] Add `POST /api/skills/custom` — validate + save
- [ ] Add `GET /api/skills/custom` — list with status
- [ ] Add `GET /api/skills/custom/{id}` — single manifest + script source
- [ ] Add `PUT /api/skills/custom/{id}` — update manifest + script
- [ ] Add `DELETE /api/skills/custom/{id}` — delete
- [ ] Add `POST /api/skills/custom/{id}/run` — run with params
- [ ] Integration test: full CRUD lifecycle via httpx

### T1.4 Skills Panel Integration
- [ ] Modify `load_skills_view()` to append custom skills with `category: "custom"`
- [ ] Test: custom skill appears in `/api/skills` response

---

## Phase 2 — Model & Power Attachment

### T2.1 Model Attachment
- [ ] Add model source field to manifest: `huggingface | local | ollama`
- [ ] HuggingFace source: validate repo exists, link to download endpoint
- [ ] Local source: validate model ID is in `MODEL_CATALOG`
- [ ] Ollama source: validate model name format
- [ ] Runner injects `MODEL_PATH` and `MODEL_ID` before entry-point call
- [ ] Unit test: model env vars set correctly during `run_skill()`

### T2.2 Power Configuration
- [ ] Runner reads `SkillPower.device` → sets `DEVICE` env var
- [ ] Runner validates `SkillPower.env_vars` — required vars present
- [ ] Runner checks server health if `server_id` set
- [ ] Status computation: `needs-model` if model not downloaded, `needs-power` if env var missing
- [ ] Unit test: missing required env var → error, not crash

---

## Phase 3 — UI & Playground Integration

### T3.1 Skill Creator Panel
- [ ] Add nav item "Skill Creator" in `index.html`
- [ ] Add panel markup: script editor area, model section, power section, metadata fields
- [ ] Load CodeMirror 6 from CDN in `index.html`
- [ ] Wire CodeMirror to script textarea in `app.js`
- [ ] Implement validate button → `POST /api/skills/custom/validate` → inline error markers
- [ ] Implement create/save button → `POST /api/skills/custom` → success toast
- [ ] Implement edit mode → `GET /api/skills/custom/{id}` → pre-populate form
- [ ] Add model section: source dropdown, model picker, download trigger
- [ ] Add power section: device dropdown, env var rows, server dropdown
- [ ] Style new panel in `style.css`

### T3.2 Custom Skills in Skills Panel
- [ ] Add "Custom" category tab in Skills panel
- [ ] Render custom skill cards with run/edit/delete actions
- [ ] Wire delete → `DELETE /api/skills/custom/{id}` with confirmation dialog
- [ ] Wire edit → switch to Skill Creator panel in edit mode
- [ ] Wire run → `POST /api/skills/custom/{id}/run` → show result

### T3.3 Playground Integration
- [ ] Append custom skills to `/api/playground/skills` response
- [ ] Derive JSON Schema from function signature for parameter form
- [ ] Custom skill blocks use standard execution path

### T3.4 Chat Agent Integration
- [ ] In `build_tools()`, call `list_skills()` for ready custom skills
- [ ] Wrap each as `langchain.tools.Tool` with manifest description
- [ ] Test: agent can invoke custom skill by name

---

## Definition of Done

- [ ] All Phase 1 unit tests pass
- [ ] Custom skill CRUD works end-to-end via API
- [ ] Skill Creator UI panel functional (create, validate, save, edit, delete)
- [ ] Custom skills visible in Skills panel and Playground
- [ ] No `BLOCKED_IMPORTS` bypass possible
- [ ] Timeout enforced on all custom skill executions
