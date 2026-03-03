"""Ollama vision model tools for image analysis via Qwen2.5-VL, LLaVA, etc."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx
from zeroclaw_tools import tool

from cv_agent.config import load_config

logger = logging.getLogger(__name__)


def _encode_image(image_path: str) -> str:
    """Read and base64-encode a local image file."""
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _ollama_chat_vision(
    image_b64: str,
    prompt: str,
    model: str | None = None,
    host: str | None = None,
) -> str:
    """Send a vision request to Ollama's chat API."""
    cfg = load_config()
    model = model or cfg.vision.ollama.default_model
    host = (host or cfg.vision.ollama.host).rstrip("/")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "stream": False,
        "options": {"num_predict": cfg.vision.ollama.max_tokens},
    }

    with httpx.Client(timeout=cfg.vision.ollama.timeout) as client:
        resp = client.post(f"{host}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


@tool
def analyze_image(image_path: str, prompt: str = "Analyze this image in detail.") -> str:
    """Analyze an image using the Ollama vision model (Qwen2.5-VL).

    Args:
        image_path: Path to the local image file.
        prompt: Analysis prompt/question about the image.

    Returns:
        Detailed analysis of the image.
    """
    image_b64 = _encode_image(image_path)
    return _ollama_chat_vision(image_b64, prompt)


@tool
def describe_image(image_path: str) -> str:
    """Generate a detailed description of an image using the vision model.

    Args:
        image_path: Path to the local image file.

    Returns:
        Comprehensive description of the image contents.
    """
    image_b64 = _encode_image(image_path)
    prompt = (
        "Provide a comprehensive description of this image. Include:\n"
        "1. Main subjects and objects\n"
        "2. Scene composition and layout\n"
        "3. Colors, lighting, and visual style\n"
        "4. Any text visible in the image\n"
        "5. Technical observations (if it's a diagram, chart, or technical figure)"
    )
    return _ollama_chat_vision(image_b64, prompt)


@tool
def compare_images(image_path_1: str, image_path_2: str, aspect: str = "general") -> str:
    """Compare two images and describe differences and similarities.

    Args:
        image_path_1: Path to the first image.
        image_path_2: Path to the second image.
        aspect: What aspect to compare (general, quality, content, style).

    Returns:
        Comparison analysis of the two images.
    """
    img1_b64 = _encode_image(image_path_1)
    img2_b64 = _encode_image(image_path_2)

    cfg = load_config()
    model = cfg.vision.ollama.default_model
    host = cfg.vision.ollama.host.rstrip("/")

    prompt = (
        f"Compare these two images focusing on '{aspect}'. Describe:\n"
        "1. Key similarities\n"
        "2. Key differences\n"
        "3. Quality comparison\n"
        "4. Overall assessment"
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [img1_b64, img2_b64],
            }
        ],
        "stream": False,
    }

    with httpx.Client(timeout=cfg.vision.ollama.timeout) as client:
        resp = client.post(f"{host}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]
