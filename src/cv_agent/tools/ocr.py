"""PaddleOCR tool — multi-language text, table, and layout extraction.

PaddleOCR (Apache 2.0) auto-downloads its models on first use (~0.5 GB).
Supports 80+ languages via the lang= parameter.

Install: pip install paddleocr paddlepaddle
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from zeroclaw_tools import tool

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path("output/ocr")

# Module-level cache — avoid re-initialising PaddleOCR (slow) on every call
_OCR_CACHE: dict[str, Any] = {}


def _get_ocr(lang: str = "en") -> Any:
    """Return a cached PaddleOCR instance for the given language."""
    if lang in _OCR_CACHE:
        return _OCR_CACHE[lang]
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return None
    # PaddleOCR 3.x: removed use_angle_cls and show_log; skip connectivity check
    import os
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    ocr = PaddleOCR(lang=lang)
    _OCR_CACHE[lang] = ocr
    return ocr


def _flatten_result(results: list) -> list[dict]:
    """Convert PaddleOCR 3.x OCRResult list to flat {text, confidence, box, polygon} dicts."""
    out = []
    for page in results:
        if page is None:
            continue
        texts = page.get("rec_texts", [])
        scores = page.get("rec_scores", [])
        polys = page.get("dt_polys", [])
        for text, conf, poly in zip(texts, scores, polys):
            pts = poly.tolist() if hasattr(poly, "tolist") else poly
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            out.append({
                "text": text,
                "confidence": round(float(conf), 4),
                "box": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))],
                "polygon": [[round(p[0]), round(p[1])] for p in pts],
            })
    return out


def _render_overlay(image_path: str, detections: list[dict]) -> str:
    """Draw bounding boxes + text labels on the image and save to output/ocr/."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    font_size = max(14, img.height // 45)
    font = None
    for fp in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            font = ImageFont.truetype(fp, size=font_size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()

    clr = (50, 200, 255)
    for d in detections:
        pts = d.get("polygon")
        if pts and len(pts) == 4:
            flat = [coord for p in pts for coord in p]
            draw.polygon(flat, outline=clr + (255,) if len(clr) == 3 else clr, width=2)
        x1, y1, x2, _ = d["box"]
        text = f"{d['text']} ({d['confidence']:.2f})"
        tb = draw.textbbox((x1, y1 - 2), text, font=font, anchor="lb")
        pad = 2
        draw.rectangle([tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad], fill=(50, 200, 255, 180))
        draw.text((x1, y1 - 2), text, fill=(0, 0, 0, 255), font=font, anchor="lb")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(image_path).stem
    out = _OUTPUT_DIR / f"{stem}_ocr_{int(time.time())}.png"
    img.save(out)
    return str(out)


@tool
def run_ocr(
    image_path: str,
    lang: str = "en",
    render_overlay: bool = True,
) -> str:
    """Extract text from an image using PaddleOCR (multi-language).

    Detects and recognises text in 80+ languages. Models auto-download on first use.

    Args:
        image_path: Path to the input image (JPEG, PNG, PDF page, etc.).
        lang: Language code — 'en' (English), 'ch' (Chinese), 'fr', 'de', 'es',
              'ja', 'ko', 'ar', 'ru', and 75+ more. Default: 'en'.
        render_overlay: If True, save an annotated PNG with boxes and labels.

    Returns:
        JSON with full_text (plain string), detections (list of box/text/confidence),
        and overlay_path if render_overlay is True.
    """
    if not Path(image_path).exists():
        return json.dumps({"error": f"File not found: {image_path}"})

    ocr = _get_ocr(lang)
    if ocr is None:
        return json.dumps({
            "error": "PaddleOCR not installed. Run: pip install paddleocr paddlepaddle"
        })

    try:
        result = ocr.ocr(image_path)
    except Exception as exc:
        return json.dumps({"error": f"OCR failed: {exc}"})

    detections = _flatten_result(result)
    full_text = "\n".join(d["text"] for d in detections)

    overlay_path = None
    if render_overlay and detections:
        try:
            overlay_path = _render_overlay(image_path, detections)
        except Exception as exc:
            logger.warning("OCR overlay render failed: %s", exc)

    return json.dumps({
        "full_text": full_text,
        "line_count": len(detections),
        "detections": detections,
        "overlay_path": overlay_path,
        "lang": lang,
    })
