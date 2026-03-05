"""Client manager for interacting with the local Node.js Eko orchestration sidecar."""

from __future__ import annotations

import asyncio
import uuid
import logging
from typing import Any, AsyncGenerator

import httpx

from cv_agent.config import load_config

logger = logging.getLogger(__name__)

class WorkflowManager:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.base_url = self.config.workflow.eko_sidecar_url.rstrip("/")

    async def submit_workflow(self, description: str) -> dict[str, Any]:
        """Submit a natural language workflow description to Eko for execution."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.base_url}/workflow/run",
                    json={"description": description}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to submit workflow to Eko sidecar: {e}")
            raise

    async def stream_workflow_status(self, run_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """
        Stream the real-time execution status of a specific workflow.
        Connects to the Eko sidecar SSE endpoint and yields status updates.
        """
        # Note: We will proxy this SSE stream to the frontend in cv_agent/web.py
        # Current sidecar doesn't implement SSE yet (T008a implementation phase)
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", f"{self.base_url}/workflow/{run_id}/stream") as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        if line.startswith("data: "):
                            import json
                            try:
                                data = json.loads(line[6:])
                                yield data
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            logger.error(f"Failed to stream workflow {run_id} from Eko sidecar: {e}")
            yield {"error": str(e), "status": "failed"}

    async def get_workflow_templates(self) -> list[dict[str, Any]]:
        """Retrieve all saved workflow templates."""
        import os
        import json
        templates = []
        os.makedirs(self.config.workflow.storage_dir, exist_ok=True)
        for filename in os.listdir(self.config.workflow.storage_dir):
            if filename.endswith(".json"):
                with open(os.path.join(self.config.workflow.storage_dir, filename), "r") as f:
                    try:
                        data = json.load(f)
                        data["id"] = filename[:-5]
                        templates.append(data)
                    except json.JSONDecodeError:
                        pass
        return templates

    async def save_workflow_template(self, name: str, description: str, steps: list = None) -> dict[str, Any]:
        """Save a completed workflow run or description as a reusable template."""
        import os
        import json
        import re
        os.makedirs(self.config.workflow.storage_dir, exist_ok=True)
        
        safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name).lower()
        if not safe_name:
            safe_name = "template"
            
        filepath = os.path.join(self.config.workflow.storage_dir, f"{safe_name}.json")
        data = {
            "name": name,
            "description": description,
            "steps": steps or []
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
            
        return {"status": "success", "template_name": name, "id": safe_name}

    async def resolve_checkpoint(self, checkpoint_id: str, approved: bool, feedback: str = "") -> dict[str, Any]:
        """Approve or reject a human-in-the-loop checkpoint."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.base_url}/workflow/checkpoint/{checkpoint_id}",
                    json={"approved": approved, "feedback": feedback}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to resolve checkpoint {checkpoint_id}: {e}")
            raise


# Singleton instance
workflow_manager = WorkflowManager()
