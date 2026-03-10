"""Segment Anything tools using SAM3 (facebook/sam3) or SAM3-MLX (mlx-community/sam3-image).

SAM3 supports text prompts, bounding box prompts, and video object tracking.
Install: git clone https://github.com/facebookresearch/sam3 && pip install -e sam3/
Weights:  download 'sam3' or 'sam3-mlx' from the Models page.
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
        # SAM3 has unresolved MPS kernel bugs ("Placeholder tensor is empty").
        # Use CUDA if available, otherwise CPU. MPS is skipped intentionally.
        device = "cuda" if torch.cuda.is_available() else "cpu"
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
        # Wrap in torch.device("cpu") context to prevent any sub-module from
        # accidentally creating tensors on MPS (Apple Silicon) during __init__.
        import torch
        with torch.device(device):
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
        device = "cuda" if torch.cuda.is_available() else "cpu"
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


# ── MLX model loader ─────────────────────────────────────────────────────────

# mlx-community/sam3-image only ships weights. The Python source lives at:
#   https://github.com/Deekshith-Dade/mlx_sam3
# Clone it alongside the PyTorch sam3/:  git clone https://github.com/Deekshith-Dade/mlx_sam3.git
_MLX_SAM3_SRC = Path("mlx_sam3")   # cloned repo root, relative to CWD


def _mlx_sam3_src_available() -> bool:
    """True when the mlx_sam3 GitHub source is cloned at mlx_sam3/."""
    return (_MLX_SAM3_SRC / "sam3").is_dir()


def _load_sam3_mlx_image() -> tuple[Any, Any] | None:
    """Load SAM3-MLX image model + processor. Returns (model, processor) or None.

    Requires:
      1. mlx package installed (pip install mlx)
      2. mlx_sam3 source cloned: git clone https://github.com/Deekshith-Dade/mlx_sam3.git
      3. sam3-mlx weights downloaded from the Models page

    The mlx_sam3 repo installs as the `sam3` package (same name as PyTorch SAM3).
    We temporarily prepend mlx_sam3/ to sys.path so it shadows the editable
    PyTorch install, run inference, then restore the PyTorch modules.
    """
    if "sam3_mlx_image" in _MODEL_CACHE:
        return _MODEL_CACHE["sam3_mlx_image"]

    model_dir = _BASE_MODELS / "sam3-mlx"
    if not (model_dir.exists() and (model_dir / ".complete").exists()):
        return None

    try:
        import mlx.core  # noqa: F401
    except ImportError:
        logger.error("SAM3-MLX: mlx not installed — run: pip install mlx")
        return None

    if not _mlx_sam3_src_available():
        logger.error(
            "SAM3-MLX: source not found — run: "
            "git clone https://github.com/Deekshith-Dade/mlx_sam3.git"
        )
        return None

    import sys

    mlx_src = str(_MLX_SAM3_SRC.resolve())

    def _swap_in() -> None:
        """Evict PyTorch sam3 and prepend mlx_sam3 to sys.path."""
        for k in [k for k in list(sys.modules) if k == "sam3" or k.startswith("sam3.")]:
            del sys.modules[k]
        if mlx_src not in sys.path:
            sys.path.insert(0, mlx_src)

    def _swap_out() -> None:
        """Remove mlx sam3 modules and mlx_src from sys.path."""
        for k in [k for k in list(sys.modules) if k == "sam3" or k.startswith("sam3.")]:
            del sys.modules[k]
        if mlx_src in sys.path:
            sys.path.remove(mlx_src)

    ckpt = _find_checkpoint(model_dir)

    _swap_in()
    try:
        from sam3.model_builder import build_sam3_image_model  # mlx version
        from sam3.model.sam3_image_processor import Sam3Processor

        # BPE vocab: mlx_sam3 stores it at <repo_root>/assets/ (one level above sam3/)
        bpe: Path | None = None
        try:
            import sam3.model_builder as _mb
            # parent = mlx_sam3/sam3/, parent.parent = mlx_sam3/
            _pkg_bpe = Path(_mb.__file__).parent.parent / "assets" / "bpe_simple_vocab_16e6.txt.gz"
            if _pkg_bpe.exists():
                bpe = _pkg_bpe
        except Exception:
            pass

        # MLX build_sam3_image_model: checkpoint_path is a single safetensors file path.
        # No load_from_HF param — omit it; local_weights_dir triggers HF download if needed.
        model = build_sam3_image_model(
            checkpoint_path=str(ckpt) if ckpt else None,
            bpe_path=str(bpe) if bpe else None,
            local_weights_dir=str(model_dir) if ckpt is None else None,
        )
        processor = Sam3Processor(model)
        _MODEL_CACHE["sam3_mlx_image"] = (model, processor)
        logger.info("SAM3-MLX image model loaded from %s", ckpt or "HF")
        return (model, processor)
    except Exception as exc:
        logger.error("SAM3-MLX model load failed: %s", exc)
        return None
    finally:
        _swap_out()


# ── Model availability helpers ───────────────────────────────────────────────

def get_sam3_runtime_status() -> dict[str, Any]:
    """Return readiness for both PyTorch SAM3 and SAM3-MLX backends."""
    from cv_agent.local_model_manager import is_model_downloaded
    import importlib.util as _ilu

    has_sam3_pkg = _ilu.find_spec("sam3") is not None
    has_sam3_model = is_model_downloaded("sam3")
    sam3_ready = has_sam3_pkg and has_sam3_model

    has_mlx_pkg = _ilu.find_spec("mlx") is not None
    has_mlx_src = _mlx_sam3_src_available()
    has_sam3_mlx_model = is_model_downloaded("sam3-mlx")
    sam3_mlx_ready = has_mlx_pkg and has_mlx_src and has_sam3_mlx_model

    models: list[dict[str, Any]] = []
    if has_sam3_mlx_model:
        needs = []
        if not has_mlx_pkg:
            needs.append("mlx package (pip install mlx)")
        if not has_mlx_src:
            needs.append("mlx_sam3 source (git clone https://github.com/Deekshith-Dade/mlx_sam3.git)")
        models.append({
            "id": "sam3-mlx",
            "label": "SAM 3 MLX (Apple Silicon)",
            "ready": sam3_mlx_ready,
            "needs": needs,
        })

    if has_sam3_model:
        models.append({
            "id": "sam3",
            "label": "SAM 3 (PyTorch · CPU)",
            "ready": sam3_ready,
            "needs": [] if sam3_ready else ["sam3 package (pip install -e sam3/)"],
        })

    return {
        "has_sam3_pkg": has_sam3_pkg,
        "has_sam3_model": has_sam3_model,
        "sam3_ready": sam3_ready,
        "has_mlx_pkg": has_mlx_pkg,
        "has_mlx_src": has_mlx_src,
        "has_sam3_mlx_model": has_sam3_mlx_model,
        "sam3_mlx_ready": sam3_mlx_ready,
        "has_any_model": has_sam3_model or has_sam3_mlx_model,
        "ready": sam3_ready or sam3_mlx_ready,
        "available_models": models,
    }

def available_segment_models() -> list[dict]:
    """Return list of available segmentation models with their status."""
    return get_sam3_runtime_status()["available_models"]


# ── Mask visualisation ──────────────────────────────────────────────────────

_MASK_COLORS = [
    (255, 50, 50), (50, 220, 50), (50, 50, 255),
    (255, 220, 0), (220, 50, 220), (0, 220, 220),
    (255, 140, 0), (140, 0, 255),
]


def _to_numpy(mask) -> "np.ndarray":
    """Convert a mask (torch tensor, mlx array, or ndarray) to numpy."""
    import numpy as np
    if hasattr(mask, "cpu"):          # torch tensor
        return mask.cpu().numpy()
    if hasattr(mask, "__array__"):    # mlx array (supports numpy protocol)
        return np.asarray(mask)
    return np.asarray(mask)


def _overlay_masks(
    image,
    masks,
    alpha: float = 0.45,
    scores: list[float] | None = None,
    boxes: list | None = None,
    label: str = "",
):
    """Return a PIL RGBA image with coloured mask overlays, bounding boxes, and labels."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    arr = np.array(image.convert("RGBA"), dtype=np.float32)
    for i, mask in enumerate(masks):
        if mask is None:
            continue
        m = _to_numpy(mask)
        if m.ndim == 3:
            m = m[0]
        if not m.any():
            continue
        r, g, b = _MASK_COLORS[i % len(_MASK_COLORS)]
        color = np.array([r, g, b, int(255 * alpha)], dtype=np.float32)
        arr[m.astype(bool)] = arr[m.astype(bool)] * (1 - alpha) + color * alpha

    result = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    n_boxes = len(boxes) if boxes else 0
    n_scores = len(scores) if scores else 0
    if n_boxes > 0 or n_scores > 0:
        draw = ImageDraw.Draw(result)
        font_size = max(14, image.height // 35)
        font = None
        for _fp in (
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ):
            try:
                font = ImageFont.truetype(_fp, size=font_size)
                break
            except Exception:
                continue
        if font is None:
            try:
                font = ImageFont.load_default(size=font_size)
            except TypeError:
                font = ImageFont.load_default()

        n = max(len(masks), n_boxes)
        for i in range(n):
            clr = _MASK_COLORS[i % len(_MASK_COLORS)]
            box = boxes[i] if boxes and i < n_boxes else None
            score = scores[i] if scores and i < n_scores else None

            if box is not None:
                x1, y1, x2, y2 = [float(v) for v in box]
                draw.rectangle([x1, y1, x2, y2], outline=clr + (255,), width=3)

                text_parts = []
                if label:
                    text_parts.append(label)
                if score is not None:
                    text_parts.append(f"{score:.2f}")
                text = " ".join(text_parts)
                if text:
                    tx, ty = x1 + 4, y1 + 4
                    tb = draw.textbbox((tx, ty), text, font=font)
                    pad = 3
                    draw.rectangle(
                        [tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad],
                        fill=clr + (210,),
                    )
                    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    return result


def _save_overlay(image_path: str, overlay_image) -> str:
    """Save overlay PNG to output/segments/ and return the path string."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(image_path).stem
    ts = int(time.time())
    out = _OUTPUT_DIR / f"{stem}_seg_{ts}.png"
    overlay_image.save(out)
    return str(out)


def _extract_masks_scores_boxes(output: dict) -> tuple[list, list, list]:
    """Extract masks/scores/boxes from processor output.

    Handles both PyTorch tensors and MLX arrays.
    MLX returns batched arrays (e.g. scores shape [N], masks shape [N,1,H,W]);
    we normalise everything to plain Python lists / numpy arrays.
    """
    import numpy as np

    def _to_np(x):
        if x is None:
            return np.array([])
        if hasattr(x, "cpu"):          # torch tensor
            return x.cpu().numpy()
        if hasattr(x, "__array__"):    # mlx array
            return np.asarray(x)
        return np.asarray(x)

    raw_masks  = output.get("masks")
    raw_scores = output.get("scores")
    raw_boxes  = output.get("boxes")

    # Scores → flat list of Python floats
    scores: list[float] = []
    if raw_scores is not None:
        arr = _to_np(raw_scores).flatten()
        scores = [float(v) for v in arr]

    # Masks → list of 2-D/3-D numpy arrays (one per detection)
    masks: list = []
    if raw_masks is not None:
        m = _to_np(raw_masks)       # shape [N, 1, H, W] or [N, H, W]
        for i in range(m.shape[0]):
            masks.append(m[i])

    # Boxes → list of [x1,y1,x2,y2] lists
    boxes: list = []
    if raw_boxes is not None:
        b = _to_np(raw_boxes)       # shape [N, 4]
        for i in range(b.shape[0]):
            boxes.append(b[i].tolist())

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
        import torch
        image = Image.open(image_path).convert("RGB")
        with torch.device(processor.device):
            state = processor.set_image(image)
            output = processor.set_text_prompt(prompt=prompt, state=state)
    except Exception as exc:
        return json.dumps({"error": f"SAM3 inference failed: {exc}"})

    masks, scores, boxes = _extract_masks_scores_boxes(output)
    overlay = _overlay_masks(image, masks, scores=scores, boxes=boxes, label=prompt)
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
        import torch
        image = Image.open(image_path).convert("RGB")
        with torch.device(processor.device):
            state = processor.set_image(image)
            output = processor.add_geometric_prompt(box=box, label=True, state=state)
    except Exception as exc:
        return json.dumps({"error": f"SAM3 inference failed: {exc}"})

    masks, scores, boxes_out = _extract_masks_scores_boxes(output)
    draw_boxes = boxes_out if boxes_out else [box]
    overlay = _overlay_masks(image, masks, scores=scores, boxes=draw_boxes)
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
