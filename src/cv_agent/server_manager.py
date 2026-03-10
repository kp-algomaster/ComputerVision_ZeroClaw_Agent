"""Local model server lifecycle manager — start, stop, restart, health-check."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

from cv_agent.http_client import httpx


@dataclass
class ServerSpec:
    id: str
    name: str
    description: str
    url: str
    health_path: str = "/health"
    managed: bool = True            # False = external (e.g. Ollama)
    device: str = "auto"            # mps | cuda | cpu | auto
    start_cmd: list[str] = field(default_factory=list)


SERVER_REGISTRY: list[ServerSpec] = [
    ServerSpec(
        id="ollama",
        name="Ollama",
        description="Local LLM & vision inference server",
        url="http://localhost:11434",
        health_path="/api/tags",
        managed=False,
        device="auto",
    ),
    ServerSpec(
        id="img-gen",
        name="Image Generation",
        description="Stable Diffusion / SDXL image generation API",
        url="http://localhost:7860",
        health_path="/health",
        managed=True,
        device="mps",
        start_cmd=[sys.executable, "-m", "cv_agent.servers.img_gen"],
    ),
    ServerSpec(
        id="ocr",
        name="OCR Service",
        description="Monkey OCR 1.5 + PaddleOCR service",
        url="http://localhost:7861",
        health_path="/health",
        managed=True,
        device="cpu",
        start_cmd=[sys.executable, "-m", "cv_agent.servers.ocr_server"],
    ),
    ServerSpec(
        id="eko-sidecar",
        name="Eko Workflow Engine",
        description="Node.js sidecar for autonomous agentic workflows",
        url="http://localhost:7862",
        health_path="/health",
        managed=True,
        device="cpu",
        start_cmd=["sh", "-c", "cd eko_sidecar && npm install && npx playwright install chromium && node index.js"],
    ),
]

_BY_ID: dict[str, ServerSpec] = {s.id: s for s in SERVER_REGISTRY}
_procs: dict[str, asyncio.subprocess.Process] = {}
_device_overrides: dict[str, str] = {}


async def check_health(spec: ServerSpec, timeout: float = 2.0) -> bool:
    url = spec.url.rstrip("/") + spec.health_path
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return resp.status_code < 500
    except Exception:
        return False


async def start_server(server_id: str) -> str:
    spec = _BY_ID.get(server_id)
    if not spec:
        return f"Unknown server: {server_id}"
    if not spec.managed:
        return f"{spec.name} is externally managed."
    if server_id in _procs and _procs[server_id].returncode is None:
        return f"{spec.name} is already running."
    device = _device_overrides.get(server_id, spec.device)
    env_extra = {"DEVICE": device}
    import os
    env = {**os.environ, **env_extra}
    proc = await asyncio.create_subprocess_exec(
        *spec.start_cmd,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    _procs[server_id] = proc
    return f"Started {spec.name} (pid {proc.pid})."


async def stop_server(server_id: str) -> str:
    spec = _BY_ID.get(server_id)
    if not spec:
        return f"Unknown server: {server_id}"
    if not spec.managed:
        return f"{spec.name} is externally managed."
    proc = _procs.get(server_id)
    if proc is None or proc.returncode is not None:
        return f"{spec.name} is not running."
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
    _procs.pop(server_id, None)
    return f"Stopped {spec.name}."


async def restart_server(server_id: str) -> str:
    await stop_server(server_id)
    await asyncio.sleep(0.5)
    return await start_server(server_id)


def set_device(server_id: str, device: str) -> None:
    _device_overrides[server_id] = device


async def get_all_statuses() -> list[dict]:
    # Check all servers concurrently
    health_results = await asyncio.gather(
        *[check_health(spec) for spec in SERVER_REGISTRY],
        return_exceptions=True,
    )
    results = []
    for spec, healthy in zip(SERVER_REGISTRY, health_results):
        proc = _procs.get(spec.id)
        proc_running = proc is not None and proc.returncode is None
        device = _device_overrides.get(spec.id, spec.device)
        results.append({
            "id": spec.id,
            "name": spec.name,
            "description": spec.description,
            "url": spec.url,
            "managed": spec.managed,
            "device": device,
            "proc_running": proc_running,
            "healthy": healthy is True,
            "pid": proc.pid if proc_running and proc else None,
        })
    return results
