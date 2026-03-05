"""Local (non-Ollama) model catalog — download, status, and delete via HuggingFace Hub."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

_BASE_DIR = Path("output/.models")


@dataclass
class ModelEntry:
    id: str
    name: str
    desc: str
    size_gb: float
    hf_repo: str | None = None      # None → pip package only
    pip_pkg: str | None = None      # e.g. "paddleocr"
    ignore_patterns: list[str] = field(default_factory=list)  # skip on snapshot_download
    category: str = ""


MODEL_CATALOG: dict[str, list[ModelEntry]] = {
    "Image Generation": [
        ModelEntry(id="sd-turbo",    name="SD-Turbo",      hf_repo="stabilityai/sd-turbo",        size_gb=4.8,  desc="Fast text-to-image (512×512)"),
        ModelEntry(id="sdxl-turbo",  name="SDXL-Turbo",    hf_repo="stabilityai/sdxl-turbo",      size_gb=6.5,  desc="Higher quality text-to-image (512×512)"),
        ModelEntry(id="deepgen-1.0", name="DeepGen 1.0",   hf_repo="deepgenteam/DeepGen-1.0",     size_gb=16.4, desc="5B unified image gen + editing: text-to-image, reasoning, text rendering",
                   ignore_patterns=["*.zip.part-*"]),
    ],
    "Video Generation": [
        ModelEntry(id="svd",    name="Stable Video Diffusion",    hf_repo="stabilityai/stable-video-diffusion-img2vid",    size_gb=9.2, desc="Image-to-video, 14 frames"),
        ModelEntry(id="svd-xt", name="Stable Video Diffusion XT", hf_repo="stabilityai/stable-video-diffusion-img2vid-xt", size_gb=9.2, desc="Image-to-video, 25 frames"),
    ],
    "OCR": [
        ModelEntry(id="monkey-ocr", name="Monkey OCR 1.5", hf_repo="echo840/MonkeyOCR",  size_gb=8.0, desc="Document OCR with layout understanding"),
        ModelEntry(id="paddleocr",  name="PaddleOCR",      hf_repo=None, pip_pkg="paddleocr", size_gb=0.5, desc="Multi-language OCR (auto-downloads on first use)"),
    ],
    "Segmentation": [
        ModelEntry(id="sam3",          name="SAM 3",          hf_repo="facebook/sam3",                   size_gb=6.9, desc="Segment Anything v3 — image+video, text prompts, 848M params (gated: request access at hf.co/facebook/sam3)"),
        ModelEntry(id="sam2.1-large",  name="SAM 2.1 Large",  hf_repo="facebook/sam2.1-hiera-large",     size_gb=2.5, desc="Segment Anything v2.1 — improved occlusion handling"),
        ModelEntry(id="sam2.1-small",  name="SAM 2.1 Small",  hf_repo="facebook/sam2.1-hiera-small",     size_gb=0.2, desc="Segment Anything v2.1 — lightweight"),
        ModelEntry(id="sam2-large",    name="SAM 2 Large",    hf_repo="facebook/sam2-hiera-large",       size_gb=2.5, desc="Segment Anything v2 — best accuracy"),
        ModelEntry(id="sam2-base",     name="SAM 2 Base+",    hf_repo="facebook/sam2-hiera-base-plus",   size_gb=0.8, desc="Segment Anything v2 — balanced"),
    ],
}

# Flat lookup by id
_ALL: dict[str, ModelEntry] = {
    m.id: m for entries in MODEL_CATALOG.values() for m in entries
}
for _cat, _entries in MODEL_CATALOG.items():
    for _m in _entries:
        _m.category = _cat


def get_model_local_path(model_id: str) -> Path:
    return _BASE_DIR / model_id


_COMPLETE_SENTINEL = ".complete"


def is_model_downloaded(model_id: str) -> bool:
    entry = _ALL.get(model_id)
    if not entry:
        return False
    if entry.pip_pkg:
        return importlib.util.find_spec(entry.pip_pkg.replace("-", "_").split(".")[0]) is not None
    p = get_model_local_path(model_id)
    return (p / _COMPLETE_SENTINEL).exists()


def get_downloaded_size_gb(model_id: str) -> float:
    p = get_model_local_path(model_id)
    if not p.exists():
        return 0.0
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return round(total / 1e9, 2)


def delete_model(model_id: str) -> None:
    p = get_model_local_path(model_id)
    if p.exists():
        shutil.rmtree(p)


def get_catalog_with_status() -> list[dict]:
    rows = []
    for category, entries in MODEL_CATALOG.items():
        for m in entries:
            downloaded = is_model_downloaded(m.id)
            rows.append({
                "id": m.id,
                "name": m.name,
                "category": category,
                "desc": m.desc,
                "size_gb": m.size_gb,
                "hf_repo": m.hf_repo,
                "pip_pkg": m.pip_pkg,
                "downloaded": downloaded,
                "local_size_gb": get_downloaded_size_gb(m.id) if downloaded else None,
            })
    return rows


async def stream_hf_download(model_id: str) -> AsyncIterator[str]:
    """Yield SSE-formatted lines with download progress."""
    entry = _ALL.get(model_id)
    if not entry:
        yield f'data: {json.dumps({"error": f"Unknown model: {model_id}"})}\n\n'
        return
    if not entry.hf_repo:
        yield f'data: {json.dumps({"error": "No HuggingFace repo for this model (pip-based)"})}\n\n'
        return

    try:
        from huggingface_hub import snapshot_download, list_repo_tree
    except ImportError:
        yield f'data: {json.dumps({"error": "huggingface_hub not installed — run: pip install huggingface_hub"})}\n\n'
        return

    hf_token = os.environ.get("HF_TOKEN") or None

    # Resolve actual repo size so progress % is accurate (respects ignore_patterns)
    def _matches_ignore(path: str) -> bool:
        import fnmatch
        return any(fnmatch.fnmatch(path.split("/")[-1], pat) for pat in entry.ignore_patterns)

    def _get_repo_size_gb(repo_id: str) -> float:
        try:
            total = sum(
                item.size for item in list_repo_tree(repo_id, recursive=True, token=hf_token)
                if hasattr(item, "size") and item.size and not _matches_ignore(getattr(item, "path", ""))
            )
            return round(total / 1e9, 2)
        except Exception:
            return entry.size_gb  # fall back to catalog estimate

    local_dir = get_model_local_path(model_id)
    local_dir.mkdir(parents=True, exist_ok=True)

    progress_queue: asyncio.Queue[dict] = asyncio.Queue()

    def _hf_download():
        # Clear stale lock files that block resume after a crash
        cache_dl_dir = local_dir / ".cache" / "huggingface" / "download"
        if cache_dl_dir.exists():
            for lock_file in cache_dl_dir.glob("*.lock"):
                lock_file.unlink(missing_ok=True)
        try:
            from huggingface_hub import snapshot_download as _dl
            kwargs: dict = dict(
                repo_id=entry.hf_repo,
                local_dir=str(local_dir),
                local_dir_use_symlinks=False,
                token=hf_token,
            )
            if entry.ignore_patterns:
                kwargs["ignore_patterns"] = entry.ignore_patterns
            _dl(**kwargs)
            (local_dir / _COMPLETE_SENTINEL).touch()
            progress_queue.put_nowait({"status": "__done__"})
        except Exception as exc:
            progress_queue.put_nowait({"error": str(exc)})

    yield f'data: {json.dumps({"status": "Resolving repo size…", "model": entry.name})}\n\n'
    loop = asyncio.get_event_loop()
    total_gb = await loop.run_in_executor(None, _get_repo_size_gb, entry.hf_repo)

    # Run blocking download in thread; emit periodic status pings while waiting
    dl_task = loop.run_in_executor(None, _hf_download)

    yield f'data: {json.dumps({"status": "Starting download…", "model": entry.name, "hf_repo": entry.hf_repo})}\n\n'

    while not dl_task.done():
        # Drain any queued progress events
        while not progress_queue.empty():
            ev = progress_queue.get_nowait()
            yield f"data: {json.dumps(ev)}\n\n"
            if ev.get("status") == "__done__" or ev.get("error"):
                return
        # Emit a heartbeat with local dir size so UI can show growth
        # Run in executor — rglob scan is blocking I/O and must not stall the event loop
        current_gb = await loop.run_in_executor(None, get_downloaded_size_gb, model_id)
        yield f'data: {json.dumps({"status": "Downloading…", "downloaded_gb": current_gb, "total_gb": total_gb})}\n\n'
        await asyncio.sleep(1.5)

    # Final drain
    while not progress_queue.empty():
        ev = progress_queue.get_nowait()
        yield f"data: {json.dumps(ev)}\n\n"
        if ev.get("status") == "__done__" or ev.get("error"):
            return

    yield f'data: {json.dumps({"status": "__done__"})}\n\n'
