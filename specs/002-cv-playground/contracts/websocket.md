# WebSocket Contract: CV-Playground Execution Streaming

**Branch**: `002-cv-playground` | **Date**: 2026-03-10

## Endpoint

```
ws://<host>/ws/workflows/{run_id}
```

`run_id` is obtained from `POST /api/pipelines/{pipeline_id}/run`.

This endpoint is the **existing** `/ws/workflows/{run_id}` handler, extended with new CV-Playground event types. Existing Eko event types are unchanged and unaffected.

---

## Message Direction

All messages are **server → client** (JSON text frames). The client sends no messages after connection; it only listens.

---

## Event Types

### node_status

Emitted each time a block transitions state.

```json
{
  "type": "node_status",
  "run_id": "uuid",
  "node_id": "block-instance-uuid",
  "status": "pending | running | done | error",
  "timestamp": "2026-03-10T12:00:01.000Z"
}
```

**Timing**: ≤ 200 ms after the DAG runner changes a node's status (SC-007).

**UI mapping**:
| status | visual |
|--------|--------|
| `pending` | grey border |
| `running` | blue pulsing border |
| `done` | green border + checkmark |
| `error` | red border + ✕ icon |

---

### node_output

Emitted when a block completes and produces output. The output value is passed as a string and also forwarded to the chat panel.

```json
{
  "type": "node_output",
  "run_id": "uuid",
  "node_id": "block-instance-uuid",
  "block_name": "run_ocr",
  "output": "Extracted text: Lorem ipsum...",
  "timestamp": "2026-03-10T12:00:02.500Z"
}
```

**Chat forwarding**: The output string is emitted to the main chat panel as an assistant message prefixed with `[Pipeline · <block_name>]`.

---

### node_error

Emitted when a block fails. Downstream dependent blocks are skipped (their `node_status` transitions directly to `error` with `skipped: true`).

```json
{
  "type": "node_error",
  "run_id": "uuid",
  "node_id": "block-instance-uuid",
  "block_name": "run_ocr",
  "error": "Tool unavailable: PaddleOCR server not running.",
  "skipped": false,
  "timestamp": "2026-03-10T12:00:02.000Z"
}
```

For downstream blocks that are skipped (not themselves the cause of failure):

```json
{
  "type": "node_error",
  "run_id": "uuid",
  "node_id": "downstream-block-uuid",
  "block_name": "analyze_image",
  "error": "Skipped: upstream block 'run_ocr' failed.",
  "skipped": true,
  "timestamp": "2026-03-10T12:00:02.010Z"
}
```

---

### pipeline_done

Emitted when all nodes have reached a terminal state (`done` or `error`).

```json
{
  "type": "pipeline_done",
  "run_id": "uuid",
  "status": "done | partial_error",
  "completed_nodes": 3,
  "errored_nodes": 0,
  "timestamp": "2026-03-10T12:00:05.000Z"
}
```

`partial_error` = at least one node errored but at least one independent branch completed.

---

## Sequencing Example (Linear Pipeline: Inputs → OCR → Outputs)

```
server → {"type": "node_status", "node_id": "uuid-inputs",   "status": "done"}
server → {"type": "node_output",  "node_id": "uuid-inputs",   "output": "image_path=/tmp/img.png"}
server → {"type": "node_status", "node_id": "uuid-ocr",     "status": "running"}
server → {"type": "node_status", "node_id": "uuid-ocr",     "status": "done"}
server → {"type": "node_output",  "node_id": "uuid-ocr",     "output": "Extracted text: Hello world"}
server → {"type": "node_status", "node_id": "uuid-outputs",  "status": "done"}
server → {"type": "node_output",  "node_id": "uuid-outputs",  "output": "Extracted text: Hello world"}
server → {"type": "pipeline_done", "status": "done", "completed_nodes": 3, "errored_nodes": 0}
```

---

## Backwards Compatibility

Existing Eko workflow event types (`execution`, `checkpoint`, `screenshot`, `tool_call`, `success`, `error`) are unchanged. New event types (`node_status`, `node_output`, `node_error`, `pipeline_done`) are only emitted during pipeline (Playground) runs, identified by the `run_id` prefix convention or by the absence of Eko-specific fields.

The client can distinguish pipeline runs from Eko runs by checking for the presence of `node_id` in the first received event.
