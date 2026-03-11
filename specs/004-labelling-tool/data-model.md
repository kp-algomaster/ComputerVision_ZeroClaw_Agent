# Data Model: Label Studio Integration

**Feature**: 004-labelling-tool | **Date**: 2026-03-11

## Entities

### LabellingConfig (Pydantic — `src/cv_agent/config.py`)
| Field | Type | Default | Notes |
|---|---|---|---|
| `port` | `int` | `8080` | Configurable via `LABEL_STUDIO_PORT` |
| `host` | `str` | `"0.0.0.0"` | Binds to all interfaces |
| `data_dir` | `str` | `"output/.label-studio"` | Label Studio SQLite DB location |
| `auto_restart` | `bool` | `True` | Agent monitors and restarts on crash |
| `api_token` | `str` | `""` | Set `LABEL_STUDIO_TOKEN` in `.env` |

### LabellingSession (runtime, `server_manager.py`)
Managed via `_procs` dict and `_BY_ID` registry. Not persisted — reconstructed from `ServerSpec` at startup.

| Attribute | Source | Notes |
|---|---|---|
| `id` | `"label-studio"` | Fixed identifier in server registry |
| `url` | `f"http://localhost:{port}"` | Derived from config |
| `status` | Derived | `stopped` / `starting` / `ready` / `restarting` / `error` |
| `pid` | `proc.pid` | Set when process is running |
| `restart_count` | `_restart_tasks` task lifecycle | Implicit via auto-restart loop |

### LabellingProject (Label Studio-owned, REST resource)
Label Studio stores this in its SQLite DB. The agent accesses it via REST.

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | Auto-assigned by Label Studio |
| `title` | `str` | Agent-generated as `YYYY-MM-DD_<dataset_name>` |
| `label_config` | `str` | XML; always includes all 4 annotation types |
| `task_number` | `int` | Count of imported images |
| `num_tasks_with_annotations` | `int` | Count of annotated images |

### AnnotationTask (Label Studio-owned)
| Field | Type | Notes |
|---|---|---|
| `id` | `int` | Auto-assigned |
| `data` | `dict` | `{"image": <url or file ref>}` |
| `annotations` | `list` | List of Annotation objects |
| `is_labeled` | `bool` | True when at least one annotation exists |

### AnnotationExport (file on disk)
| Field | Type | Notes |
|---|---|---|
| `output_path` | `Path` | `output/labels/{date}_{name}/{format}/{project_id}.{ext}` |
| `format` | `str` | `COCO` / `YOLO` / `VOC` |
| `project_id` | `int` | Source Label Studio project |
| `created_at` | `datetime` | Filesystem mtime |

### WorkflowLabellingNode (runtime, `tools/labelling.py::_pending_nodes`)
In-memory dict keyed by `node_id`. Not persisted — agent session-scoped.

| Field | Type | Notes |
|---|---|---|
| `node_id` | `str` | 12-char hex UUID fragment |
| `dataset_name` | `str` | Human-readable name |
| `project_id` | `int` | Label Studio project ID |
| `project_title` | `str` | Auto-generated title |
| `image_dir` | `str` | Source image directory |
| `annotation_types` | `str` | Comma-separated types |
| `export_format` | `str` | `COCO` / `YOLO` / `VOC` |
| `images_imported` | `int` | Count of imported images |
| `status` | `str` | `pending` / `completed` |
| `export_path` | `str` | Set after Mark Complete + auto-export |
| `created_at` | `str` | ISO datetime string |

## State Transitions

### LabellingSession
```
[not_registered] --register_label_studio()--> [stopped]
[stopped] --start_server()--> [starting] --health_check()--> [ready]
[ready] --crash--> [restarting] --start_server()--> [ready]
[ready] --stop_server()--> [stopped]
[starting] --timeout/error--> [error]
```

### WorkflowLabellingNode
```
[pending] --POST /api/labelling/complete/{node_id}--> [completed]
```

## File Layout (output/)
```
output/
├── .label-studio/          # Label Studio SQLite DB + media files (gitignored)
└── labels/
    └── {YYYY-MM-DD}_{dataset_name}/
        ├── coco/
        │   └── {project_id}.json
        ├── yolo/
        │   └── {project_id}.zip
        └── voc/
            └── {project_id}.zip
```
