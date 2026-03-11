"""Label Studio annotation tools for the CV agent."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

from zeroclaw_tools import tool

from cv_agent.config import load_config
from cv_agent.labelling_client import LabelStudioClient, export_path

logger = logging.getLogger(__name__)

# Module-level registry of pending DAG labelling nodes
_pending_nodes: dict[str, dict] = {}


def _client() -> LabelStudioClient:
    return LabelStudioClient(load_config().labelling)


def _project_title(dataset_name: str) -> str:
    return f"{datetime.now():%Y-%m-%d}_{dataset_name.lower().replace(' ', '_')}"


def _register_pending_node(
    *,
    node_id: str,
    dataset_name: str,
    project_id: int,
    project_title: str,
    image_dir: str,
    annotation_types: str,
    export_format: str,
    images_imported: int,
) -> None:
    _pending_nodes[node_id] = {
        "node_id": node_id,
        "dataset_name": dataset_name,
        "project_id": project_id,
        "project_title": project_title,
        "image_dir": image_dir,
        "annotation_types": annotation_types,
        "export_format": export_format,
        "images_imported": images_imported,
        "status": "pending",
        "export_path": "",
        "created_at": datetime.now().isoformat(),
    }


@tool
def start_labelling_server() -> str:
    """Start the Label Studio annotation server and return the access URL.

    Waits up to 60 seconds for Label Studio to become ready.
    """
    import httpx as _httpx

    cfg = load_config().labelling
    from cv_agent.server_manager import _BY_ID, _procs, start_server  # local import
    import asyncio

    # Ensure Label Studio is registered
    from cv_agent.server_manager import register_label_studio
    register_label_studio(cfg)

    asyncio.run(start_server("label-studio"))

    client = _client()
    for _ in range(60):
        if client.health():
            url = f"http://localhost:{cfg.port}"
            return json.dumps({"status": "ready", "url": url, "port": cfg.port, "host": cfg.host})
        time.sleep(1)

    return json.dumps({"status": "starting", "message": "Label Studio is starting — check back shortly."})


@tool
def create_labelling_project(
    dataset_name: str,
    annotation_types: str = "bbox,polygon,keypoint,mask",
    image_dir: str = "",
) -> str:
    """Create a Label Studio labelling project and optionally import images.

    Args:
        dataset_name: Short name for the dataset; auto-generates project title as
            YYYY-MM-DD_<name>.
        annotation_types: Comma-separated annotation types to enable: bbox, polygon,
            keypoint, mask. All four are always included in the annotation interface.
        image_dir: Local directory of images to import. Skipped if empty.

    Returns:
        JSON with project_id, project_url, and import summary.
    """
    cfg = load_config().labelling
    client = _client()

    if not client.health():
        return json.dumps({"error": "Label Studio is not running. Call start_labelling_server first."})

    title = _project_title(dataset_name)
    project = client.create_project(title)
    project_id = project["id"]
    url = f"http://localhost:{cfg.port}/projects/{project_id}"

    imported = 0
    if image_dir:
        for event in client.import_images(project_id, image_dir):
            imported = event.get("imported", 0)

    return json.dumps({
        "project_id": project_id,
        "project_title": title,
        "project_url": url,
        "images_imported": imported,
    })


@tool
def list_labelling_projects() -> str:
    """List all Label Studio projects with their task and annotation counts."""
    client = _client()
    if not client.health():
        return json.dumps({"error": "Label Studio is not running."})

    projects = client.list_projects()
    summary = [
        {
            "id": p["id"],
            "title": p.get("title", ""),
            "task_count": p.get("task_number", 0),
            "annotation_count": p.get("num_tasks_with_annotations", 0),
        }
        for p in projects
    ]
    return json.dumps({"projects": summary, "total": len(summary)})


@tool
def export_annotations(
    project_id: int,
    export_format: str = "COCO",
    output_path: str = "",
) -> str:
    """Export annotations from a Label Studio project.

    Args:
        project_id: Label Studio project ID (integer).
        export_format: One of COCO, YOLO, or VOC. Default is COCO.
        output_path: Custom output file path. Auto-generated under output/labels/ if empty.

    Returns:
        JSON with output_path and format.
    """
    cfg = load_config().labelling
    client = _client()

    if not client.health():
        return json.dumps({"error": "Label Studio is not running."})

    fmt = export_format.upper()
    if fmt not in ("COCO", "YOLO", "VOC"):
        return json.dumps({"error": f"Unsupported format: {export_format}. Use COCO, YOLO, or VOC."})

    # Get project info for naming
    try:
        project = client.get_project(project_id)
        dataset_name = project.get("title", str(project_id))
    except Exception:
        dataset_name = str(project_id)

    export_id = client.trigger_export(project_id, fmt)
    ready = client.poll_export(project_id, export_id)
    if not ready:
        return json.dumps({"error": "Export timed out or failed."})

    data = client.download_export(project_id, export_id)

    dest = Path(output_path) if output_path else export_path(dataset_name, fmt, project_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    return json.dumps({"output_path": str(dest), "format": fmt, "project_id": project_id})


@tool
def create_labelling_dag_node(
    dataset_name: str,
    image_dir: str,
    annotation_types: str = "bbox",
    export_format: str = "COCO",
) -> str:
    """Register a human-in-the-loop labelling checkpoint for workflow DAG integration.

    Creates a Label Studio project, imports images, and returns a node_id. The workflow
    pauses — click 'Mark Complete' in the Labelling sidebar view to resume and trigger
    the annotation export.

    Args:
        dataset_name: Short name for the dataset.
        image_dir: Path to the directory of images to annotate.
        annotation_types: Comma-separated: bbox, polygon, keypoint, mask.
        export_format: Export format when Mark Complete is clicked: COCO, YOLO, or VOC.

    Returns:
        JSON with node_id, project_id, and instructions for the user.
    """
    cfg = load_config().labelling
    client = _client()

    if not client.health():
        return json.dumps({"error": "Label Studio is not running. Call start_labelling_server first."})

    title = _project_title(dataset_name)
    project = client.create_project(title)
    project_id = project["id"]

    imported = 0
    if image_dir and Path(image_dir).is_dir():
        for event in client.import_images(project_id, image_dir):
            imported = event.get("imported", 0)

    node_id = uuid.uuid4().hex[:12]
    _register_pending_node(
        node_id=node_id,
        dataset_name=dataset_name,
        project_id=project_id,
        project_title=title,
        image_dir=image_dir,
        annotation_types=annotation_types,
        export_format=export_format,
        images_imported=imported,
    )

    labelling_url = f"http://localhost:{cfg.port}/projects/{project_id}"
    return json.dumps({
        "status": "pending",
        "node_id": node_id,
        "project_id": project_id,
        "project_url": labelling_url,
        "images_imported": imported,
        "message": (
            f"Labelling session created (node {node_id}). "
            f"Open the Labelling view in the sidebar, annotate your images, "
            f"then click 'Mark Complete' to export and continue."
        ),
    })
