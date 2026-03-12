# Data Model: Skill Creator

**Branch**: `006-skill-creator` | **Date**: 2026-03-12

---

## Entities

### SkillManifest *(persisted as JSON)*

Stored at `output/.skills/<skill-id>/manifest.json`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | `str` | auto-generated | Slug from name, e.g. `edge-detection` |
| `name` | `str` | required | Human-readable display name |
| `description` | `str` | `""` | Shown in skill card and chat tool description |
| `icon` | `str` | `"🧩"` | Emoji icon for the skill card |
| `category` | `str` | `"custom"` | Always `"custom"` for user-created skills |
| `script_file` | `str` | `"skill.py"` | Filename relative to skill directory |
| `entry_point` | `str` | `"run"` | Function name to invoke (auto-detected from `@tool` or `def run`) |
| `parameters` | `dict` | `{}` | JSON Schema for function parameters |
| `model` | `SkillModel \| null` | `null` | Optional model dependency |
| `power` | `SkillPower` | `{}` | Compute and env configuration |
| `created_at` | `str` | auto | ISO 8601 timestamp |
| `updated_at` | `str` | auto | ISO 8601 timestamp |
| `version` | `int` | `1` | Incremented on each edit/save |

---

### SkillModel *(embedded in manifest)*

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `source` | `str` | required | `"huggingface"`, `"local"`, or `"ollama"` |
| `id` | `str` | required | HF repo ID, local model ID from catalog, or Ollama model name |
| `label` | `str` | `""` | Human-readable model name |
| `size_gb` | `float \| null` | `null` | Approximate size (from HF or disk scan) |
| `path_override` | `str \| null` | `null` | Explicit path if user provides custom location |

**Runtime injection**: When the skill runs, the following env vars are set:
- `MODEL_PATH` → absolute path to `output/.models/<model-id>/` or `path_override`
- `MODEL_ID` → the `id` field value

---

### SkillPower *(embedded in manifest)*

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `device` | `str` | `"auto"` | `"cpu"`, `"mps"`, `"cuda"`, `"auto"` |
| `env_vars` | `list[EnvVarSpec]` | `[]` | Required environment variables |
| `server_id` | `str \| null` | `null` | Linked managed server from `server_manager` |
| `timeout_s` | `int` | `120` | Max execution time in seconds |

---

### EnvVarSpec *(embedded in SkillPower)*

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | `str` | required | Environment variable name (e.g. `MY_API_KEY`) |
| `description` | `str` | `""` | Help text shown in the UI |
| `required` | `bool` | `true` | If true, skill shows "needs-power" when unset |
| `default` | `str \| null` | `null` | Default value if not set in `.env` |

---

## File System Layout

```
output/.skills/
├── edge-detection/
│   ├── manifest.json          # SkillManifest
│   └── skill.py               # User's Python script
├── my-classifier/
│   ├── manifest.json
│   └── skill.py
└── _index.json                # Optional index for fast listing (auto-rebuilt)
```

Models are NOT copied into the skill directory. They stay in `output/.models/<id>/` and are referenced by ID.

---

## Status Computation

A skill's runtime status is derived from its manifest:

```
status = "ready"

if manifest.model and not is_model_downloaded(manifest.model.id):
    status = "needs-model"

if manifest.power.env_vars:
    for var in manifest.power.env_vars:
        if var.required and not os.environ.get(var.name) and not var.default:
            status = "needs-power"

if manifest.power.server_id:
    if not check_health(server_registry[manifest.power.server_id]):
        status = "needs-power"
```

---

## API Contracts

### `POST /api/skills/custom`

Create a new custom skill.

**Request**:
```json
{
    "name": "Edge Detection",
    "description": "Detect edges using Canny algorithm",
    "icon": "🔲",
    "script": "from pathlib import Path\nimport cv2\n...",
    "entry_point": "run",
    "model": {
        "source": "huggingface",
        "id": "my-org/edge-model",
        "label": "Edge Model v2"
    },
    "power": {
        "device": "mps",
        "env_vars": [{"name": "THRESHOLD", "description": "Edge threshold", "required": false, "default": "100"}],
        "server_id": null,
        "timeout_s": 60
    }
}
```

**Response** `201`:
```json
{
    "id": "edge-detection",
    "status": "ready",
    "message": "Skill created successfully"
}
```

**Response** `422` (validation error):
```json
{
    "error": "Script validation failed",
    "details": [{"line": 3, "message": "SyntaxError: unexpected EOF"}]
}
```

---

### `GET /api/skills/custom`

List all custom skills with status.

**Response** `200`:
```json
[
    {
        "id": "edge-detection",
        "name": "Edge Detection",
        "icon": "🔲",
        "description": "Detect edges using Canny algorithm",
        "status": "ready",
        "model": {"id": "my-org/edge-model", "label": "Edge Model v2"},
        "power": {"device": "mps"},
        "version": 2,
        "updated_at": "2026-03-12T14:30:00Z"
    }
]
```

---

### `PUT /api/skills/custom/{id}`

Update an existing skill (script, model, power, metadata).

**Request**: Same shape as POST (partial updates allowed).

**Response** `200`:
```json
{"id": "edge-detection", "status": "ready", "message": "Skill updated", "version": 3}
```

---

### `DELETE /api/skills/custom/{id}`

Delete a custom skill.

**Response** `200`:
```json
{"id": "edge-detection", "deleted": true}
```

---

### `POST /api/skills/custom/{id}/run`

Invoke a custom skill.

**Request**:
```json
{
    "image_path": "output/uploads/input.png",
    "threshold": 100
}
```

**Response** `200`:
```json
{
    "result": "Detected 47 edges",
    "output_path": "output/segments/input_edges.png",
    "duration_s": 1.23
}
```

---

### `POST /api/skills/custom/validate`

Validate a script without creating a skill.

**Request**:
```json
{"script": "def run(image_path: str):\n    return 'ok'"}
```

**Response** `200`:
```json
{
    "valid": true,
    "entry_points": ["run"],
    "imports": ["pathlib"],
    "blocked_imports": []
}
```

**Response** `422`:
```json
{
    "valid": false,
    "errors": [{"line": 5, "message": "Import 'subprocess' is not allowed"}]
}
```
