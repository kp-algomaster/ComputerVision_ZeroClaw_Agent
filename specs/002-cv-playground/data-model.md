# Data Model: CV-Playground

**Branch**: `002-cv-playground` | **Date**: 2026-03-10 | **Phase**: 1

## Entities

### PipelineGraph

The persisted representation of a user-assembled visual pipeline. Stored as a JSON file in `output/.workflows/`.

| Field | Type | Constraints |
|-------|------|-------------|
| `id` | `str` (UUID4) | Required, unique, immutable after creation |
| `name` | `str` | Required, 1–100 chars, unique within `output/.workflows/`; used as display name and filename slug |
| `created_at` | `datetime` | Required, ISO-8601, set on first save |
| `updated_at` | `datetime` | Required, ISO-8601, updated on every save |
| `nodes` | `list[BlockInstance]` | Required, ≥ 0 items; must contain exactly one `Inputs` node and ≥ 1 `Outputs` node for a runnable pipeline |
| `edges` | `list[Edge]` | Required, ≥ 0 items; must form a DAG (no cycles) |

**Validation rules**:
- `name` is slugified to produce the filename: `output/.workflows/<slug>.json`
- On overwrite (same name), `updated_at` is refreshed and `id` is preserved
- A pipeline may be saved in an incomplete/non-runnable state (missing Inputs/Outputs); the Run button is simply disabled in the UI

---

### BlockInstance

One instantiated copy of a skill placed on the canvas.

| Field | Type | Constraints |
|-------|------|-------------|
| `id` | `str` (UUID4) | Required, unique within a pipeline |
| `skill_name` | `str` | Required; must match a key in the live `build_tools()` registry, OR be the special value `"__inputs__"` or `"__outputs__"` |
| `category` | `str` | Required; one of `Vision \| Research \| Content \| Agents \| Utility \| Special` |
| `position` | `Position` | Required; canvas coordinates for rendering |
| `config` | `dict[str, Any]` | Required, may be empty; key-value map of user-supplied parameter overrides |
| `status` | `BlockStatus` | Transient (runtime-only); NOT persisted to JSON; default `pending` |

**State transitions** (runtime only, not stored):

```
pending → running → done
                 → error
```

---

### Position

Canvas (x, y) coordinate for a block node.

| Field | Type | Constraints |
|-------|------|-------------|
| `x` | `float` | Required |
| `y` | `float` | Required |

---

### Edge

A directed data connection between two block ports.

| Field | Type | Constraints |
|-------|------|-------------|
| `id` | `str` (UUID4) | Required, unique within a pipeline |
| `source_node_id` | `str` | Required; must reference an existing `BlockInstance.id` |
| `source_port` | `str` | Required; currently always `"output_1"` (single output port per block) |
| `target_node_id` | `str` | Required; must reference an existing `BlockInstance.id` |
| `target_port` | `str` | Required; currently always `"input_1"` (single input port per block) |

**Validation rules**:
- `source_node_id != target_node_id` (no self-loops)
- Adding an edge must not create a cycle in the graph
- Deleting a `BlockInstance` cascades and deletes all `Edge`s referencing its `id`

---

### SkillDefinition

Read-only descriptor derived from a registered `@tool` function. Never persisted; served fresh from `/api/skills` on every request.

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | `str` | Unique identifier matching `tool.name` from `build_tools()` |
| `display_name` | `str` | Human-readable label (title-cased from `name`) |
| `description` | `str` | One-line description from `tool.description` |
| `category` | `str` | Derived from source module; one of `Vision \| Research \| Content \| Agents \| Utility` |
| `parameter_schema` | `dict` | JSON Schema object from `tool.args_schema.schema()` |

---

### RunContext

Transient execution context created when the user clicks Run. Not persisted.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` (UUID4) | Used as the WebSocket path: `/ws/workflows/{run_id}` |
| `pipeline` | `PipelineGraph` | Snapshot of the pipeline at the moment Run was clicked |
| `inputs` | `dict[str, Any]` | Values from the Inputs node (image path, text, URL) |
| `node_outputs` | `dict[str, Any]` | Accumulated outputs keyed by `node_id`; populated as nodes complete |
| `status` | `RunStatus` | `running \| done \| error` |

---

## Enumerations

```python
class BlockStatus(str, Enum):
    PENDING  = "pending"   # grey  — not yet reached
    RUNNING  = "running"   # blue pulse — currently executing
    DONE     = "done"      # green — completed successfully
    ERROR    = "error"     # red   — failed; downstream dependents skipped

class RunStatus(str, Enum):
    RUNNING = "running"
    DONE    = "done"
    ERROR   = "error"

class SkillCategory(str, Enum):
    VISION    = "Vision"
    RESEARCH  = "Research"
    CONTENT   = "Content"
    AGENTS    = "Agents"
    UTILITY   = "Utility"
    SPECIAL   = "Special"   # Inputs, Outputs nodes
```

---

## Pydantic V2 Model Definitions

```python
# src/cv_agent/pipeline/models.py

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field


class BlockStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    ERROR   = "error"


class Position(BaseModel):
    x: float
    y: float


class BlockInstance(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    skill_name: str
    category: str
    position: Position
    config: dict[str, Any] = Field(default_factory=dict)
    # status is transient — excluded from JSON serialization
    status: BlockStatus = Field(default=BlockStatus.PENDING, exclude=True)


class Edge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_node_id: str
    source_port: str = "output_1"
    target_node_id: str
    target_port: str = "input_1"


class PipelineGraph(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    nodes: list[BlockInstance] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)


class SkillDefinition(BaseModel):
    name: str
    display_name: str
    description: str
    category: str
    parameter_schema: dict[str, Any]
```

---

## Storage Layout

```text
output/.workflows/
├── my-ocr-pipeline.json          # PipelineGraph (saved by Playground)
├── blog-from-arxiv.json          # PipelineGraph
├── eko-template-1.json           # Existing Eko workflow templates (unchanged)
└── ...
```

Pipeline files are distinguished from Eko templates by the presence of the `"nodes"` key in the JSON root. Both are shown in the Workflows nav section; the Playground Load dropdown filters to pipeline files only.
