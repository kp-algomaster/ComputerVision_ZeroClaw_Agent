"""Local (non-Ollama) model catalog — download, status, and delete via HuggingFace Hub."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import threading
import time
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
        ModelEntry(id="sd-turbo",    name="SD-Turbo",      hf_repo="stabilityai/sd-turbo",        size_gb=12.0, desc="Fast text-to-image (512×512)"),
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

# Global download state — persists across SSE reconnects, survives tab switches.
# model_id -> { status, model, downloaded_gb, total_gb, speed_mbps, error }
_ACTIVE_DOWNLOADS: dict[str, dict] = {}
_DOWNLOAD_THREADS: dict[str, threading.Thread] = {}


def get_active_downloads() -> dict[str, dict]:
    """Return a snapshot of all currently running downloads."""
    return {
        mid: dict(state)
        for mid, state in _ACTIVE_DOWNLOADS.items()
        if state.get("status") == "downloading"
    }


def reset_download(model_id: str) -> None:
    """Cancel any in-progress download and wipe all local files so the next
    call to stream_hf_download starts from byte 0."""
    # Mark state as cancelled so the SSE polling loop exits cleanly
    if model_id in _ACTIVE_DOWNLOADS:
        _ACTIVE_DOWNLOADS[model_id]["status"] = "error"
        _ACTIVE_DOWNLOADS[model_id]["error"] = "Reset by user"
    # Remove thread entry so the next call starts a fresh thread
    _DOWNLOAD_THREADS.pop(model_id, None)
    # Delete all local files (the old thread is orphaned but harmless)
    p = get_model_local_path(model_id)
    if p.exists():
        shutil.rmtree(p)


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
    """Yield SSE-formatted lines with download progress.

    Downloads run in a daemon thread that persists across SSE reconnects — if the
    browser disconnects (tab switch / reload) and reconnects, this function just
    subscribes to the already-running thread rather than starting a duplicate.
    """
    entry = _ALL.get(model_id)
    if not entry:
        yield f'data: {json.dumps({"error": f"Unknown model: {model_id}"})}\n\n'
        return
    if not entry.hf_repo:
        yield f'data: {json.dumps({"error": "No HuggingFace repo for this model (pip-based)"})}\n\n'
        return

    try:
        from huggingface_hub import snapshot_download as _snapshot_dl, list_repo_tree
    except ImportError:
        yield f'data: {json.dumps({"error": "huggingface_hub not installed — run: pip install huggingface_hub"})}\n\n'
        return

    hf_token = os.environ.get("HF_TOKEN") or None
    local_dir = get_model_local_path(model_id)
    local_dir.mkdir(parents=True, exist_ok=True)

    # ── Start background thread only if not already running ────────────────
    existing = _DOWNLOAD_THREADS.get(model_id)
    if existing is None or not existing.is_alive():
        # Initialise state (or reset if previous run errored)
        _ACTIVE_DOWNLOADS[model_id] = {
            "status": "downloading",
            "model": entry.name,
            "downloaded_gb": get_downloaded_size_gb(model_id),
            "total_gb": entry.size_gb,
            "speed_mbps": 0.0,
            "error": None,
        }

        def _hf_download_thread():
            import fnmatch

            state = _ACTIVE_DOWNLOADS[model_id]

            # Enable hf_transfer (Rust-based downloader) if available —
            # it handles read timeouts and stalls properly, unlike pure requests.
            os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

            # Resolve accurate repo size (respects ignore_patterns)
            def _matches(p: str) -> bool:
                return any(fnmatch.fnmatch(p.split("/")[-1], pat) for pat in entry.ignore_patterns)
            try:
                total = sum(
                    item.size for item in list_repo_tree(entry.hf_repo, recursive=True, token=hf_token)
                    if hasattr(item, "size") and item.size and not _matches(getattr(item, "path", ""))
                )
                state["total_gb"] = round(total / 1e9, 2)
            except Exception:
                pass  # keep catalog estimate

            # Clear stale locks so resume works after a crash
            cache_dl_dir = local_dir / ".cache" / "huggingface" / "download"
            if cache_dl_dir.exists():
                for lf in cache_dl_dir.glob("*.lock"):
                    lf.unlink(missing_ok=True)

            # snapshot_download resumes automatically from .incomplete files.
            # Retry up to 5 times to handle transient stalls / connection drops.
            max_retries = 5
            for attempt in range(1, max_retries + 1):
                try:
                    kwargs: dict = dict(
                        repo_id=entry.hf_repo,
                        local_dir=str(local_dir),
                        local_dir_use_symlinks=False,
                        token=hf_token,
                    )
                    if entry.ignore_patterns:
                        kwargs["ignore_patterns"] = entry.ignore_patterns
                    _snapshot_dl(**kwargs)
                    (local_dir / _COMPLETE_SENTINEL).touch()
                    state["status"] = "done"
                    state["downloaded_gb"] = state["total_gb"]
                    state["speed_mbps"] = 0.0
                    return
                except Exception as exc:
                    err_msg = str(exc)
                    if attempt < max_retries:
                        state["error"] = f"Retrying ({attempt}/{max_retries - 1})… {err_msg[:80]}"
                        # Clear any stale lock before retrying
                        if cache_dl_dir.exists():
                            for lf in cache_dl_dir.glob("*.lock"):
                                lf.unlink(missing_ok=True)
                        time.sleep(3)
                    else:
                        state["status"] = "error"
                        state["error"] = err_msg

        t = threading.Thread(target=_hf_download_thread, daemon=True, name=f"hf-dl-{model_id}")
        _DOWNLOAD_THREADS[model_id] = t
        t.start()

    # ── SSE polling loop — survives reconnects ──────────────────────────────
    loop = asyncio.get_event_loop()
    state = _ACTIVE_DOWNLOADS[model_id]
    yield f'data: {json.dumps({"status": f"Downloading {entry.name}…", "model": entry.name})}\n\n'

    prev_gb = state.get("downloaded_gb", 0.0)
    prev_time = time.monotonic()

    while True:
        state = _ACTIVE_DOWNLOADS.get(model_id, {})

        if state.get("status") == "error":
            yield f'data: {json.dumps({"error": state.get("error", "Download failed")})}\n\n'
            return

        if state.get("status") == "done":
            current_gb = state.get("total_gb", entry.size_gb)
            yield f'data: {json.dumps({"status": "Downloading…", "downloaded_gb": current_gb, "total_gb": current_gb, "speed_mbps": 0.0})}\n\n'
            yield f'data: {json.dumps({"status": "__done__"})}\n\n'
            return

        # Disk scan in thread pool so we don't block the event loop
        current_gb = await loop.run_in_executor(None, get_downloaded_size_gb, model_id)
        now = time.monotonic()
        elapsed = now - prev_time
        speed_mbps = round((current_gb - prev_gb) * 1000 / elapsed, 1) if elapsed > 0 and current_gb > prev_gb else 0.0
        prev_gb = current_gb
        prev_time = now

        total_gb = state.get("total_gb", entry.size_gb)
        yield f'data: {json.dumps({"status": "Downloading…", "downloaded_gb": current_gb, "total_gb": total_gb, "speed_mbps": speed_mbps})}\n\n'
        await asyncio.sleep(1.5)
