"""Segment Anything tools using SAM3 (facebook/sam3) for image and video segmentation.

SAM3 supports text prompts, bounding box prompts, and video object tracking.
Install: git clone https://github.com/facebookresearch/sam3 && pip install -e sam3/
Weights:  download 'sam3' from the Models page (gated — requires HF access request).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from zeroclaw_tools import tool

logger = logging.getLogger(__name__)

_BASE_MODELS = Path("output/.models")
_OUTPUT_DIR = Path("output/segments")

# Module-level model cache — avoids reloading on every call
_MODEL_CACHE: dict[str, Any] = {}


# ── Checkpoint discovery ────────────────────────────────────────────────────

def _find_file(model_dir: Path, *globs: str) -> Path | None:
    """Search model_dir (and one level of subdirs) for the first file matching any glob."""
    for g in globs:
        hits = list(model_dir.glob(g))
        if hits:
            return hits[0]
        for sub in model_dir.iterdir():
            if sub.is_dir():
                hits = list(sub.glob(g))
                if hits:
                    return hits[0]
    return None


def _find_checkpoint(model_dir: Path) -> Path | None:
    # Prefer .pt (torch pickle) over .safetensors — sam3's loader uses torch.load, not safetensors
    return _find_file(model_dir, "*.pt", "*.pth", "*.safetensors")


def _find_bpe(model_dir: Path) -> Path | None:
    return _find_file(model_dir, "bpe_simple_vocab*.txt.gz", "bpe_*.json", "tokenizer*.json")


# ── Model loader ────────────────────────────────────────────────────────────

def _load_sam3_image() -> tuple[Any, Any] | None:
    """Load SAM3 image model + processor. Returns (model, processor) or None."""
    if "sam3_image" in _MODEL_CACHE:
        return _MODEL_CACHE["sam3_image"]

    model_dir = _BASE_MODELS / "sam3"
    if not ((model_dir / ".complete").exists() or _find_checkpoint(model_dir)):
        return None

    try:
        from sam3.model_builder import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor
    except ImportError:
        return None

    try:
        import torch
        device = (
            "mps" if torch.backends.mps.is_available()
            else "cuda" if torch.cuda.is_available()
            else "cpu"
        )
    except ImportError:
        device = "cpu"

    ckpt = _find_checkpoint(model_dir)

    # Prefer the BPE vocab bundled with the sam3 package (under sam3/sam3/assets/).
    # sam3.__file__ is None for namespace packages; use model_builder.__file__ instead.
    bpe: Path | None = None
    try:
        import sam3.model_builder as _mb
        _pkg_bpe = Path(_mb.__file__).parent / "assets" / "bpe_simple_vocab_16e6.txt.gz"
        if _pkg_bpe.exists():
            bpe = _pkg_bpe
    except Exception:
        pass
    if bpe is None:
        bpe = _find_file(model_dir, "bpe_simple_vocab*.txt.gz", "bpe_*.gz")

    try:
        model = build_sam3_image_model(
            checkpoint_path=str(ckpt) if ckpt else None,
            bpe_path=str(bpe) if bpe else None,
            load_from_HF=(ckpt is None),  # only hit HF if no local checkpoint
            device=device,
        )
        processor = Sam3Processor(model, device=device)
        _MODEL_CACHE["sam3_image"] = (model, processor)
        logger.info("SAM3 image model loaded from %s on %s", ckpt or "HF", device)
        return (model, processor)
    except Exception as exc:
        logger.error("SAM3 image model load failed: %s", exc)
        return None


def _load_sam3_video() -> Any | None:
    """Load SAM3 video predictor. Returns predictor or None."""
    if "sam3_video" in _MODEL_CACHE:
        return _MODEL_CACHE["sam3_video"]

    model_dir = _BASE_MODELS / "sam3"
    if not ((model_dir / ".complete").exists() or _find_checkpoint(model_dir)):
        return None

    try:
        from sam3.model_builder import build_sam3_video_predictor
    except ImportError:
        return None

    try:
        import torch
        device = (
            "mps" if torch.backends.mps.is_available()
            else "cuda" if torch.cuda.is_available()
            else "cpu"
        )
    except ImportError:
        device = "cpu"

    ckpt = _find_checkpoint(model_dir)
    bpe = _find_bpe(model_dir)

    try:
        predictor = build_sam3_video_predictor(
            checkpoint_path=str(ckpt) if ckpt else None,
            bpe_path=str(bpe) if bpe else None,
            load_from_HF=(ckpt is None),
            device=device,
        )
        _MODEL_CACHE["sam3_video"] = predictor
        logger.info("SAM3 video predictor loaded on %s", device)
        return predictor
    except Exception as exc:
        logger.error("SAM3 video predictor load failed: %s", exc)
        return None


# ── Mask visualisation ──────────────────────────────────────────────────────

_MASK_COLORS = [
    (255, 50, 50), (50, 220, 50), (50, 50, 255),
    (255, 220, 0), (220, 50, 220), (0, 220, 220),
    (255, 140, 0), (140, 0, 255),
]


def _overlay_masks(image, masks, alpha: float = 0.45):
    """Return a PIL RGBA image with coloured mask overlays."""
    import numpy as np
    from PIL import Image

    arr = np.array(image.convert("RGBA"), dtype=np.float32)
    for i, mask in enumerate(masks):
        if mask is None:
            continue
        m = mask if isinstance(mask, np.ndarray) else mask.cpu().numpy()
        if m.ndim == 3:
            m = m[0]
        if not m.any():
            continue
        r, g, b = _MASK_COLORS[i % len(_MASK_COLORS)]
        color = np.array([r, g, b, int(255 * alpha)], dtype=np.float32)
        arr[m.astype(bool)] = (
            arr[m.astype(bool)] * (1 - alpha)
            + color * alpha
        )
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _save_overlay(image_path: str, overlay_image) -> str:
    """Save overlay PNG to output/segments/ and return the path string."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(image_path).stem
    ts = int(time.time())
    out = _OUTPUT_DIR / f"{stem}_seg_{ts}.png"
    overlay_image.save(out)
    return str(out)


