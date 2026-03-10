# REST API Contract: CV-Playground

**Branch**: `002-cv-playground` | **Date**: 2026-03-10

All endpoints are additive — no existing endpoints are modified.

---

## GET /api/skills

Returns all available skill blocks derived from the live `build_tools()` registry.

**Auth**: None
**Cache**: No caching (live registry reflection)

### Response 200

```json
{
  "skills": [
    {
      "name": "run_ocr",
      "display_name": "Run OCR",
      "description": "Extract text from an image using PaddleOCR.",
      "category": "Vision",
      "parameter_schema": {
        "type": "object",
        "properties": {
          "image_path": { "type": "string", "description": "Path to the image file." }
        },
        "required": ["image_path"]
      }
    },
    {
      "name": "__inputs__",
      "display_name": "Inputs",
      "description": "Pipeline entry point. Defines the data passed to the first block.",
      "category": "Special",
      "parameter_schema": {
        "type": "object",
        "properties": {
          "image_path": { "type": "string" },
          "text":       { "type": "string" },
          "url":        { "type": "string" }
        }
      }
    },
    {
      "name": "__outputs__",
      "display_name": "Outputs",
      "description": "Pipeline exit point. Captures and displays the final result.",
      "category": "Special",
      "parameter_schema": { "type": "object", "properties": {} }
    }
  ]
}
```

---

## POST /api/pipelines

Save (create or overwrite) a pipeline.

**Auth**: None
**Content-Type**: `application/json`

### Request Body

```json
{
  "name": "My OCR Pipeline",
  "nodes": [
    {
      "id": "uuid-1",
      "skill_name": "__inputs__",
      "category": "Special",
      "position": { "x": 50, "y": 200 },
      "config": { "image_path": "" }
    },
    {
      "id": "uuid-2",
      "skill_name": "run_ocr",
      "category": "Vision",
      "position": { "x": 300, "y": 200 },
      "config": {}
    },
    {
      "id": "uuid-3",
      "skill_name": "__outputs__",
      "category": "Special",
      "position": { "x": 550, "y": 200 },
      "config": {}
    }
  ],
  "edges": [
    {
      "id": "edge-uuid-1",
      "source_node_id": "uuid-1",
      "source_port": "output_1",
      "target_node_id": "uuid-2",
      "target_port": "input_1"
    },
    {
      "id": "edge-uuid-2",
      "source_node_id": "uuid-2",
      "source_port": "output_1",
      "target_node_id": "uuid-3",
      "target_port": "input_1"
    }
  ]
}
```

### Response 200 — Created (new name)

```json
{
  "status": "created",
  "id": "uuid",
  "name": "My OCR Pipeline",
  "filename": "my-ocr-pipeline.json"
}
```

### Response 409 — Name Conflict

```json
{
  "status": "conflict",
  "message": "A pipeline named 'My OCR Pipeline' already exists.",
  "existing_id": "uuid"
}
```

The client MUST display a confirmation dialog and re-submit with `"overwrite": true` if the user confirms.

### Request Body (overwrite)

```json
{
  "name": "My OCR Pipeline",
  "overwrite": true,
  "nodes": [...],
  "edges": [...]
}
```

### Response 200 — Overwrite Confirmed

```json
{
  "status": "overwritten",
  "id": "uuid",
  "name": "My OCR Pipeline",
  "filename": "my-ocr-pipeline.json"
}
```

---

## GET /api/pipelines

List all saved pipelines (pipeline files only — not Eko workflow templates).

**Auth**: None

### Response 200

```json
{
  "pipelines": [
    {
      "id": "uuid",
      "name": "My OCR Pipeline",
      "created_at": "2026-03-10T12:00:00Z",
      "updated_at": "2026-03-10T12:30:00Z",
      "node_count": 3,
      "edge_count": 2
    }
  ]
}
```

---

## GET /api/pipelines/{pipeline_id}

Load a saved pipeline by ID.

**Auth**: None

### Response 200

Full `PipelineGraph` JSON (same schema as the POST request body).

### Response 404

```json
{ "detail": "Pipeline not found." }
```

---

## POST /api/pipelines/{pipeline_id}/run

Start a pipeline execution. Returns a `run_id` for WebSocket connection.

**Auth**: None
**Content-Type**: `application/json`

### Request Body

```json
{
  "inputs": {
    "image_path": "/path/to/image.png",
    "text": "",
    "url": ""
  }
}
```

### Response 200

```json
{
  "run_id": "uuid",
  "ws_url": "/ws/workflows/uuid"
}
```

The client immediately connects to `ws_url` to receive streaming execution events.

---

## Error Schema (all endpoints)

```json
{
  "detail": "Human-readable error message."
}
```

HTTP 422 is returned for Pydantic validation failures (malformed request body).
