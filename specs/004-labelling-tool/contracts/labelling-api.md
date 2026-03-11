# API Contracts: Label Studio Integration

**Feature**: 004-labelling-tool | **Date**: 2026-03-11

All endpoints are served by the existing FastAPI app (`web.py`) under `/api/labelling/`.
Auth: no additional auth beyond the agent's own session (Label Studio API token is server-side only).

---

## Server Lifecycle

### POST /api/labelling/start

Start the Label Studio subprocess. Polls health for up to 60 s.

**Request**: no body

**Response 200**
```json
{
  "status": "ready",
  "url": "http://localhost:8080",
  "host": "0.0.0.0",
  "port": 8080
}
```

**Response 504** (timeout — server did not become healthy within 60 s)
```json
{ "detail": "Label Studio did not become healthy within 60 s" }
```

---

### POST /api/labelling/stop

Disable auto-restart and stop the subprocess.

**Request**: no body

**Response 200**
```json
{ "message": "Label Studio stopped" }
```

---

### GET /api/labelling/status

**Response 200**
```json
{
  "status": "ready",
  "url": "http://localhost:8080",
  "host": "0.0.0.0",
  "port": 8080,
  "pid": 12345
}
```

`status` values: `stopped` | `starting` | `ready` | `restarting` | `error`

`pid` is `null` when stopped.

---

## Projects

### POST /api/labelling/projects

Create a new Label Studio project.

**Request**
```json
{
  "dataset_name": "road_damage",
  "annotation_types": "bbox,polygon"
}
```

`annotation_types`: comma-separated subset of `bbox`, `polygon`, `keypoint`, `mask`. Defaults to all 4.

**Response 200**
```json
{
  "project_id": 42,
  "title": "2026-03-11_road_damage",
  "url": "http://localhost:8080/projects/42/data"
}
```

---

### GET /api/labelling/projects

**Response 200**
```json
[
  {
    "id": 42,
    "title": "2026-03-11_road_damage",
    "task_number": 150,
    "num_tasks_with_annotations": 30
  }
]
```

---

## Image Import (SSE)

### GET /api/labelling/projects/{id}/import-stream?image_dir={path}

Server-Sent Events stream. Each event is a JSON object.

**Query params**
| Param | Type | Required | Notes |
|---|---|---|---|
| `image_dir` | `str` | yes | Absolute or relative path to image directory |

**SSE event format** (progress):
```
data: {"imported": 5, "total": 150, "file": "img_0005.jpg"}
```

**SSE event format** (completion):
```
data: {"done": true, "total": 150}
```

**SSE event format** (error):
```
data: {"error": "Directory not found: /bad/path"}
```

Supported image extensions: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`, `.tiff`.

---

## Export

### POST /api/labelling/projects/{id}/export

Trigger export, poll until ready, download, and write to disk.

**Request**
```json
{
  "export_format": "COCO",
  "dataset_name": "road_damage"
}
```

`export_format`: `COCO` | `YOLO` | `VOC`

**Response 200**
```json
{
  "output_path": "output/labels/2026-03-11_road_damage/coco/42.json",
  "format": "COCO",
  "project_id": 42
}
```

**Response 504** (export not ready within 60 s)
```json
{ "detail": "Export timed out" }
```

---

## DAG Nodes

### GET /api/labelling/nodes

List all pending/completed labelling nodes registered in the current session.

**Response 200**
```json
[
  {
    "node_id": "a3f9c12e1b4d",
    "dataset_name": "road_damage",
    "project_id": 42,
    "project_title": "2026-03-11_road_damage",
    "image_dir": "output/.datasets/road-damage/",
    "annotation_types": "bbox",
    "export_format": "COCO",
    "images_imported": 150,
    "status": "pending",
    "export_path": "",
    "created_at": "2026-03-11T10:30:00"
  }
]
```

---

### POST /api/labelling/complete/{node_id}

Mark a DAG labelling node as complete. Triggers auto-export if export_format is set.

**Request**: no body

**Response 200**
```json
{
  "node_id": "a3f9c12e1b4d",
  "status": "completed",
  "export_path": "output/labels/2026-03-11_road_damage/coco/42.json"
}
```

**Response 404**
```json
{ "detail": "Node a3f9c12e1b4d not found" }
```

`export_path` is `""` if export was not triggered (e.g., no project_id stored).