def _extract_masks_scores_boxes(output: dict) -> tuple[list, list, list]:
    masks = output.get("masks", []) or []
    scores = [float(s) for s in (output.get("scores") or [])]
    boxes = output.get("boxes") or []
    return masks, scores, boxes


# ── Tools ───────────────────────────────────────────────────────────────────

_NOT_AVAILABLE = (
    "SAM3 not available. "
    "Install: git clone https://github.com/facebookresearch/sam3 && pip install -e sam3/ "
    "then download the SAM3 model weights from the Models page "
    "(requires access request at hf.co/facebook/sam3)."
)


@tool
def segment_with_text(
    image_path: str,
    prompt: str,
    output_path: str = "",
) -> str:
    """Segment objects in an image using SAM3 with a natural-language text prompt.

    SAM3 detects and segments every instance that matches the description.
    Requires the SAM3 package (pip install -e sam3/) and model weights.

    Args:
        image_path: Path to the input image (JPEG, PNG, etc.).
        prompt: Natural-language description of what to segment, e.g. "person", "red car".
        output_path: Optional save path for the mask-overlay PNG. Auto-generated if empty.

    Returns:
        JSON with output_path, mask_count, scores, boxes, and model info.
    """
    from PIL import Image

    loaded = _load_sam3_image()
    if loaded is None:
        return json.dumps({"error": _NOT_AVAILABLE})

    model, processor = loaded
    try:
        image = Image.open(image_path).convert("RGB")
        state = processor.set_image(image)
        output = processor.set_text_prompt(prompt=prompt, state=state)
    except Exception as exc:
        return json.dumps({"error": f"SAM3 inference failed: {exc}"})

    masks, scores, boxes = _extract_masks_scores_boxes(output)
    overlay = _overlay_masks(image, masks)
    out_file = output_path if output_path else _save_overlay(image_path, overlay)
    if output_path:
        overlay.save(output_path)

    return json.dumps({
        "output_path": out_file,
        "mask_count": len(masks),
        "scores": [round(s, 4) for s in scores],
        "boxes": [b.tolist() if hasattr(b, "tolist") else b for b in boxes],
        "prompt": prompt,
        "model": "SAM3",
    })


