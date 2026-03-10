from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cv_agent.pipeline.models import PipelineGraph


def _slug(name: str) -> str:
    """Convert pipeline name to a filesystem-safe filename slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:80] or "pipeline"


async def save_pipeline(graph: PipelineGraph, storage_dir: str | Path, *, overwrite: bool = False) -> Path:
    """Persist a PipelineGraph as JSON.  Returns the file Path."""
    if not graph.name:
        raise ValueError("Pipeline must have a name before saving.")
    dir_path = await asyncio.to_thread(lambda: Path(storage_dir).expanduser())
    await asyncio.to_thread(dir_path.mkdir, parents=True, exist_ok=True)

    filename = f"{_slug(graph.name)}.json"
    file_path = dir_path / filename

    existing = await asyncio.to_thread(file_path.exists)
    if existing and not overwrite:
        # Caller must check for conflicts and re-call with overwrite=True
        raise FileExistsError(graph.name)

    graph = graph.model_copy(update={"updated_at": datetime.utcnow()})
    payload = graph.model_dump(mode="json")
    await asyncio.to_thread(_write_json, file_path, payload)
    return file_path


async def load_pipeline(pipeline_id: str, storage_dir: str | Path) -> PipelineGraph:
    """Load a PipelineGraph by its slug ID."""
    dir_path = Path(storage_dir).expanduser()
    file_path = dir_path / f"{pipeline_id}.json"
    exists = await asyncio.to_thread(file_path.exists)
    if not exists:
        raise FileNotFoundError(pipeline_id)
    data = await asyncio.to_thread(_read_json, file_path)
    return PipelineGraph.model_validate(data)


async def list_pipelines(storage_dir: str | Path) -> list[dict[str, Any]]:
    """Return summary dicts for all pipeline files (those containing a 'nodes' key)."""
    dir_path = Path(storage_dir).expanduser()
    exists = await asyncio.to_thread(dir_path.exists)
    if not exists:
        return []

    def _scan():
        result = []
        for fpath in sorted(dir_path.glob("*.json")):
            try:
                data = _read_json(fpath)
                if "nodes" not in data:
                    continue  # skip legacy Eko templates
                result.append({
                    "id": fpath.stem,
                    "name": data.get("name") or fpath.stem,
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "node_count": len(data.get("nodes", [])),
                    "edge_count": len(data.get("edges", [])),
                })
            except Exception:
                continue
        return result

    return await asyncio.to_thread(_scan)


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
