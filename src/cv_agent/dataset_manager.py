"""Dataset catalog — HuggingFace dataset download, status, and delete."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

_BASE_DIR = Path("output/.datasets")
_COMPLETE_SENTINEL = ".complete"


@dataclass
class DatasetEntry:
    id: str
    name: str
    desc: str
    size_gb: float
    hf_repo: str
    splits: list[str] = field(default_factory=lambda: ["train", "validation"])
    num_samples: int = 0        # approximate total
    task: str = ""              # e.g. "image-classification"
    category: str = ""


DATASET_CATALOG: dict[str, list[DatasetEntry]] = {
    "Image Classification": [
        DatasetEntry(
            id="food101", name="Food-101", hf_repo="food101",
            size_gb=5.6, num_samples=101_000,
            splits=["train", "validation"],
            task="image-classification",
            desc="101 food categories, 101K images. Perfect for fine-grained classification fine-tuning.",
        ),
        DatasetEntry(
            id="oxford-pets", name="Oxford-IIIT Pets", hf_repo="pcuenq/oxford-pets",
            size_gb=0.8, num_samples=7_349,
            splits=["train", "test"],
            task="image-classification",
            desc="37 cat and dog breeds, 7K images. Compact fine-grained benchmark.",
        ),
        DatasetEntry(
            id="cifar-100", name="CIFAR-100", hf_repo="uoft-cs/cifar100",
            size_gb=0.5, num_samples=60_000,
            splits=["train", "test"],
            task="image-classification",
            desc="100 classes, 60K images at 32×32. Classic multi-class benchmark.",
        ),
        DatasetEntry(
            id="flowers-102", name="Flowers-102", hf_repo="nelorth/oxford-flowers",
            size_gb=0.4, num_samples=8_189,
            splits=["train", "validation", "test"],
            task="image-classification",
            desc="102 flower species, 8K images. Challenging fine-grained recognition.",
        ),
        DatasetEntry(
            id="beans", name="Beans", hf_repo="AI-Lab-Makerere/beans",
            size_gb=0.1, num_samples=1_295,
            splits=["train", "validation", "test"],
            task="image-classification",
            desc="3 classes (healthy, angular leaf spot, bean rust). Small agricultural dataset.",
        ),
    ],
    "Object Detection": [
        DatasetEntry(
            id="wider-face", name="WIDER FACE", hf_repo="CASIA-IVA-Lab/WIDER_FACE",
            size_gb=3.5, num_samples=32_203,
            splits=["train", "validation"],
            task="object-detection",
            desc="Face detection benchmark, 32K images with 393K faces across 61 event categories.",
        ),
        DatasetEntry(
            id="voc2007", name="Pascal VOC 2007", hf_repo="Graphcore/voc2007",
            size_gb=0.9, num_samples=9_963,
            splits=["train", "validation", "test"],
            task="object-detection",
            desc="20 object categories, 10K images. Classic detection and segmentation benchmark.",
        ),
    ],
    "Segmentation": [
        DatasetEntry(
            id="sidewalk-semantic", name="Sidewalk Semantic", hf_repo="segments/sidewalk-semantic",
            size_gb=0.3, num_samples=1_000,
            splits=["train", "validation"],
            task="image-segmentation",
            desc="10 sidewalk categories (road, person, curb etc.), 1K images. Great for semantic segmentation.",
        ),
        DatasetEntry(
            id="scene-parse-150", name="ADE20K (Scene Parse 150)", hf_repo="zhoubolei/scene_parse_150",
            size_gb=0.8, num_samples=22_210,
            splits=["train", "validation"],
            task="image-segmentation",
            desc="150 semantic categories, 22K images. ADE20K subset for scene parsing.",
        ),
    ],
    "Document / OCR": [
        DatasetEntry(
            id="docvqa-sample", name="DocVQA Sample", hf_repo="nielsr/docvqa_1200_examples",
            size_gb=0.2, num_samples=1_200,
            splits=["train", "validation", "test"],
            task="document-qa",
            desc="1200 document VQA examples. Use with Monkey OCR or PaddleOCR fine-tuning.",
        ),
        DatasetEntry(
            id="sroie", name="SROIE (Receipt OCR)", hf_repo="darentang/sroie",
            size_gb=0.1, num_samples=1_000,
            splits=["train", "test"],
            task="ocr",
            desc="Scanned receipt OCR, 1K images. Key information extraction benchmark.",
        ),
    ],
}

# Flat lookup by id
_ALL: dict[str, DatasetEntry] = {
    e.id: e for entries in DATASET_CATALOG.values() for e in entries
}
for _cat, _entries in DATASET_CATALOG.items():
    for _e in _entries:
        _e.category = _cat


def get_dataset_local_path(dataset_id: str) -> Path:
    return _BASE_DIR / dataset_id


def is_dataset_downloaded(dataset_id: str) -> bool:
    p = get_dataset_local_path(dataset_id)
    return (p / _COMPLETE_SENTINEL).exists()


def get_downloaded_size_gb(dataset_id: str) -> float:
    p = get_dataset_local_path(dataset_id)
    if not p.exists():
        return 0.0
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return round(total / 1e9, 2)


def delete_dataset(dataset_id: str) -> None:
    p = get_dataset_local_path(dataset_id)
    if p.exists():
        shutil.rmtree(p)


def get_catalog_with_status() -> list[dict]:
    rows = []
    for category, entries in DATASET_CATALOG.items():
        for e in entries:
            downloaded = is_dataset_downloaded(e.id)
            rows.append({
                "id": e.id,
                "name": e.name,
                "category": category,
                "task": e.task,
                "desc": e.desc,
                "size_gb": e.size_gb,
                "num_samples": e.num_samples,
                "splits": e.splits,
                "hf_repo": e.hf_repo,
                "downloaded": downloaded,
                "local_size_gb": get_downloaded_size_gb(e.id) if downloaded else None,
            })
    return rows


async def stream_hf_download(dataset_id: str) -> AsyncIterator[str]:
    """Async SSE generator — streams HuggingFace dataset download progress."""
    entry = _ALL.get(dataset_id)
    if not entry:
        yield f'data: {json.dumps({"error": f"Unknown dataset: {dataset_id}"})}\n\n'
        return

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        yield f'data: {json.dumps({"error": "huggingface_hub not installed — run: pip install huggingface_hub"})}\n\n'
        return

    hf_token = os.environ.get("HF_TOKEN") or None
    local_dir = get_dataset_local_path(dataset_id)
    local_dir.mkdir(parents=True, exist_ok=True)

    # Use catalog estimate — skips slow list_repo_tree scan on large datasets
    total_gb = entry.size_gb

    progress_queue: asyncio.Queue[dict] = asyncio.Queue()

    def _download():
        # Clear stale lock files that block resume after a crash
        cache_dl_dir = local_dir / ".cache" / "huggingface" / "download"
        if cache_dl_dir.exists():
            for lock_file in cache_dl_dir.glob("*.lock"):
                lock_file.unlink(missing_ok=True)
        try:
            snapshot_download(
                repo_id=entry.hf_repo,
                repo_type="dataset",
                local_dir=str(local_dir),
                local_dir_use_symlinks=False,
                token=hf_token,
            )
            (local_dir / _COMPLETE_SENTINEL).touch()
            progress_queue.put_nowait({"status": "__done__"})
        except Exception as exc:
            progress_queue.put_nowait({"error": str(exc)})

    loop = asyncio.get_event_loop()

    dl_task = loop.run_in_executor(None, _download)
    yield f'data: {json.dumps({"status": "Starting download…", "dataset": entry.name, "hf_repo": entry.hf_repo})}\n\n'

    while not dl_task.done():
        while not progress_queue.empty():
            ev = progress_queue.get_nowait()
            yield f"data: {json.dumps(ev)}\n\n"
            if ev.get("status") == "__done__" or ev.get("error"):
                return
        current_gb = await loop.run_in_executor(None, get_downloaded_size_gb, dataset_id)
        yield f'data: {json.dumps({"status": "Downloading…", "downloaded_gb": current_gb, "total_gb": total_gb})}\n\n'
        await asyncio.sleep(1.5)

    while not progress_queue.empty():
        ev = progress_queue.get_nowait()
        yield f"data: {json.dumps(ev)}\n\n"
        if ev.get("status") == "__done__" or ev.get("error"):
            return

    yield f'data: {json.dumps({"status": "__done__"})}\n\n'