@tool
def segment_with_box(
    image_path: str,
    box_json: str,
    output_path: str = "",
) -> str:
    """Segment an object in an image using SAM3 with a bounding-box prompt.

    Provide the bounding box of the region you want segmented. SAM3 returns
    a precise instance mask within that region.

    Args:
        image_path: Path to the input image.
        box_json: JSON object with pixel coords: '{"x1": 10, "y1": 20, "x2": 300, "y2": 400}'.
        output_path: Optional save path for the mask-overlay PNG. Auto-generated if empty.

    Returns:
        JSON with output_path, mask_count, scores, and model info.
    """
    from PIL import Image

    try:
        b = json.loads(box_json)
        box = [b["x1"], b["y1"], b["x2"], b["y2"]]
    except (json.JSONDecodeError, KeyError) as exc:
        return json.dumps({
            "error": f"Invalid box_json: {exc}. "
                     'Expected: {"x1": 10, "y1": 20, "x2": 300, "y2": 400}'
        })

    loaded = _load_sam3_image()
    if loaded is None:
        return json.dumps({"error": _NOT_AVAILABLE})

    model, processor = loaded
    try:
        image = Image.open(image_path).convert("RGB")
        state = processor.set_image(image)
        output = processor.add_geometric_prompt(box=box, label=True, state=state)
    except Exception as exc:
        return json.dumps({"error": f"SAM3 inference failed: {exc}"})

    masks, scores, _ = _extract_masks_scores_boxes(output)
    overlay = _overlay_masks(image, masks)
    out_file = output_path if output_path else _save_overlay(image_path, overlay)
    if output_path:
        overlay.save(output_path)

    return json.dumps({
        "output_path": out_file,
        "mask_count": len(masks),
        "scores": [round(s, 4) for s in scores],
        "box": box,
        "model": "SAM3",
    })


@tool
def segment_video(
    video_path: str,
    prompt: str,
    frame_index: int = 0,
) -> str:
    """Segment and track objects across a video using SAM3 with a text prompt.

    Initialises a SAM3 video session, adds a text prompt on the specified frame,
    and returns the segmentation output for that frame along with the session ID
    for further tracking operations.

    Args:
        video_path: Path to an MP4 video file or a directory of JPEG frames.
        prompt: Text description of the object to track, e.g. "the cyclist on the left".
        frame_index: Frame number to apply the initial prompt on (default 0).

    Returns:
        JSON with session_id, frame_index, prompt, and the segmentation outputs for the frame.
    """
    predictor = _load_sam3_video()
    if predictor is None:
        return json.dumps({"error": _NOT_AVAILABLE})

    try:
        # 1. Start session
        resp = predictor.handle_request({"type": "start_session", "resource_path": video_path})
        session_id = resp.get("session_id")
        if not session_id:
            return json.dumps({"error": "SAM3 failed to start video session", "response": resp})

        # 2. Add text prompt on the requested frame
        resp = predictor.handle_request({
            "type": "add_prompt",
            "session_id": session_id,
            "frame_index": frame_index,
            "text": prompt,
        })
        outputs = resp.get("outputs", {})
    except Exception as exc:
        return json.dumps({"error": f"SAM3 video inference failed: {exc}"})

    return json.dumps({
        "session_id": session_id,
        "frame_index": frame_index,
        "prompt": prompt,
        "model": "SAM3",
        "outputs": str(outputs),  # serialise tensors/arrays as string summary
    })
