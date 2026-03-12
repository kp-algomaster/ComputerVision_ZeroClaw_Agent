# Feature Specification: Skill Creator

**Feature Branch**: `006-skill-creator`
**Created**: 2026-03-12
**Status**: Draft
**Input**: User description: "Create skills by adding a Python script, a model, and power (compute/API configuration)."

## Overview

Add a **Skill Creator** UI and backend that lets users define custom skills without editing source code. A skill is the combination of three components:

1. **Script** — A Python file containing the skill logic (function with `@tool` or plain callable)
2. **Model** — An optional local model (HuggingFace, Ollama, or file path) the script depends on
3. **Power** — Compute/API configuration: device selection (CPU / MPS / CUDA), environment variables (API keys), or a managed server

Skills created through this flow are registered at runtime, appear in the Skills panel and CV Playground, and persist across server restarts via a JSON manifest stored in `output/.skills/`.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Create a Skill from a Python Script (Priority: P1)

A researcher has a Python script that performs edge detection using OpenCV. They open the Skill Creator, paste/upload the script, fill in a name and description, and click **Create**. The new skill immediately appears in the Skills panel with a green "ready" badge and can be invoked from chat or the Playground.

**Why this priority**: The script is the minimum viable unit of a skill. Without it, nothing else matters. A skill with just a script and no model or power dependency covers most utility tools.

**Independent Test**: Open Skill Creator, paste a trivial script (e.g., one that returns `"hello"`), give it a name, create it. Verify it appears in `/api/skills` and can be invoked via `/api/skills/{id}/run`.

**Acceptance Scenarios**:

1. **Given** the Skill Creator panel is open, **When** the user uploads or pastes a Python file, **Then** the editor preview shows the code with syntax highlighting and the system auto-detects any `@tool`-decorated functions or top-level `def run(...)` as entry points.
2. **Given** a valid script is loaded, **When** the user fills in name + description and clicks Create, **Then** the skill is saved to `output/.skills/<skill-id>/`, registered at runtime, and appears in the Skills panel.
3. **Given** a script has import errors or syntax errors, **When** the user clicks Create, **Then** a validation error is shown inline with the failing line highlighted, and the skill is NOT registered.
4. **Given** a skill was created, **When** the user invokes it from chat (e.g., "run my edge-detection skill on this image"), **Then** the agent calls the skill's entry point and streams the result back.

---

### User Story 2 — Attach a Model to a Skill (Priority: P2)

A researcher's script requires a HuggingFace model (e.g., a fine-tuned YOLO checkpoint). In the Skill Creator, they select "Model" and either enter a HuggingFace repo ID, select an already-downloaded local model, or upload weights. The model is downloaded/linked and its path is injected into the script at runtime via a `MODEL_PATH` variable.

**Why this priority**: Many CV skills need model weights. Without model attachment, users must hardcode paths — fragile and not portable.

**Independent Test**: Create a skill with a mock script that reads `MODEL_PATH` and returns "model loaded from {MODEL_PATH}". Attach a small test model. Invoke the skill and verify the path resolves correctly.

**Acceptance Scenarios**:

1. **Given** the Model section is open, **When** the user enters a HuggingFace repo ID, **Then** the system validates the repo exists and shows model size and description. Clicking "Download" streams progress via SSE using the existing model download infrastructure.
2. **Given** a model is already in `output/.models/`, **When** the user clicks "Select existing model", **Then** a picker shows all downloaded models with size and status, and the selected model is linked to the skill.
3. **Given** a model is attached, **When** the skill script runs, **Then** the environment variable `MODEL_PATH` is set to the absolute path of the model directory, and `MODEL_ID` is set to the model identifier.
4. **Given** a skill's model has not been downloaded yet, **When** the skill status is checked, **Then** it shows "needs-model" status with a download button.

---

### User Story 3 — Configure Power for a Skill (Priority: P2)

A researcher's skill needs GPU acceleration (MPS on Apple Silicon) and an API key for an external service. In the "Power" section, they select the device (CPU/MPS/CUDA/auto), add required environment variables (key name + description), and optionally link an existing managed server.

**Why this priority**: Power configuration determines whether a skill runs at all and how fast. Without it, GPU skills default to CPU, and API-dependent skills fail silently.

**Independent Test**: Create a skill with a script that prints `os.environ.get("DEVICE")`. Set power to `mps`. Run the skill and verify the output is `mps`.

**Acceptance Scenarios**:

1. **Given** the Power section is open, **When** the user selects a device from the dropdown, **Then** the skill manifest stores the device preference and it is passed to the script runtime as `DEVICE` environment variable.
2. **Given** the user adds a required environment variable (e.g., `MY_API_KEY`), **When** the skill status is checked without the env var set, **Then** the skill shows "needs-power" status with instructions to set the variable.
3. **Given** a managed server is selected (e.g., "OCR Service" on port 7861), **When** the skill runs, **Then** the system ensures the server is healthy before invoking the script, and passes `SERVER_URL` to the script.
4. **Given** a skill has all power requirements met, **When** the skill status is computed, **Then** it shows "ready" with a green badge.

