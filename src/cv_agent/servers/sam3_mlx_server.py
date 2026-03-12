"""Dedicated SAM3-MLX segmentation server — keeps model loaded in MLX memory.

Run standalone:  python -m cv_agent.servers.sam3_mlx_server
Managed by server_manager.py from the UI → Model Management → Server Management.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="SAM3-MLX Segmentation Server")

_BASE_MODELS = Path("output/.models")
_OUTPUT_DIR = Path("output/segments")
_MLX_SAM3_SRC = Path("mlx_sam3")

# Persistent model cache — loaded once at startup, stays in memory
_model = None
_processor = None


def _load_model():
    """Load SAM3-MLX model + processor into memory. Called once at startup."""
    global _model, _processor

    model_dir = _BASE_MODELS / "sam3-mlx"
    if not (model_dir.exists() and (model_dir / ".complete").exists()):
        logger.error("SAM3-MLX weights not found at %s", model_dir)
        return False

    mlx_src = str(_MLX_SAM3_SRC.resolve())

    # Evict any PyTorch sam3 modules and inject mlx_sam3
    for k in [k for k in list(sys.modules) if k == "sam3" or k.startswith("sam3.")]:
        del sys.modules[k]
    if mlx_src not in sys.path:
        sys.path.insert(0, mlx_src)

    from cv_agent.tools.segment_anything import _find_checkpoint

    ckpt = _find_checkpoint(model_dir)

    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    bpe: Path | None = None
    try:
        import sam3.model_builder as _mb
        _pkg_bpe = Path(_mb.__file__).parent.parent / "assets" / "bpe_simple_vocab_16e6.txt.gz"
        if _pkg_bpe.exists():
            bpe = _pkg_bpe
    except Exception:
        pass

    t0 = time.perf_counter()
    _model = build_sam3_image_model(
        checkpoint_path=str(ckpt) if ckpt else None,
        bpe_path=str(bpe) if bpe else None,
        local_weights_dir=str(model_dir) if ckpt is None else None,
    )
    _processor = Sam3Processor(_model)
    elapsed = time.perf_counter() - t0
    logger.info("SAM3-MLX model loaded in %.1fs from %s", elapsed, ckpt or "HF")

    # Keep mlx modules alive, just remove from sys.path
    if mlx_src in sys.path:
        sys.path.remove(mlx_src)
    return True


@app.on_event("startup")
async def startup():
    ok = _load_model()
    if not ok:
        logger.error("Failed to load SAM3-MLX model — server will return errors")


@app.get("/health")
async def health():
    ready = _model is not None and _processor is not None
    return JSONResponse({
        "status": "ok" if ready else "model_not_loaded",
        "model": "sam3-mlx",
        "ready": ready,
    })


@app.post("/segment")
async def segment(body: dict):
    """Run segmentation. Body: {image_path, mode, prompt?, box?}"""
    import asyncio

    if _model is None or _processor is None:
        return JSONResponse({"error": "SAM3-MLX model not loaded"}, status_code=503)

    image_path = body.get("image_path", "")
    mode = body.get("mode", "text")

    if not image_path:
        return JSONResponse({"error": "image_path is required"}, status_code=400)
    if not Path(image_path).exists():
        return JSONResponse({"error": f"Image not found: {image_path}"}, status_code=404)

    def _run():
        from PIL import Image
        from cv_agent.tools.segment_anything import (
            _overlay_masks, _save_overlay, _extract_masks_scores_boxes,
        )

        t0 = time.perf_counter()
        image = Image.open(image_path).convert("RGB")
        state = _processor.set_image(image)

        if mode == "text":
            prompt = body.get("prompt", "").strip()
            if not prompt:
                return {"error": "prompt is required for text mode"}
            output = _processor.set_text_prompt(prompt=prompt, state=state)
        elif mode == "box":
            import json as _json
            box_raw = body.get("box")
            if not box_raw:
                return {"error": "box is required for box mode"}
            b = box_raw if isinstance(box_raw, dict) else _json.loads(box_raw)
            output = _processor.add_geometric_prompt(
                box=[b["x1"], b["y1"], b["x2"], b["y2"]], label=True, state=state
            )
        else:
            return {"error": f"Unknown mode: {mode}"}

        masks, scores, boxes_out = _extract_masks_scores_boxes(output)
        label = body.get("prompt", "") if mode == "text" else ""
        overlay = _overlay_masks(image, masks, scores=scores, boxes=boxes_out, label=label)
        out_file = _save_overlay(image_path, overlay)
        elapsed = time.perf_counter() - t0

        return {
            "output_path": out_file,
            "mask_count": len(masks),
            "scores": [round(s, 4) for s in scores],
            "boxes": [b.tolist() if hasattr(b, "tolist") else b for b in boxes_out],
            "model": "SAM3-MLX",
            "inference_time_s": round(elapsed, 2),
        }

    result = await asyncio.to_thread(_run)
    status = 200 if "error" not in result else 400
    return JSONResponse(result, status_code=status)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("SAM3_MLX_PORT", "7863"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
