from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class BlockStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class RunStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class SkillCategory(str, Enum):
    VISION = "Vision"
    RESEARCH = "Research"
    CONTENT = "Content"
    AGENTS = "Agents"
    UTILITY = "Utility"
    SPECIAL = "Special"


class Position(BaseModel):
    x: float
    y: float


class BlockInstance(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    skill_name: str
    category: str
    position: Position
    config: dict[str, Any] = Field(default_factory=dict)
    # status is transient — excluded from serialised JSON
    status: BlockStatus = Field(default=BlockStatus.PENDING, exclude=True)


class Edge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_node_id: str
    source_port: str = "output_1"
    target_node_id: str
    target_port: str = "input_1"


class PipelineGraph(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
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


class RunContext(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    pipeline: PipelineGraph
    inputs: dict[str, Any] = Field(default_factory=dict)
    node_outputs: dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = RunStatus.RUNNING
