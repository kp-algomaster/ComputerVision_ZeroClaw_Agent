"""Text-to-diagram tool powered by Paperbanana."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import datetime
from pathlib import Path

from zeroclaw_tools import tool

from cv_agent.config import load_config

logger = logging.getLogger(__name__)


def _normalize_diagram_type(raw_value: str):
    """Resolve user-provided diagram type to a Paperbanana DiagramType enum value."""
    from paperbanana import DiagramType

    value = (raw_value or "").strip().lower()
    if not value:
        return DiagramType.METHODOLOGY

    aliases = {
        "method": DiagramType.METHODOLOGY,
        "methodology": DiagramType.METHODOLOGY,
        "architecture": DiagramType.METHODOLOGY,
        "statistical_plot": DiagramType.STATISTICAL_PLOT,
        "plot": DiagramType.STATISTICAL_PLOT,
        "chart": DiagramType.STATISTICAL_PLOT,
    }
    return aliases.get(value, DiagramType.METHODOLOGY)


@tool
def text_to_diagram(
    source_text: str,
    caption: str,
    diagram_type: str = "",
    iterations: int | None = None,
    provider: str = "",
    vlm_provider: str = "",
    image_provider: str = "",
    vlm_model: str = "",
    image_model: str = "",
    output_format: str = "png",
) -> str:
    """Generate a diagram image from pasted text using Paperbanana.

    Args:
        source_text: The context text to convert into a diagram.
        caption: Communicative intent/caption for the diagram.
        diagram_type: Diagram style: methodology or statistical_plot.
        iterations: Optional refinement iteration count. Defaults to config value (2).
        provider: Provider profile: ollama | gemini | openai | openrouter.
        vlm_provider: Optional explicit VLM provider override.
        image_provider: Optional explicit image provider override.
        vlm_model: Optional provider-specific VLM model override.
        image_model: Optional provider-specific image model override.
        output_format: Final output format: png or svg.

    Returns:
        Generation summary including output image path.
    """
    cfg = load_config()
    t2d = cfg.text_to_diagram

    if not t2d.enabled:
        return "Text-to-diagram is disabled in config under text_to_diagram.enabled."

    if not source_text.strip():
        return "source_text is empty. Paste or write text to generate a diagram."
    if not caption.strip():
        return "caption is empty. Provide a short intent/caption for the diagram."

    requested_iterations = iterations if iterations is not None else t2d.default_iterations
    requested_iterations = max(1, int(requested_iterations))
    requested_output_format = (output_format or "png").strip().lower()
    if requested_output_format not in {"png", "svg"}:
        requested_output_format = "png"

    profile_name = (provider or t2d.vlm_provider or "ollama").strip().lower()
    if profile_name not in {"ollama", "gemini", "openai", "openrouter"}:
        profile_name = "ollama"

    profile_map = {
        "ollama": ("ollama", "matplotlib"),
        "gemini": ("gemini", "google_imagen"),
        "openai": ("openai", "openai_imagen"),
        "openrouter": ("openrouter", "openrouter_imagen"),
    }
    selected_vlm_provider, selected_image_provider = profile_map[profile_name]

    if vlm_provider.strip().lower() in {"ollama", "gemini", "openai", "openrouter"}:
        selected_vlm_provider = vlm_provider.strip().lower()

    if image_provider.strip().lower() in {
        "matplotlib",
        "google_imagen",
        "openai_imagen",
        "openrouter_imagen",
        "stability",
    }:
        selected_image_provider = image_provider.strip().lower()

    if selected_vlm_provider == "ollama":
        selected_vlm_model = (vlm_model or t2d.ollama_vlm_model).strip()
    elif selected_vlm_provider == "gemini":
        selected_vlm_model = (vlm_model or os.environ.get("PAPERBANANA_GEMINI_VLM_MODEL") or "gemini-2.0-flash").strip()
    elif selected_vlm_provider == "openai":
        selected_vlm_model = (vlm_model or os.environ.get("PAPERBANANA_OPENAI_VLM_MODEL") or "gpt-4o").strip()
    else:
        selected_vlm_model = (vlm_model or os.environ.get("PAPERBANANA_OPENROUTER_VLM_MODEL") or "openai/gpt-4o-mini").strip()

    effective_image_provider = selected_image_provider
    if selected_image_provider == "matplotlib":
        selected_image_model = "matplotlib"
    elif selected_image_provider == "google_imagen":
        selected_image_model = (image_model or os.environ.get("PAPERBANANA_GEMINI_IMAGE_MODEL") or "gemini-3-pro-image-preview").strip()
    elif selected_image_provider == "openai_imagen":
        selected_image_model = (image_model or os.environ.get("PAPERBANANA_OPENAI_IMAGE_MODEL") or "gpt-image-1").strip()
    elif selected_image_provider == "openrouter_imagen":
        selected_image_model = (image_model or os.environ.get("PAPERBANANA_OPENROUTER_IMAGE_MODEL") or "openai/gpt-image-1").strip()
    else:
        # Stability is routed via OpenRouter image provider.
        effective_image_provider = "openrouter_imagen"
        selected_image_model = (
            image_model
            or os.environ.get("PAPERBANANA_STABILITY_IMAGE_MODEL")
            or "stabilityai/stable-diffusion-3.5-large"
        ).strip()

    model_note = ""
    if effective_image_provider == "google_imagen" and "flash-image-preview" in selected_image_model:
        selected_image_model = "gemini-3-pro-image-preview"
        model_note = (
            "Configured Gemini image model is not supported for generateContent; "
            "using 'gemini-3-pro-image-preview'."
        )

    if selected_vlm_provider == "ollama":
        from cv_agent.tools.hardware_probe import list_ollama_models

        ollama_host = t2d.ollama_base_url.removesuffix("/v1")
        pulled_models = list_ollama_models(ollama_host)
        if pulled_models and selected_vlm_model not in pulled_models:
            preferred_model = cfg.vision.ollama.default_model
            if preferred_model in pulled_models:
                selected_vlm_model = preferred_model
            else:
                selected_vlm_model = next(
                    (m for m in pulled_models if any(k in m.lower() for k in ("vl", "llava", "vision"))),
                    pulled_models[0],
                )
            model_note = (
                f"Configured model '{t2d.ollama_vlm_model}' was not pulled; "
                f"using '{selected_vlm_model}' instead."
            )

    output_dir = Path(t2d.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    async def _run() -> str:
        from paperbanana import GenerationInput, PaperBananaPipeline
        from paperbanana.core.config import Settings

        settings = Settings(
            vlm_provider=selected_vlm_provider,
            image_provider=effective_image_provider,
            vlm_model=selected_vlm_model,
            image_model=selected_image_model,
            ollama_base_url=t2d.ollama_base_url,
            ollama_vlm_model=selected_vlm_model,
            ollama_code_model=t2d.ollama_code_model,
            google_api_key=os.environ.get("GOOGLE_API_KEY"),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_vlm_model=selected_vlm_model,
            openai_image_model=selected_image_model,
            output_dir=str(output_dir),
            output_format="png",
            refinement_iterations=requested_iterations,
            max_iterations=requested_iterations,
        )

        resolved_type = _normalize_diagram_type(diagram_type or t2d.default_diagram_type)

        provider_note = ""
        try:
            pipeline = PaperBananaPipeline(settings=settings)
        except Exception as exc:
            # Upstream Paperbanana may not expose a provider named 'ollama'.
            # Fall back to OpenAI-compatible mode targeting Ollama's /v1 endpoint.
            if "Unknown VLM provider: ollama" not in str(exc):
                raise
            if selected_vlm_provider == "ollama" and effective_image_provider == "openai_imagen":
                raise RuntimeError(
                    "This Paperbanana build lacks native ollama provider support, and openai_imagen "
                    "cannot be used with Ollama fallback mode. Choose google_imagen, openrouter_imagen, "
                    "or matplotlib for image generation."
                )
            settings = Settings(
                vlm_provider="openai",
                image_provider=effective_image_provider,
                vlm_model=selected_vlm_model,
                image_model=selected_image_model,
                openai_api_key=(os.environ.get("OPENAI_API_KEY") or "ollama-local"),
                openai_base_url=t2d.ollama_base_url,
                openai_vlm_model=selected_vlm_model,
                google_api_key=os.environ.get("GOOGLE_API_KEY"),
                openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
                ollama_code_model=t2d.ollama_code_model,
                output_dir=str(output_dir),
                output_format="png",
                refinement_iterations=requested_iterations,
                max_iterations=requested_iterations,
            )
            provider_note = (
                "Provider fallback: used openai VLM provider with Ollama-compatible base URL."
            )
            pipeline = PaperBananaPipeline(settings=settings)

        result = await pipeline.generate(
            GenerationInput(
                source_context=source_text,
                communicative_intent=caption,
                diagram_type=resolved_type,
            )
        )

        image_path = Path(result.image_path).expanduser().resolve()
        if requested_output_format == "svg":
            mime = {
                ".png": "image/png",
                ".jpeg": "image/jpeg",
                ".jpg": "image/jpeg",
                ".webp": "image/webp",
            }.get(image_path.suffix.lower(), "image/png")
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            svg_path = image_path.with_suffix(".svg")
            svg_path.write_text(
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                "<svg xmlns=\"http://www.w3.org/2000/svg\" version=\"1.1\" "
                "width=\"100%\" height=\"100%\" viewBox=\"0 0 2048 1536\">\n"
                f"  <image href=\"data:{mime};base64,{encoded}\" x=\"0\" y=\"0\" "
                "width=\"2048\" height=\"1536\" preserveAspectRatio=\"xMidYMid meet\"/>\n"
                "</svg>\n"
            )
            image_path = svg_path

        rel_path = image_path
        try:
            rel_path = image_path.relative_to(Path.cwd())
        except ValueError:
            pass

        return (
            f"Diagram generated successfully.\\n"
            f"Path: {rel_path}\\n"
            f"Description: {result.description}\\n"
            f"Iterations: {result.iterations}\\n"
            f"Type: {resolved_type.value}\\n"
            f"Provider profile: {profile_name}\n"
            f"VLM provider/model: {selected_vlm_provider} / {selected_vlm_model}\n"
            f"Image provider/model: {selected_image_provider} / {selected_image_model}\n"
            f"Output format: {requested_output_format}\n"
            f"Provider note: {provider_note or 'configured provider used'}\\n"
            f"Model note: {model_note or 'configured model used'}\\n"
            f"Timestamp: {datetime.now().isoformat(timespec='seconds')}"
        )

    try:
        return asyncio.run(_run())
    except ImportError as exc:
        return (
            "Paperbanana is not available in this environment. "
            "Install/activate it in this venv and retry. "
            f"Import error: {exc}"
        )
    except Exception as exc:
        logger.exception("text_to_diagram failed")
        return f"Failed to generate diagram: {exc}"