---

### User Story 4 — Edit and Delete Custom Skills (Priority: P3)

A researcher wants to update a skill's script after finding a bug, or remove a skill they no longer need. They click the skill card's edit button to open the Skill Creator pre-populated with the existing configuration, make changes, and save. Or they click delete and confirm.

**Why this priority**: Iterability is essential for a creator tool. Without edit, users must delete and recreate from scratch on every change.

**Independent Test**: Create a skill, edit its script to return a different string, run it, verify the new output. Delete the skill and verify it disappears from `/api/skills`.

**Acceptance Scenarios**:

1. **Given** a custom skill exists, **When** the user clicks Edit on its card, **Then** the Skill Creator opens with all fields (script, model, power) pre-populated.
2. **Given** the user modifies the script and clicks Save, **Then** the skill is hot-reloaded — the old module is evicted from `sys.modules` and the updated script is loaded, without a server restart.
3. **Given** the user clicks Delete and confirms, **Then** the skill manifest, script file, and any linked (but not shared) model are removed, and the skill disappears from all panels.

---

### User Story 5 — Use Custom Skills in the Playground (Priority: P3)

A researcher's custom skill appears as a draggable block in the CV Playground canvas. It can be wired into pipelines alongside built-in skills like OCR and SAM3.

**Why this priority**: Playground integration is what makes custom skills composable and reusable in workflows, not just standalone tools.

**Independent Test**: Create a custom skill, open the Playground, verify the skill appears in the skill palette, drag it onto the canvas, wire it between Inputs and Outputs, and run the pipeline.

**Acceptance Scenarios**:

1. **Given** a custom skill is registered, **When** `/api/playground/skills` is called, **Then** the skill appears in the response with `category: "custom"` and its parameter schema.
2. **Given** a custom skill block is wired in a pipeline, **When** the pipeline runs, **Then** the block executes the custom script with inputs from upstream blocks and passes output downstream.

---

### Edge Cases

- **Script with dangerous imports**: Only a curated list of modules is allowed by the sandbox. Imports of `subprocess`, `os.system`, `shutil.rmtree`, or `eval`/`exec` (beyond the runner itself) are rejected at creation time with a clear error.
- **Model download fails mid-way**: The existing `stream_hf_download` retry/resume logic handles this — the skill shows "needs-model" until the download completes.
- **Two skills reference the same model**: Models are shared via `output/.models/` — deleting a skill does NOT delete a model used by other skills.
- **Script runs forever**: Skill execution has a configurable timeout (default: 120s). If exceeded, the process is killed and an error is returned.
- **Name collision**: If a skill name matches a built-in skill label, the creation is rejected with a suggestion to rename.
- **Hot-reload race**: If a skill is invoked while being edited/saved, the in-flight call completes with the old version; the next call uses the new version.

---

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Skill creation latency | < 2s (script validation + manifest write) |
| Skill invocation overhead | < 100ms added vs. direct function call |
| Max script size | 1 MB |
| Max skills | 100 custom skills |
| Persistence | JSON manifest survives server restart |
| Isolation | Scripts run in-process but with restricted imports |

---

## Constraints & Boundaries

### In Scope
- Script upload/paste with syntax validation
- Model attachment (HuggingFace download, local selection, upload)
- Power configuration (device, env vars, server linkage)
- Skill CRUD (create, read, update, delete)
- Runtime registration (Skills panel, Playground, chat agent)
- Hot-reload on edit
- Manifest persistence in `output/.skills/`

### Out of Scope
- Containerized/sandboxed execution (future — use process isolation)
- Skill marketplace or sharing between users
- Skill versioning / rollback
- Visual script builder (node-based code editor)
- Automatic parameter schema inference from undecorated functions (require `@tool` or `def run()`)

---

## Technology Choices

| Component | Choice | License | Rationale |
|-----------|--------|---------|-----------|
| Script editor | CodeMirror 6 (CDN) | MIT | Lightweight, syntax highlighting, inline errors |
| Script validation | `ast.parse()` + import allowlist | stdlib | No external deps; catches syntax errors before registration |
| Manifest storage | JSON files in `output/.skills/` | — | Matches existing patterns (sessions, workflows) |
| Model management | Existing `local_model_manager` | — | Reuse HF download, status, catalog infrastructure |
| Server management | Existing `server_manager` | — | Reuse health checks, start/stop, device selection |
| Skill runtime | `importlib.import_module()` | stdlib | Dynamic loading with module eviction for hot-reload |
