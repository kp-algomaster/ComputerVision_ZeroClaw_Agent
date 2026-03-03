"""MLX-accelerated vision model tools for Apple Silicon Macs."""

from __future__ import annotations

import logging
from pathlib import Path

from zeroclaw_tools import tool

logger = logging.getLogger(__name__)


def _check_mlx_available() -> bool:
    """Check if MLX and mlx-vlm are installed."""
    try:
        import mlx  # noqa: F401
        return True
    except ImportError:
        return False


@tool
def mlx_analyze_image(
    image_path: str,
    prompt: str = "Describe this image in detail.",
    model: str = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit",
    max_tokens: int = 2048,
) -> str:
    """Analyze an image using MLX-accelerated vision model on Apple Silicon.

    This provides faster inference on M-series Macs by using the Metal GPU directly.

    Args:
        image_path: Path to the local image file.
        prompt: Question or instruction about the image.
        model: MLX model identifier (HuggingFace repo).
        max_tokens: Maximum tokens to generate.

    Returns:
        Analysis text from the vision model.
    """
    if not _check_mlx_available():
        return (
            "MLX is not available. Install with: pip install 'cv-zero-claw-agent[mlx]'\n"
            "Requires macOS with Apple Silicon (M1/M2/M3/M4)."
        )

    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        return f"Error: Image not found at {path}"

    try:
        from mlx_vlm import load as mlx_load, generate as mlx_generate
        from mlx_vlm.utils import load_image

        model_obj, processor = mlx_load(model)
        image = load_image(str(path))

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        formatted_prompt = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        output = mlx_generate(
            model_obj,
            processor,
            formatted_prompt,
            image=image,
            max_tokens=max_tokens,
            verbose=False,
        )
        return output

    except Exception as e:
        logger.exception("MLX vision analysis failed")
        return f"MLX analysis error: {e}"
