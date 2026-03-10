"""Web UI server — FastAPI backend with chat and content viewer."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from cv_agent.http_client import httpx
import markdown
from fastapi import FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv as _load_dotenv_startup
from cv_agent.config import AgentConfig, load_config

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_NON_CHAT_MODEL_MARKERS = (
    "embed",
    "embedding",
    "rerank",
    "whisper",
    "transcribe",
    "speech",
    "tts",
    "clip",
)

# Re-apply .env with override so vars added after initial startup are picked up
_load_dotenv_startup(_PROJECT_ROOT / ".env", override=True)


def _is_chat_model_compatible(model_name: str, capabilities: list[str] | None) -> bool:
    """Return True when an Ollama model looks suitable for text chat."""
    normalized_name = model_name.strip().lower()
    if any(marker in normalized_name for marker in _NON_CHAT_MODEL_MARKERS):
        return False

    normalized_caps = {str(cap).strip().lower() for cap in (capabilities or []) if str(cap).strip()}
    if not normalized_caps:
        return True
    return "completion" in normalized_caps or "chat" in normalized_caps


def _select_default_chat_model(
    available_models: list[str],
    configured_model: str,
    preferred_model: str | None = None,
) -> str:
    """Pick the best available chat model, preferring an explicit user choice."""
    if preferred_model and preferred_model in available_models:
        return preferred_model
    if configured_model in available_models:
        return configured_model
    return available_models[0] if available_models else ""


def _persist_env_updates(env_path: Path, updates: dict[str, str]) -> None:
    """Write environment updates to `.env`, creating the file when needed."""
    if not updates:
        return

    lines = env_path.read_text().splitlines() if env_path.exists() else []
    written: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                written.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in written:
            new_lines.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(new_lines) + "\n")


def _persist_huggingface_token(token: str) -> bool:
    """Persist the active HF token for clients that read Hub auth state directly."""
    cleaned = token.strip()
    if not cleaned:
        return False

    os.environ["HF_TOKEN"] = cleaned
    os.environ["HUGGING_FACE_HUB_TOKEN"] = cleaned

    try:
        from huggingface_hub import constants as hf_constants
    except ImportError:
        return False

    try:
        token_path = Path(hf_constants.HF_TOKEN_PATH)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(cleaned)

        # Keep a named token entry too so `hf auth list` can surface it.
        try:
            from huggingface_hub.utils import _auth as hf_auth

            hf_auth._save_token(cleaned, "cv-agent")
        except Exception:
            logger.debug("Could not update stored HF token list", exc_info=True)

        return True
    except Exception:
        logger.warning("Could not persist HF token to huggingface_hub cache", exc_info=True)
        return False


def create_app(config: AgentConfig | None = None) -> FastAPI:
    """Create the FastAPI application."""
    if config is None:
        config = load_config()

    app = FastAPI(title="CV Zero Claw Agent", version="0.1.0")

    output_dir = _PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/output", StaticFiles(directory=output_dir), name="output")
    app.state.diagram_jobs = {}

    def _fetch_ollama_model_metadata(model_name: str) -> dict[str, Any]:
        host = config.vision.ollama.host.rstrip("/")
        try:
            resp = httpx.post(
                f"{host}/api/show",
                json={"name": model_name},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Could not inspect Ollama model '%s': %s", model_name, exc)
            return {}

    def _list_chat_compatible_models() -> list[dict[str, Any]]:
        from cv_agent.tools.hardware_probe import list_ollama_models

        compatible: list[dict[str, Any]] = []
        for model_name in list_ollama_models(config.vision.ollama.host):
            metadata = _fetch_ollama_model_metadata(model_name)
            details = metadata.get("details") or {}
            capabilities = [
                str(cap).strip().lower()
                for cap in (metadata.get("capabilities") or [])
                if str(cap).strip()
            ]
            if not _is_chat_model_compatible(model_name, capabilities):
                continue

            normalized_name = model_name.lower()
            compatible.append(
                {
                    "name": model_name,
                    "family": details.get("family") or "",
                    "parameter_size": details.get("parameter_size") or "",
                    "quantization": details.get("quantization_level") or "",
                    "capabilities": capabilities,
                    "supports_tools": "tools" in capabilities,
                    "supports_vision": "vision" in capabilities,
                    "supports_thinking": "thinking" in capabilities,
                    "warning": (
                        "Base model detected; it may be less instruction-tuned than chat/instruct variants."
                        if "-base" in normalized_name
                        else ""
                    ),
                }
            )

        compatible.sort(
            key=lambda item: (
                0 if item["name"] == config.llm.model else 1,
                0 if item["supports_tools"] else 1,
                0 if item["supports_vision"] else 1,
                0 if item["supports_thinking"] else 1,
                0 if not item["warning"] else 1,
                item["name"].lower(),
            )
        )
        return compatible

    def _add_diag_event(job: dict[str, Any], message: str, kind: str = "info") -> None:
        job["events"].append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "kind": kind,
                "message": message,
            }
        )

    def _project_relative_url(path: Path) -> str:
        rel = path.resolve().relative_to(_PROJECT_ROOT)
        return f"/{rel.as_posix()}"

    def _scan_diagram_job(job: dict[str, Any]) -> None:
        run_dir = job.get("run_dir")
        if not run_dir:
            return
        run_path = Path(run_dir)
        if not run_path.exists():
            return

        if not job.get("planning_seen") and (run_path / "planning.json").exists():
            job["planning_seen"] = True
            _add_diag_event(job, "Planning/styling phase completed.")

        for image_path in sorted(run_path.glob("diagram_iter_*.png")):
            m = re.search(r"diagram_iter_(\d+)\.png$", image_path.name)
            if not m:
                continue
            iter_num = int(m.group(1))
            if iter_num in job["seen_iterations"]:
                continue

            item: dict[str, Any] = {
                "iteration": iter_num,
                "image_url": _project_relative_url(image_path),
                "critique_summary": "",
                "needs_revision": None,
            }
            details_path = run_path / f"iter_{iter_num}" / "details.json"
            if details_path.exists():
                try:
                    details = json.loads(details_path.read_text())
                    critique = details.get("critique", {})
                    item["critique_summary"] = critique.get("summary", "")
                    item["needs_revision"] = critique.get("needs_revision")
                except Exception:
                    pass

            job["seen_iterations"].add(iter_num)
            job["iterations"].append(item)
            _add_diag_event(job, f"Iteration {iter_num} image generated.")

        final_output = run_path / "final_output.svg"
        if not final_output.exists():
            final_output = run_path / "final_output.png"
        if not final_output.exists():
            jpeg_output = run_path / "final_output.jpeg"
            webp_output = run_path / "final_output.webp"
            if jpeg_output.exists():
                final_output = jpeg_output
            elif webp_output.exists():
                final_output = webp_output
        if final_output.exists():
            job["final_image_url"] = _project_relative_url(final_output)

    def _embed_raster_as_svg(raster_path: Path, svg_path: Path) -> None:
        suffix = raster_path.suffix.lower()
        mime = {
            ".png": "image/png",
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
            ".webp": "image/webp",
        }.get(suffix, "image/png")
        encoded = base64.b64encode(raster_path.read_bytes()).decode("ascii")

        svg = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<svg xmlns=\"http://www.w3.org/2000/svg\" version=\"1.1\" "
            "width=\"100%\" height=\"100%\" viewBox=\"0 0 2048 1536\">\n"
            f"  <image href=\"data:{mime};base64,{encoded}\" x=\"0\" y=\"0\" "
            "width=\"2048\" height=\"1536\" preserveAspectRatio=\"xMidYMid meet\"/>\n"
            "</svg>\n"
        )
        svg_path.write_text(svg)

    # ── Serve the main UI ──────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index():
        ui_path = _PROJECT_ROOT / "src" / "cv_agent" / "ui" / "index.html"
        return HTMLResponse(ui_path.read_text())

    @app.get("/style.css")
    async def style():
        css_path = _PROJECT_ROOT / "src" / "cv_agent" / "ui" / "style.css"
        from fastapi.responses import Response
        return Response(content=css_path.read_text(), media_type="text/css")

    @app.get("/app.js")
    async def script():
        js_path = _PROJECT_ROOT / "src" / "cv_agent" / "ui" / "app.js"
        from fastapi.responses import Response
        return Response(content=js_path.read_text(), media_type="application/javascript")

    # ── WebSocket chat endpoint ────────────────────────────────────────────

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket):
        await websocket.accept()
        history: list[Any] = []

        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                user_text = msg.get("message", "")
                requested_model = str(msg.get("model", "")).strip()

                if not user_text.strip():
                    continue

                # Send typing indicator
                await websocket.send_text(json.dumps({"type": "typing", "status": True}))

                try:
                    available_chat_models = _list_chat_compatible_models()
                    available_model_names = [model["name"] for model in available_chat_models]
                    selected_model = _select_default_chat_model(
                        available_model_names,
                        config.llm.model,
                        requested_model or None,
                    )
                    if not selected_model:
                        raise RuntimeError(
                            "No compatible Ollama chat models are currently available. Pull one in the Models view first."
                        )

                    if selected_model != (requested_model or config.llm.model):
                        missing_model = requested_model or config.llm.model
                        await websocket.send_text(json.dumps({
                            "type": "model_info",
                            "selected_model": selected_model,
                            "requested_model": missing_model,
                            "fallback": True,
                            "message": f"Model '{missing_model}' is unavailable. Using '{selected_model}' instead.",
                        }))

                    runtime_config = config.model_copy(
                        update={
                            "llm": config.llm.model_copy(update={"model": selected_model}),
                        }
                    )

                    from cv_agent.agent import run_agent_stream

                    # Signal stream start so client creates the message bubble
                    await websocket.send_text(json.dumps({
                        "type": "stream_start",
                        "role": "assistant",
                        "model": selected_model,
                    }))

                    final_content = ""
                    async for event in run_agent_stream(user_text, runtime_config, history):
                        etype = event["type"]

                        if etype == "token":
                            await websocket.send_text(json.dumps({
                                "type": "stream_token",
                                "content": event["content"],
                            }))

                        elif etype == "tool_start":
                            await websocket.send_text(json.dumps({
                                "type": "tool_start",
                                "name": event["name"],
                                "input": event.get("input", ""),
                            }))

                        elif etype == "tool_end":
                            await websocket.send_text(json.dumps({
                                "type": "tool_end",
                                "name": event["name"],
                                "output": event.get("output", ""),
                            }))

                        elif etype == "done":
                            final_content = event["content"]

                    # Send final rendered message
                    await websocket.send_text(json.dumps({
                        "type": "stream_end",
                        "content": final_content,
                        "html": markdown.markdown(
                            final_content,
                            extensions=["fenced_code", "tables", "codehilite"],
                        ),
                        "timestamp": datetime.now().isoformat(),
                    }))

                    from langchain_core.messages import HumanMessage
                    history.append(HumanMessage(content=user_text))
                    history.append({"role": "assistant", "content": final_content})

                except Exception as e:
                    logger.exception("Agent error")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": f"Agent error: {e}",
                    }))
                finally:
                    await websocket.send_text(json.dumps({"type": "typing", "status": False}))

        except WebSocketDisconnect:
            logger.info("Chat client disconnected")

    # ── REST API for content browsing ──────────────────────────────────────

    @app.get("/api/vault/tree")
    async def vault_tree():
        """Get the vault directory tree."""
        vault = Path(config.knowledge.vault_path).expanduser().resolve()
        if not vault.exists():
            return JSONResponse({"tree": []})

        def _scan(directory: Path, depth: int = 0) -> list[dict]:
            items = []
            if depth > 4:
                return items
            try:
                for entry in sorted(directory.iterdir()):
                    if entry.name.startswith("."):
                        continue
                    node: dict[str, Any] = {
                        "name": entry.name,
                        "path": str(entry.relative_to(vault)),
                    }
                    if entry.is_dir():
                        node["type"] = "folder"
                        node["children"] = _scan(entry, depth + 1)
                    else:
                        node["type"] = "file"
                        node["size"] = entry.stat().st_size
                    items.append(node)
            except PermissionError:
                pass
            return items

        return JSONResponse({"tree": _scan(vault)})

    @app.get("/api/vault/note/{path:path}")
    async def vault_note(path: str):
        """Read a specific vault note and return as HTML."""
        vault = Path(config.knowledge.vault_path).expanduser().resolve()
        note_path = (vault / path).resolve()

        # Prevent directory traversal
        if not str(note_path).startswith(str(vault)):
            return JSONResponse({"error": "Invalid path"}, status_code=400)
        if not note_path.exists() or not note_path.is_file():
            return JSONResponse({"error": "Not found"}, status_code=404)

        content = note_path.read_text(errors="replace")
        html = markdown.markdown(
            content,
            extensions=["fenced_code", "tables", "meta"],
        )
        return JSONResponse({"path": path, "raw": content, "html": html})

    @app.get("/api/specs")
    async def list_specs():
        """List generated spec files."""
        specs_dir = Path(config.spec.output_dir).expanduser().resolve()
        if not specs_dir.exists():
            return JSONResponse({"specs": []})

        specs = []
        for f in sorted(specs_dir.glob("*.md"), reverse=True):
            specs.append({
                "name": f.name,
                "path": str(f),
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return JSONResponse({"specs": specs})

    @app.get("/api/specs/{filename}")
    async def read_spec(filename: str):
        """Read a specific spec file."""
        specs_dir = Path(config.spec.output_dir).expanduser().resolve()
        spec_path = (specs_dir / filename).resolve()

        if not str(spec_path).startswith(str(specs_dir)):
            return JSONResponse({"error": "Invalid path"}, status_code=400)
        if not spec_path.exists():
            return JSONResponse({"error": "Not found"}, status_code=404)

        content = spec_path.read_text()
        html = markdown.markdown(content, extensions=["fenced_code", "tables"])
        return JSONResponse({"name": filename, "raw": content, "html": html})

    @app.get("/api/digests")
    async def list_digests():
        """List generated digest files."""
        digests_dir = Path(config.output.digests_dir).expanduser().resolve()
        if not digests_dir.exists():
            return JSONResponse({"digests": []})

        digests = []
        for f in sorted(digests_dir.glob("*.md"), reverse=True):
            digests.append({
                "name": f.name,
                "path": str(f),
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return JSONResponse({"digests": digests})

    @app.get("/api/digests/{filename}")
    async def read_digest(filename: str):
        """Read a specific digest file."""
        digests_dir = Path(config.output.digests_dir).expanduser().resolve()
        digest_path = (digests_dir / filename).resolve()

        if not str(digest_path).startswith(str(digests_dir)):
            return JSONResponse({"error": "Invalid path"}, status_code=400)
        if not digest_path.exists():
            return JSONResponse({"error": "Not found"}, status_code=404)

        content = digest_path.read_text()
        html = markdown.markdown(content, extensions=["fenced_code", "tables"])
        return JSONResponse({"name": filename, "raw": content, "html": html})

    @app.get("/api/graph")
    async def graph_data():
        """Get knowledge graph data for visualization."""
        from cv_agent.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph(config.knowledge)
        data = kg.to_dict()
        stats = kg.get_stats()
        return JSONResponse({"graph": data, "stats": stats})

    @app.get("/api/graph/mermaid")
    async def graph_mermaid():
        """Get knowledge graph as Mermaid diagram."""
        from cv_agent.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph(config.knowledge)
        return JSONResponse({"mermaid": kg.to_mermaid()})

    @app.get("/api/status")
    async def status():
        """Agent health/status check."""
        return JSONResponse({
            "status": "ok",
            "agent": config.name,
            "llm_model": config.llm.model,
            "vision_model": config.vision.ollama.default_model,
            "vault_path": config.knowledge.vault_path,
        })

    @app.get("/api/chat/models")
    async def chat_models():
        """List locally available Ollama models that can power the main chat."""
        models = _list_chat_compatible_models()
        available_names = [model["name"] for model in models]
        default_model = _select_default_chat_model(available_names, config.llm.model)

        message = ""
        if not models:
            message = "No compatible Ollama chat models are pulled yet. Open Models to pull one first."
        elif config.llm.model not in available_names and default_model:
            message = (
                f"Configured chat model '{config.llm.model}' is not pulled. "
                f"Select '{default_model}' or another available model below."
            )

        return JSONResponse({
            "configured_model": config.llm.model,
            "configured_model_available": config.llm.model in available_names,
            "default_model": default_model,
            "message": message,
            "models": models,
        })

    # ── Text To Diagram ───────────────────────────────────────────────────

    _T2D_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
        "ollama": {
            "vlm_provider": "ollama",
            "image_provider": "mermaid_local",
            "api_key_env": "",
            "label": "Ollama Local",
        },
        "gemini": {
            "vlm_provider": "gemini",
            "image_provider": "google_imagen",
            "api_key_env": "GOOGLE_API_KEY",
            "label": "Google Gemini",
        },
        "openai": {
            "vlm_provider": "openai",
            "image_provider": "openai_imagen",
            "api_key_env": "OPENAI_API_KEY",
            "label": "OpenAI",
        },
        "openrouter": {
            "vlm_provider": "openrouter",
            "image_provider": "openrouter_imagen",
            "api_key_env": "OPENROUTER_API_KEY",
            "label": "OpenRouter",
        },
    }

    _T2D_VLM_PROVIDER_OPTIONS: dict[str, dict[str, str]] = {
        "ollama": {
            "provider": "ollama",
            "label": "Ollama Local",
            "required_env": "",
        },
        "gemini": {
            "provider": "gemini",
            "label": "Google Gemini",
            "required_env": "GOOGLE_API_KEY",
        },
        "openai": {
            "provider": "openai",
            "label": "OpenAI",
            "required_env": "OPENAI_API_KEY",
        },
        "openrouter": {
            "provider": "openrouter",
            "label": "OpenRouter",
            "required_env": "OPENROUTER_API_KEY",
        },
    }

    _T2D_IMAGE_PROVIDER_OPTIONS: dict[str, dict[str, str]] = {
        "mermaid_local": {
            "provider": "mermaid_local",
            "label": "Mermaid Local (SVG)",
            "required_env": "",
        },
        "matplotlib": {
            "provider": "matplotlib",
            "label": "Matplotlib (local)",
            "required_env": "",
        },
        "google_imagen": {
            "provider": "google_imagen",
            "label": "Google Imagen",
            "required_env": "GOOGLE_API_KEY",
        },
        "openai_imagen": {
            "provider": "openai_imagen",
            "label": "OpenAI Image",
            "required_env": "OPENAI_API_KEY",
        },
        "openrouter_imagen": {
            "provider": "openrouter_imagen",
            "label": "OpenRouter Image",
            "required_env": "OPENROUTER_API_KEY",
        },
        # Alias for a common Stable Diffusion route through OpenRouter.
        "stability": {
            "provider": "openrouter_imagen",
            "label": "Stability (via OpenRouter)",
            "required_env": "OPENROUTER_API_KEY",
        },
    }

    def _normalize_t2d_provider(raw_provider: str | None, cfg_now: AgentConfig) -> str:
        candidate = (raw_provider or cfg_now.text_to_diagram.vlm_provider or "ollama").strip().lower()
        return candidate if candidate in _T2D_PROVIDER_PRESETS else "ollama"

    def _normalize_t2d_vlm_provider(
        raw_vlm_provider: str | None,
        cfg_now: AgentConfig,
        legacy_provider: str | None,
    ) -> str:
        if raw_vlm_provider:
            candidate = raw_vlm_provider.strip().lower()
            if candidate in _T2D_VLM_PROVIDER_OPTIONS:
                return candidate
        if legacy_provider and legacy_provider in _T2D_PROVIDER_PRESETS:
            return _T2D_PROVIDER_PRESETS[legacy_provider]["vlm_provider"]
        configured = (cfg_now.text_to_diagram.vlm_provider or "ollama").strip().lower()
        return configured if configured in _T2D_VLM_PROVIDER_OPTIONS else "ollama"

    def _normalize_t2d_image_provider(
        raw_image_provider: str | None,
        cfg_now: AgentConfig,
        legacy_provider: str | None,
    ) -> str:
        if raw_image_provider:
            candidate = raw_image_provider.strip().lower()
            if candidate in _T2D_IMAGE_PROVIDER_OPTIONS:
                return candidate
        if legacy_provider and legacy_provider in _T2D_PROVIDER_PRESETS:
            return _T2D_PROVIDER_PRESETS[legacy_provider]["image_provider"]
        configured = (cfg_now.text_to_diagram.image_provider or "matplotlib").strip().lower()
        return configured if configured in _T2D_IMAGE_PROVIDER_OPTIONS else "matplotlib"

    def _effective_t2d_image_provider(image_provider: str) -> str:
        return _T2D_IMAGE_PROVIDER_OPTIONS[image_provider]["provider"]

    def _slug_words(text: str, max_words: int = 3) -> str:
        words = re.findall(r"[A-Za-z0-9]+", text.lower())
        if not words:
            return "step"
        return "_".join(words[:max_words])

    def _build_mermaid_from_text(caption: str, source_text: str, diagram_type: str) -> str:
        sentences = [s.strip() for s in re.split(r"[\n\.]+", source_text) if s.strip()]
        top = sentences[:4] if sentences else ["Input", "Processing", "Output"]
        title = (caption or "Method Diagram").strip()
        direction = "TD" if str(diagram_type).lower() == "methodology" else "LR"

        lines = [f"flowchart {direction}"]
        prev_node = None
        for idx, sentence in enumerate(top, start=1):
            label = re.sub(r"\s+", " ", sentence)[:64]
            node = f"S{idx}_{_slug_words(label)}"
            lines.append(f"    {node}[\"{label}\"]")
            if prev_node is not None:
                lines.append(f"    {prev_node} --> {node}")
            prev_node = node

        if prev_node:
            lines.append(f"    {prev_node} --> OUT[\"{title[:64]}\"]")

        return "\n".join(lines)

    def _default_t2d_vlm_model(vlm_provider: str, cfg_now: AgentConfig) -> str:
        if vlm_provider == "ollama":
            return cfg_now.text_to_diagram.ollama_vlm_model
        if vlm_provider == "gemini":
            return os.environ.get("PAPERBANANA_GEMINI_VLM_MODEL") or "gemini-2.0-flash"
        if vlm_provider == "openai":
            return os.environ.get("PAPERBANANA_OPENAI_VLM_MODEL") or "gpt-4o"
        return os.environ.get("PAPERBANANA_OPENROUTER_VLM_MODEL") or "openai/gpt-4o-mini"

    def _default_t2d_image_model(image_provider: str) -> str:
        if image_provider == "mermaid_local":
            return "beautiful-mermaid"
        if image_provider == "matplotlib":
            return "matplotlib"
        if image_provider == "google_imagen":
            return os.environ.get("PAPERBANANA_GEMINI_IMAGE_MODEL") or "gemini-3-pro-image-preview"
        if image_provider == "openai_imagen":
            return os.environ.get("PAPERBANANA_OPENAI_IMAGE_MODEL") or "gpt-image-1"
        if image_provider == "openrouter_imagen":
            return os.environ.get("PAPERBANANA_OPENROUTER_IMAGE_MODEL") or "openai/gpt-image-1"
        if image_provider == "stability":
            return os.environ.get("PAPERBANANA_STABILITY_IMAGE_MODEL") or "stabilityai/stable-diffusion-3.5-large"
        return "matplotlib"

    def _resolve_t2d_models(
        vlm_provider: str,
        image_provider: str,
        cfg_now: AgentConfig,
        vlm_model: str | None,
        image_model: str | None,
    ) -> tuple[str, str]:
        selected_vlm_model = (vlm_model or _default_t2d_vlm_model(vlm_provider, cfg_now)).strip()
        if image_provider == "matplotlib":
            return selected_vlm_model, "matplotlib"
        if image_provider == "mermaid_local":
            return selected_vlm_model, "beautiful-mermaid"
        selected_image_model = (image_model or _default_t2d_image_model(image_provider)).strip()
        return selected_vlm_model, selected_image_model

    def _build_t2d_settings_kwargs(
        selected_vlm_provider: str,
        selected_image_provider: str,
        cfg_now: AgentConfig,
        selected_vlm_model: str,
        selected_image_model: str,
        requested_iterations: int,
        requested_output_format: str,
    ) -> dict[str, Any]:
        t2d = cfg_now.text_to_diagram
        effective_image_provider = _effective_t2d_image_provider(selected_image_provider)
        kwargs: dict[str, Any] = {
            "vlm_provider": selected_vlm_provider,
            "image_provider": effective_image_provider,
            "vlm_model": selected_vlm_model,
            "image_model": selected_image_model,
            "output_dir": t2d.output_dir,
            "refinement_iterations": requested_iterations,
            "max_iterations": requested_iterations,
            "output_format": "png" if requested_output_format == "svg" else requested_output_format,
            "ollama_base_url": t2d.ollama_base_url,
            "ollama_code_model": t2d.ollama_code_model,
        }

        if selected_vlm_provider == "ollama":
            kwargs["ollama_vlm_model"] = selected_vlm_model
        elif selected_vlm_provider == "gemini":
            kwargs["google_api_key"] = os.environ.get("GOOGLE_API_KEY")
        elif selected_vlm_provider == "openai":
            kwargs["openai_api_key"] = os.environ.get("OPENAI_API_KEY")
            kwargs["openai_base_url"] = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            kwargs["openai_vlm_model"] = selected_vlm_model
        elif selected_vlm_provider == "openrouter":
            kwargs["openrouter_api_key"] = os.environ.get("OPENROUTER_API_KEY")

        if effective_image_provider == "google_imagen":
            kwargs["google_api_key"] = os.environ.get("GOOGLE_API_KEY")
        elif effective_image_provider == "openai_imagen":
            kwargs["openai_api_key"] = os.environ.get("OPENAI_API_KEY")
            kwargs["openai_base_url"] = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            kwargs["openai_image_model"] = selected_image_model
        elif effective_image_provider == "openrouter_imagen":
            kwargs["openrouter_api_key"] = os.environ.get("OPENROUTER_API_KEY")

        return kwargs

    def _format_t2d_exception(exc: Exception) -> str:
        """Unwrap nested provider errors (e.g. tenacity RetryError) into actionable text."""
        base = str(exc)
        nested_exc = None

        last_attempt = getattr(exc, "last_attempt", None)
        if last_attempt is not None:
            try:
                nested_exc = last_attempt.exception()
            except Exception:
                nested_exc = None

        if nested_exc is not None:
            base = f"{type(nested_exc).__name__}: {nested_exc}"

        if "not found for API version" in base and "generateContent" in base:
            base += " | Hint: use image model 'gemini-3-pro-image-preview' for provider 'google_imagen'."

        return base

    @app.get("/api/text-to-diagram/readiness")
    async def text_to_diagram_readiness(
        provider: str | None = None,
        vlm_provider: str | None = None,
        image_provider: str | None = None,
        vlm_model: str | None = None,
        image_model: str | None = None,
    ):
        issues: list[str] = []
        fixes: list[str] = []
        details: dict[str, Any] = {}

        cfg_now = load_config()
        t2d = cfg_now.text_to_diagram
        selected_provider = _normalize_t2d_provider(provider, cfg_now)
        selected_vlm_provider = _normalize_t2d_vlm_provider(vlm_provider, cfg_now, selected_provider)
        selected_image_provider = _normalize_t2d_image_provider(image_provider, cfg_now, selected_provider)
        effective_image_provider = _effective_t2d_image_provider(selected_image_provider)
        selected_vlm_model, selected_image_model = _resolve_t2d_models(
            selected_vlm_provider,
            selected_image_provider,
            cfg_now,
            vlm_model,
            image_model,
        )

        details["configured_vlm_provider"] = t2d.vlm_provider
        details["configured_image_provider"] = t2d.image_provider
        details["configured_vlm_model"] = t2d.ollama_vlm_model
        details["configured_code_model"] = t2d.ollama_code_model
        details["selected_profile"] = selected_provider
        details["selected_vlm_provider"] = selected_vlm_provider
        details["selected_image_provider"] = selected_image_provider
        details["selected_image_provider_effective"] = effective_image_provider
        details["selected_vlm_model"] = selected_vlm_model
        details["selected_image_model"] = selected_image_model
        details["profiles"] = {
            key: {
                "label": meta["label"],
                "vlm_provider": meta["vlm_provider"],
                "image_provider": meta["image_provider"],
            }
            for key, meta in _T2D_PROVIDER_PRESETS.items()
        }
        details["vlm_providers"] = {
            key: {
                "label": meta["label"],
                "default_vlm_model": _default_t2d_vlm_model(key, cfg_now),
                "required_env": meta["required_env"],
            }
            for key, meta in _T2D_VLM_PROVIDER_OPTIONS.items()
        }
        details["image_providers"] = {
            key: {
                "label": meta["label"],
                "effective_provider": meta["provider"],
                "default_image_model": _default_t2d_image_model(key),
                "required_env": meta["required_env"],
            }
            for key, meta in _T2D_IMAGE_PROVIDER_OPTIONS.items()
        }

        # Check package + provider modules are available in the installed Paperbanana.
        try:
            import importlib

            importlib.import_module("paperbanana")
            details["paperbanana_installed"] = True
        except Exception as exc:
            details["paperbanana_installed"] = False
            issues.append(f"paperbanana import failed: {exc}")
            fixes.append("pip install -e ./paperbanana")

        if selected_vlm_provider == "ollama":
            try:
                import importlib

                importlib.import_module("paperbanana.providers.vlm.ollama")
                details["ollama_provider_module"] = True
            except Exception as exc:
                details["ollama_provider_module"] = False
                issues.append(f"paperbanana missing ollama provider module: {exc}")
                fixes.append("Install/pin patched paperbanana with ollama provider support")

            if selected_image_provider == "matplotlib":
                try:
                    import importlib

                    importlib.import_module("paperbanana.providers.image_gen.matplotlib_gen")
                    details["matplotlib_provider_module"] = True
                except Exception as exc:
                    details["matplotlib_provider_module"] = False
                    issues.append(f"paperbanana missing matplotlib provider module: {exc}")
                    fixes.append("Install/pin patched paperbanana with matplotlib image provider support")

        # Check provider-level credentials and model availability.
        vlm_required_key = _T2D_VLM_PROVIDER_OPTIONS[selected_vlm_provider]["required_env"]
        if vlm_required_key and not os.environ.get(vlm_required_key, "").strip():
            issues.append(f"{vlm_required_key} is not set for VLM provider '{selected_vlm_provider}'")
            fixes.append(f"Set {vlm_required_key} in .env or in Powers → configure")

        image_required_key = _T2D_IMAGE_PROVIDER_OPTIONS[selected_image_provider]["required_env"]
        if image_required_key and not os.environ.get(image_required_key, "").strip():
            issues.append(
                f"{image_required_key} is not set for image provider '{selected_image_provider}'"
            )
            fixes.append(f"Set {image_required_key} in .env or in Powers → configure")

        if selected_vlm_provider == "ollama":
            from cv_agent.tools.hardware_probe import list_ollama_models

            ollama_host = t2d.ollama_base_url.removesuffix("/v1")
            pulled_models = list_ollama_models(ollama_host)
            details["ollama_host"] = ollama_host
            details["ollama_reachable"] = bool(pulled_models)
            details["pulled_models"] = pulled_models[:50]
            if not pulled_models:
                issues.append(f"Ollama not reachable at {ollama_host} or no models pulled")
                fixes.append("Start Ollama and ensure at least one model is pulled")

            if pulled_models and selected_vlm_model not in pulled_models:
                issues.append(
                    f"Selected VLM model '{selected_vlm_model}' not pulled in Ollama"
                )
                fixes.append(f"ollama pull {selected_vlm_model}")

            if pulled_models and t2d.ollama_code_model and t2d.ollama_code_model not in pulled_models:
                issues.append(
                    f"Configured code model '{t2d.ollama_code_model}' not pulled in Ollama"
                )
                fixes.append(f"ollama pull {t2d.ollama_code_model}")

        # De-duplicate fixes while preserving order.
        dedup_fixes: list[str] = []
        for item in fixes:
            if item not in dedup_fixes:
                dedup_fixes.append(item)

        return JSONResponse(
            {
                "ready": len(issues) == 0,
                "issues": issues,
                "fixes": dedup_fixes,
                "details": details,
            }
        )

    @app.post("/api/text-to-diagram/jobs")
    async def create_text_to_diagram_job(body: dict):
        source_text = str(body.get("source_text", ""))
        caption = str(body.get("caption", ""))
        diagram_type = str(body.get("diagram_type", "")) or config.text_to_diagram.default_diagram_type
        iterations = body.get("iterations")
        provider = str(body.get("provider", "")).strip().lower() if body.get("provider") is not None else None
        vlm_provider = (
            str(body.get("vlm_provider", "")).strip().lower()
            if body.get("vlm_provider") is not None
            else None
        )
        image_provider = (
            str(body.get("image_provider", "")).strip().lower()
            if body.get("image_provider") is not None
            else None
        )
        vlm_model = str(body.get("vlm_model", "")).strip() if body.get("vlm_model") is not None else None
        image_model = str(body.get("image_model", "")).strip() if body.get("image_model") is not None else None
        output_format = str(body.get("output_format", "png")).strip().lower()
        if output_format not in {"png", "svg"}:
            return JSONResponse({"error": "output_format must be one of: png, svg"}, status_code=400)

        if not source_text.strip():
            return JSONResponse({"error": "source_text is required"}, status_code=400)
        if not caption.strip():
            return JSONResponse({"error": "caption is required"}, status_code=400)

        job_id = uuid.uuid4().hex[:12]
        job: dict[str, Any] = {
            "id": job_id,
            "status": "queued",
            "source_text": source_text,
            "caption": caption,
            "diagram_type": diagram_type,
            "iterations_requested": int(iterations) if iterations is not None else config.text_to_diagram.default_iterations,
            "provider": provider,
            "vlm_provider": vlm_provider,
            "image_provider": image_provider,
            "vlm_model": vlm_model,
            "image_model": image_model,
            "output_format_requested": output_format,
            "output_format_effective": None,
            "final_mermaid": None,
            "events": [],
            "iterations": [],
            "seen_iterations": set(),
            "planning_seen": False,
            "run_id": None,
            "run_dir": None,
            "final_image_url": None,
            "result_description": "",
            "error": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        app.state.diagram_jobs[job_id] = job
        _add_diag_event(job, "Job created. Initializing Paperbanana pipeline...")

        async def _runner() -> None:
            from cv_agent.tools.hardware_probe import list_ollama_models
            from paperbanana import DiagramType, GenerationInput, PaperBananaPipeline
            from paperbanana.core.config import Settings

            try:
                job["status"] = "running"
                cfg_now = load_config()
                t2d = cfg_now.text_to_diagram
                requested_iterations = max(1, int(job["iterations_requested"]))
                selected_profile = _normalize_t2d_provider(job.get("provider"), cfg_now)
                selected_vlm_provider = _normalize_t2d_vlm_provider(
                    job.get("vlm_provider"),
                    cfg_now,
                    selected_profile,
                )
                selected_image_provider = _normalize_t2d_image_provider(
                    job.get("image_provider"),
                    cfg_now,
                    selected_profile,
                )
                selected_vlm_model, selected_image_model = _resolve_t2d_models(
                    selected_vlm_provider,
                    selected_image_provider,
                    cfg_now,
                    job.get("vlm_model"),
                    job.get("image_model"),
                )

                # Older UI defaults used a Gemini image preview model that is invalid for this API path.
                if selected_image_provider == "google_imagen" and "flash-image-preview" in selected_image_model:
                    selected_image_model = "gemini-3-pro-image-preview"
                    _add_diag_event(
                        job,
                        "Image model 'gemini-2.5-flash-image-preview' is not supported here. "
                        "Using 'gemini-3-pro-image-preview'.",
                        kind="warn",
                    )

                job["provider"] = selected_profile
                job["vlm_provider"] = selected_vlm_provider
                job["image_provider"] = selected_image_provider
                job["vlm_model"] = selected_vlm_model
                job["image_model"] = selected_image_model

                _add_diag_event(
                    job,
                    "Using providers/models: "
                    f"vlm={selected_vlm_provider} ({selected_vlm_model}), "
                    f"image={selected_image_provider} ({selected_image_model}), "
                    f"output={job.get('output_format_requested', 'png')}",
                )

                if selected_vlm_provider == "ollama":
                    ollama_host = t2d.ollama_base_url.removesuffix("/v1")
                    pulled_models = list_ollama_models(ollama_host)
                    if pulled_models and selected_vlm_model not in pulled_models:
                        preferred_model = cfg_now.vision.ollama.default_model
                        if preferred_model in pulled_models:
                            selected_vlm_model = preferred_model
                        else:
                            selected_vlm_model = next(
                                (m for m in pulled_models if any(k in m.lower() for k in ("vl", "llava", "vision"))),
                                pulled_models[0],
                            )
                        _add_diag_event(
                            job,
                            f"Configured VLM model '{t2d.ollama_vlm_model}' not found. Using '{selected_vlm_model}'.",
                            kind="warn",
                        )

                if selected_image_provider == "mermaid_local":
                    run_id = f"run_mermaid_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[:6]}"
                    run_dir = Path(t2d.output_dir).expanduser().resolve() / run_id
                    run_dir.mkdir(parents=True, exist_ok=True)

                    mermaid_code = _build_mermaid_from_text(caption=caption, source_text=source_text, diagram_type=diagram_type)
                    (run_dir / "final_output.mmd").write_text(mermaid_code)

                    job["run_id"] = run_id
                    job["run_dir"] = str(run_dir)
                    job["final_mermaid"] = mermaid_code
                    job["output_format_effective"] = "svg"
                    job["result_description"] = "Generated local Mermaid diagram source (rendered as SVG in UI)."
                    job["status"] = "completed"
                    _add_diag_event(job, "Mermaid local generation complete.", kind="success")
                    return

                settings = Settings(
                    **_build_t2d_settings_kwargs(
                        selected_vlm_provider=selected_vlm_provider,
                        selected_image_provider=selected_image_provider,
                        cfg_now=cfg_now,
                        selected_vlm_model=selected_vlm_model,
                        selected_image_model=selected_image_model,
                        requested_iterations=requested_iterations,
                        requested_output_format=job.get("output_format_requested", "png"),
                    )
                )

                try:
                    pipeline = PaperBananaPipeline(settings=settings)
                except Exception as exc:
                    if "Unknown VLM provider: ollama" not in str(exc):
                        raise

                    if selected_image_provider == "openai_imagen":
                        raise RuntimeError(
                            "This Paperbanana build lacks native ollama VLM provider support, and "
                            "OpenAI image generation cannot be combined with Ollama fallback mode. "
                            "Choose a different image provider (google_imagen/openrouter_imagen/matplotlib) "
                            "or upgrade Paperbanana with native ollama support."
                        )

                    settings = Settings(
                        vlm_provider="openai",
                        image_provider=_effective_t2d_image_provider(selected_image_provider),
                        vlm_model=selected_vlm_model,
                        image_model=selected_image_model,
                        openai_api_key=(os.environ.get("OPENAI_API_KEY") or "ollama-local"),
                        openai_base_url=t2d.ollama_base_url,
                        openai_vlm_model=selected_vlm_model,
                        google_api_key=os.environ.get("GOOGLE_API_KEY"),
                        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
                        ollama_code_model=t2d.ollama_code_model,
                        output_dir=t2d.output_dir,
                        output_format="png",
                        refinement_iterations=requested_iterations,
                        max_iterations=requested_iterations,
                    )
                    _add_diag_event(
                        job,
                        "Provider fallback applied: openai provider with Ollama-compatible /v1 endpoint.",
                        kind="warn",
                    )
                    pipeline = PaperBananaPipeline(settings=settings)
                run_dir = Path(settings.output_dir).expanduser().resolve() / pipeline.run_id
                job["run_id"] = pipeline.run_id
                job["run_dir"] = str(run_dir)
                _add_diag_event(job, f"Pipeline started (run_id={pipeline.run_id}).")

                run_task = asyncio.create_task(
                    pipeline.generate(
                        GenerationInput(
                            source_context=source_text,
                            communicative_intent=caption,
                            diagram_type=(
                                DiagramType.STATISTICAL_PLOT
                                if str(diagram_type).lower() == "statistical_plot"
                                else DiagramType.METHODOLOGY
                            ),
                        )
                    )
                )

                while not run_task.done():
                    _scan_diagram_job(job)
                    await asyncio.sleep(1)

                result = await run_task
                _scan_diagram_job(job)

                requested_output_format = (job.get("output_format_requested") or "png").lower()
                if requested_output_format == "svg" and job.get("run_dir"):
                    run_path = Path(job["run_dir"])
                    final_png = run_path / "final_output.png"
                    final_jpeg = run_path / "final_output.jpeg"
                    final_webp = run_path / "final_output.webp"
                    raster_source = final_png if final_png.exists() else final_jpeg if final_jpeg.exists() else final_webp
                    if raster_source and raster_source.exists():
                        final_svg = run_path / "final_output.svg"
                        _embed_raster_as_svg(raster_source, final_svg)
                        job["final_image_url"] = _project_relative_url(final_svg)
                        job["output_format_effective"] = "svg"
                        _add_diag_event(job, "Final output exported as SVG.")
                    else:
                        job["output_format_effective"] = "png"
                        _add_diag_event(
                            job,
                            "SVG export requested but raster source was not found; using PNG output.",
                            kind="warn",
                        )
                else:
                    job["output_format_effective"] = "png"

                job["result_description"] = result.description
                job["status"] = "completed"
                _add_diag_event(job, "Generation complete.", kind="success")
            except Exception as exc:
                job["status"] = "failed"
                error_text = _format_t2d_exception(exc)
                job["error"] = error_text
                _add_diag_event(job, f"Generation failed: {error_text}", kind="error")

        asyncio.create_task(_runner())
        return JSONResponse({"job_id": job_id})

    @app.get("/api/text-to-diagram/jobs/{job_id}")
    async def get_text_to_diagram_job(job_id: str):
        job = app.state.diagram_jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        _scan_diagram_job(job)
        return JSONResponse(
            {
                "id": job["id"],
                "status": job["status"],
                "caption": job["caption"],
                "diagram_type": job["diagram_type"],
                "iterations_requested": job["iterations_requested"],
                "provider": job["provider"],
                "vlm_provider": job.get("vlm_provider"),
                "image_provider": job.get("image_provider"),
                "vlm_model": job["vlm_model"],
                "image_model": job["image_model"],
                "output_format_requested": job.get("output_format_requested"),
                "output_format_effective": job.get("output_format_effective"),
                "run_id": job["run_id"],
                "final_image_url": job["final_image_url"],
                "final_mermaid": job.get("final_mermaid"),
                "result_description": job["result_description"],
                "error": job["error"],
                "events": job["events"],
                "iterations": sorted(job["iterations"], key=lambda x: x["iteration"]),
            }
        )

    # ── Sub-Agent API ──────────────────────────────────────────────────────

    from cv_agent.agents import AGENT_REGISTRY

    @app.get("/api/agents")
    async def list_agents():
        """List all available sub-agents and their enabled status."""
        result = []
        for key, info in AGENT_REGISTRY.items():
            agent_cfg = getattr(config.agents, info["config_key"])
            result.append({
                "id": key,
                "name": info["name"],
                "description": info["description"],
                "icon": info["icon"],
                "enabled": agent_cfg.enabled,
                "model": agent_cfg.model_override or config.llm.model,
            })
        return JSONResponse({"agents": result})

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: str):
        """Get info for a specific sub-agent."""
        if agent_id not in AGENT_REGISTRY:
            return JSONResponse({"error": f"Unknown agent: {agent_id}"}, status_code=404)
        info = AGENT_REGISTRY[agent_id]
        agent_cfg = getattr(config.agents, info["config_key"])
        return JSONResponse({
            "id": agent_id,
            "name": info["name"],
            "description": info["description"],
            "icon": info["icon"],
            "enabled": agent_cfg.enabled,
            "model": agent_cfg.model_override or config.llm.model,
        })

    @app.websocket("/ws/agent/{agent_id}")
    async def ws_agent(websocket: WebSocket, agent_id: str):
        await websocket.accept()

        if agent_id not in AGENT_REGISTRY:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"Unknown agent: {agent_id}",
            }))
            await websocket.close()
            return

        info = AGENT_REGISTRY[agent_id]
        agent_cfg = getattr(config.agents, info["config_key"])
        if not agent_cfg.enabled:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"{info['name']} is disabled.",
            }))
            await websocket.close()
            return

        history: list[Any] = []
        runner = info["runner"]

        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                user_text = msg.get("message", "")

                if not user_text.strip():
                    continue

                await websocket.send_text(json.dumps({"type": "typing", "status": True}))

                try:
                    response = await runner(user_text, config, history)

                    from langchain_core.messages import HumanMessage
                    history.append(HumanMessage(content=user_text))
                    history.append({"role": "assistant", "content": response})

                    await websocket.send_text(json.dumps({
                        "type": "message",
                        "role": "assistant",
                        "content": response,
                        "html": markdown.markdown(
                            response,
                            extensions=["fenced_code", "tables", "codehilite"],
                        ),
                        "timestamp": datetime.now().isoformat(),
                    }))
                except Exception as e:
                    logger.exception("Sub-agent error: %s", agent_id)
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": f"Agent error: {e}",
                    }))
                finally:
                    await websocket.send_text(json.dumps({"type": "typing", "status": False}))

        except WebSocketDisconnect:
            logger.info("Agent client disconnected: %s", agent_id)

    # ── Cache API ──────────────────────────────────────────────────────────

    @app.get("/api/cache/stats")
    async def cache_stats():
        """Return cache hit/miss stats and disk usage."""
        from cv_agent.cache import get_cache
        return JSONResponse(get_cache(config).stats())

    @app.post("/api/cache/clear")
    async def cache_clear():
        """Delete expired cache entries. Returns count of deleted files."""
        from cv_agent.cache import get_cache
        count = get_cache(config).clear()
        return JSONResponse({"deleted": count})

    # ── Remote Integrations ────────────────────────────────────────────────

    _PLATFORMS: dict = {
        "telegram": {
            "label": "Telegram", "icon": "✈️",
            "description": "Send messages via a Telegram Bot.",
            "docs": "Create a bot at t.me/BotFather, then use /getUpdates to find your Chat ID.",
            "fields": [
                {"key": "TELEGRAM_BOT_TOKEN", "label": "Bot Token", "secret": True,
                 "placeholder": "123456789:AAABB..."},
                {"key": "TELEGRAM_CHAT_ID", "label": "Chat ID", "secret": False,
                 "placeholder": "-1001234567890"},
            ],
            "enabled_key": "TELEGRAM_ENABLED",
        },
        "discord": {
            "label": "Discord", "icon": "🎮",
            "description": "Post to a Discord channel via an Incoming Webhook.",
            "docs": "Channel Settings → Integrations → Webhooks → New Webhook.",
            "fields": [
                {"key": "DISCORD_WEBHOOK_URL", "label": "Webhook URL", "secret": True,
                 "placeholder": "https://discord.com/api/webhooks/..."},
            ],
            "enabled_key": "DISCORD_ENABLED",
        },
        "whatsapp": {
            "label": "WhatsApp", "icon": "💬",
            "description": "Send via Meta Cloud API (WhatsApp Business).",
            "docs": "Requires a Meta Business account. Get credentials at developers.facebook.com.",
            "fields": [
                {"key": "WHATSAPP_ACCESS_TOKEN", "label": "Access Token", "secret": True,
                 "placeholder": "EAABxxx..."},
                {"key": "WHATSAPP_PHONE_NUMBER_ID", "label": "Phone Number ID", "secret": False,
                 "placeholder": "123456789012345"},
                {"key": "WHATSAPP_RECIPIENT", "label": "Default Recipient", "secret": False,
                 "placeholder": "+14155552671"},
            ],
            "enabled_key": "WHATSAPP_ENABLED",
        },
        "signal": {
            "label": "Signal", "icon": "🔒",
            "description": "Encrypted messages via signal-cli (self-hosted).",
            "docs": "Install signal-cli from github.com/AsamK/signal-cli and register your number.",
            "fields": [
                {"key": "SIGNAL_CLI_PATH", "label": "signal-cli path", "secret": False,
                 "placeholder": "signal-cli"},
                {"key": "SIGNAL_PHONE_NUMBER", "label": "Sender Number", "secret": False,
                 "placeholder": "+14155550000"},
                {"key": "SIGNAL_RECIPIENT", "label": "Default Recipient", "secret": False,
                 "placeholder": "+14155551111"},
            ],
            "enabled_key": "SIGNAL_ENABLED",
        },
    }

    def _mask(value: str) -> str:
        if not value:
            return ""
        return "•" * max(0, len(value) - 4) + value[-4:]

    @app.get("/api/integrations")
    async def list_integrations():
        """Return status and masked field values for all remote platforms."""
        result = {}
        for pid, meta in _PLATFORMS.items():
            field_values: dict[str, str] = {}
            configured = True
            for f in meta["fields"]:
                val = os.environ.get(f["key"], "")
                field_values[f["key"]] = _mask(val) if f["secret"] else val
                if not val:
                    configured = False
            result[pid] = {
                "label": meta["label"],
                "icon": meta["icon"],
                "description": meta["description"],
                "docs": meta["docs"],
                "configured": configured,
                "enabled": os.environ.get(meta["enabled_key"], "false").lower() == "true",
                "fields": meta["fields"],
                "field_values": field_values,
            }
        return JSONResponse(result)

    @app.post("/api/integrations/{platform}/configure")
    async def configure_integration(platform: str, body: dict):
        """Update credentials for a platform. Persists to .env and updates os.environ.

        Body: {"fields": {"ENV_KEY": "value", ...}, "enabled": bool}
        """
        if platform not in _PLATFORMS:
            return JSONResponse({"error": f"Unknown platform: {platform}"}, status_code=404)
        meta = _PLATFORMS[platform]
        allowed_keys = {f["key"] for f in meta["fields"]} | {meta["enabled_key"]}
        updates: dict[str, str] = {}
        for key, value in (body.get("fields") or {}).items():
            if key in allowed_keys and value is not None:
                os.environ[key] = str(value)
                updates[key] = str(value)
        enabled = body.get("enabled")
        if enabled is not None:
            os.environ[meta["enabled_key"]] = "true" if enabled else "false"
            updates[meta["enabled_key"]] = "true" if enabled else "false"
        # Persist to .env
        env_path = _PROJECT_ROOT / ".env"
        if env_path.exists() and updates:
            lines = env_path.read_text().splitlines()
            written: set[str] = set()
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=", 1)[0].strip()
                    if k in updates:
                        new_lines.append(f"{k}={updates[k]}")
                        written.add(k)
                        continue
                new_lines.append(line)
            for k, v in updates.items():
                if k not in written:
                    new_lines.append(f"{k}={v}")
            env_path.write_text("\n".join(new_lines) + "\n")
        return JSONResponse({"ok": True, "updated": list(updates.keys())})

    @app.post("/api/integrations/{platform}/test")
    async def test_integration(platform: str):
        """Test the connection for a remote platform."""
        if platform not in _PLATFORMS:
            return JSONResponse({"error": f"Unknown platform: {platform}"}, status_code=404)
        from cv_agent.http_client import httpx as _hx
        import subprocess as _sp

        if platform == "telegram":
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
            if not token:
                return JSONResponse({"ok": False, "message": "Bot token not set."})
            try:
                r = _hx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
                if r.status_code != 200:
                    return JSONResponse({"ok": False, "message": f"API error {r.status_code}: {r.text[:100]}"})
                name = r.json().get("result", {}).get("username", "unknown")
                msg = f"Bot @{name} reachable."
                if chat_id:
                    _hx.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": "CV Agent: connection test ✓"},
                        timeout=5,
                    )
                    msg += f" Test message sent to {chat_id}."
                return JSONResponse({"ok": True, "message": msg})
            except Exception as exc:
                return JSONResponse({"ok": False, "message": str(exc)})

        elif platform == "discord":
            webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
            if not webhook:
                return JSONResponse({"ok": False, "message": "Webhook URL not set."})
            try:
                r = _hx.post(webhook, json={"content": "CV Agent: connection test ✓"}, timeout=5)
                if r.status_code in (200, 204):
                    return JSONResponse({"ok": True, "message": "Test message delivered to Discord."})
                return JSONResponse({"ok": False, "message": f"Error {r.status_code}: {r.text[:100]}"})
            except Exception as exc:
                return JSONResponse({"ok": False, "message": str(exc)})

        elif platform == "whatsapp":
            token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
            phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
            if not token or not phone_id:
                return JSONResponse({"ok": False, "message": "Access token or phone number ID not set."})
            try:
                r = _hx.get(
                    f"https://graph.facebook.com/v19.0/{phone_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5,
                )
                if r.status_code == 200:
                    display = r.json().get("display_phone_number", phone_id)
                    return JSONResponse({"ok": True, "message": f"WhatsApp number {display} verified."})
                return JSONResponse({"ok": False, "message": f"Meta API error {r.status_code}: {r.text[:100]}"})
            except Exception as exc:
                return JSONResponse({"ok": False, "message": str(exc)})

        elif platform == "signal":
            cli = os.environ.get("SIGNAL_CLI_PATH", "signal-cli").strip()
            try:
                r = _sp.run([cli, "--version"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    return JSONResponse({"ok": True, "message": f"{r.stdout.strip()} — signal-cli found."})
                return JSONResponse({"ok": False, "message": r.stderr.strip() or "non-zero exit."})
            except FileNotFoundError:
                return JSONResponse({"ok": False, "message": f"signal-cli not found at '{cli}'."})
            except Exception as exc:
                return JSONResponse({"ok": False, "message": str(exc)})

        return JSONResponse({"ok": False, "message": "Test not implemented."})

    # ── Model Management ───────────────────────────────────────────────────

    @app.get("/api/models")
    async def list_models():
        """List all models currently pulled in Ollama."""
        from cv_agent.tools.hardware_probe import list_ollama_models
        return JSONResponse({"models": list_ollama_models(config.vision.ollama.host)})

    @app.post("/api/models/pull")
    async def pull_model(body: dict):
        """Pull a model from Ollama registry. Body: {"model": "<tag>"}"""
        from cv_agent.tools.hardware_probe import ensure_ollama_model
        model = (body.get("model") or "").strip()
        if not model:
            return JSONResponse({"error": "model tag is required"}, status_code=400)
        already, msg = ensure_ollama_model(model, config.vision.ollama.host)
        return JSONResponse({"already_present": already, "message": msg, "model": model})

    @app.post("/api/models/pull-cmd")
    async def pull_model_cmd(body: dict):
        """Stream `ollama pull` progress as SSE (NDJSON from Ollama API)."""
        import json as _json
        from cv_agent.http_client import httpx as _httpx
        from fastapi.responses import StreamingResponse as _SR
        model = (body.get("model") or "").strip()
        if not model:
            return JSONResponse({"error": "model tag is required"}, status_code=400)
        ollama_host = config.vision.ollama.host.rstrip("/")

        async def _stream():
            try:
                async with _httpx.AsyncClient(timeout=600) as client:
                    async with client.stream(
                        "POST", f"{ollama_host}/api/pull",
                        json={"name": model, "stream": True},
                    ) as resp:
                        if resp.status_code != 200:
                            err = _json.dumps({"error": f"Ollama returned HTTP {resp.status_code}"})
                            yield f"data: {err}\n\n"
                            return
                        async for line in resp.aiter_lines():
                            if line:
                                yield f"data: {line}\n\n"
            except Exception as exc:
                yield f'data: {_json.dumps({"error": str(exc)})}\n\n'
            yield 'data: {"status":"__done__"}\n\n'

        return _SR(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.delete("/api/models/{name:path}")
    async def delete_model(name: str):
        """Delete a pulled model from Ollama."""
        from cv_agent.http_client import httpx as _httpx
        host = config.vision.ollama.host.rstrip("/")
        try:
            resp = _httpx.delete(
                f"{host}/api/delete",
                json={"name": name},
                timeout=30,
            )
            resp.raise_for_status()
            return JSONResponse({"message": f"Deleted '{name}'"})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/api/zeroclaw")
    async def zeroclaw_status():
        """ZeroClaw integration status — shim vs package, version, and PyPI update check."""
        import importlib.metadata as _meta

        # Check if the real zeroclaw-tools package is installed
        real_pkg: str | None = None
        try:
            real_pkg = _meta.version("zeroclaw-tools")
        except _meta.PackageNotFoundError:
            pass

        using_shim = real_pkg is None
        current_version = real_pkg if real_pkg else "shim-0.1.0"

        # Non-blocking PyPI version check
        pypi_version: str | None = None
        update_available = False
        try:
            from cv_agent.http_client import httpx as _httpx
            resp = _httpx.get("https://pypi.org/pypi/zeroclaw-tools/json", timeout=4)
            if resp.status_code == 200:
                pypi_version = resp.json()["info"]["version"]
                if real_pkg and real_pkg != pypi_version:
                    update_available = True
        except Exception:
            pass

        return JSONResponse({
            "mode": "shim" if using_shim else "package",
            "current_version": current_version,
            "pypi_version": pypi_version,
            "update_available": update_available,
            "package_on_pypi": pypi_version is not None,
            "agent_framework": "LangChain + LangGraph",
            "tool_call_mode": "text-based ReAct (balanced-brace extractor)",
            "builtin_tools": ["shell", "file_read", "file_write", "web_search", "http_request"],
            "shim_path": "src/zeroclaw_tools/__init__.py" if using_shim else None,
        })

    @app.get("/api/models/recommended")
    async def recommended_models():
        """Return llmfit hardware probe + recommended VLMs."""
        from cv_agent.tools.hardware_probe import (
            get_hardware_info, get_runnable_models, is_llmfit_available,
        )
        hw = get_hardware_info()
        recs = get_runnable_models(use_case="multimodal", min_fit="marginal", limit=10)
        return JSONResponse({
            "llmfit_available": is_llmfit_available(),
            "hardware": {
                "ram_gb": hw.ram_gb,
                "cpu_cores": hw.cpu_cores,
                "gpu_vram_gb": hw.gpu_vram_gb,
                "gpu_cores": hw.gpu_cores,
                "gpu_name": hw.gpu_name,
                "cpu_name": hw.cpu_name,
                "acceleration": hw.acceleration,
                "unified_memory": hw.unified_memory,
            } if hw else None,
            "recommended": [
                {
                    "name": m.name,
                    "provider": m.provider,
                    "fit": m.fit,
                    "quantization": m.quantization,
                    "score": round(m.composite_score, 1),
                    "vram_gb": round(m.vram_gb, 1),
                    "runtime": m.runtime,
                    "gguf_sources": m.gguf_sources,
                }
                for m in recs
            ],
        })

    # ── Local Servers ───────────────────────────────────────────────────────

    @app.get("/api/local-servers")
    async def list_local_servers():
        from cv_agent.server_manager import get_all_statuses
        return JSONResponse(await get_all_statuses())

    @app.post("/api/local-servers/{server_id}/start")
    async def start_local_server(server_id: str):
        from cv_agent.server_manager import start_server
        msg = await start_server(server_id)
        return JSONResponse({"message": msg})

    @app.post("/api/local-servers/{server_id}/stop")
    async def stop_local_server(server_id: str):
        from cv_agent.server_manager import stop_server
        msg = await stop_server(server_id)
        return JSONResponse({"message": msg})

    @app.post("/api/local-servers/{server_id}/restart")
    async def restart_local_server(server_id: str):
        from cv_agent.server_manager import restart_server
        msg = await restart_server(server_id)
        return JSONResponse({"message": msg})

    @app.patch("/api/local-servers/{server_id}")
    async def update_local_server(server_id: str, body: dict):
        from cv_agent.server_manager import set_device
        if "device" in body:
            set_device(server_id, body["device"])
        return JSONResponse({"ok": True})

    # ── Local Model Catalog ─────────────────────────────────────────────────

    @app.get("/api/local-models/downloads/active")
    async def active_local_downloads():
        from cv_agent.local_model_manager import get_active_downloads
        return JSONResponse(get_active_downloads())

    @app.get("/api/local-models/catalog")
    async def local_model_catalog():
        from cv_agent.local_model_manager import get_catalog_with_status
        return JSONResponse(get_catalog_with_status())

    @app.post("/api/local-models/{model_id}/download")
    async def download_local_model(model_id: str):
        from cv_agent.local_model_manager import stream_hf_download
        from fastapi.responses import StreamingResponse as _SR
        return _SR(
            stream_hf_download(model_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/local-models/{model_id}/reset")
    async def reset_local_model_download(model_id: str):
        from cv_agent.local_model_manager import reset_download, _ALL
        if model_id not in _ALL:
            return JSONResponse({"error": "Unknown model"}, status_code=404)
        reset_download(model_id)
        return JSONResponse({"ok": True, "reset": model_id})

    @app.delete("/api/local-models/{model_id}")
    async def delete_local_model(model_id: str):
        from cv_agent.local_model_manager import delete_model, _ALL
        if model_id not in _ALL:
            return JSONResponse({"error": "Unknown model"}, status_code=404)
        delete_model(model_id)
        return JSONResponse({"ok": True, "deleted": model_id})

    # ── Powers ─────────────────────────────────────────────────────────────

    @app.get("/api/powers")
    async def list_powers():
        """Return status of all agent powers (resource access / integrations)."""
        import importlib.util as _ilu

        def _e(k: str) -> str: return os.environ.get(k, "").strip()
        def _has(*keys: str) -> bool: return all(_e(k) for k in keys)
        def _pkg(n: str) -> bool: return _ilu.find_spec(n) is not None
        def _mask(v: str) -> str: return ("•" * max(0, len(v) - 4) + v[-4:]) if v else ""

        powers = {
            "internet_search": {
                "label": "Internet Search", "icon": "🔍", "category": "built-in",
                "description": "Search the web for current research, news, and documentation.",
                "status": "active",
                "detail": "DuckDuckGo (ddgs)" + (" + Brave Search API" if _e("BRAVE_API_KEY") else " — set BRAVE_API_KEY for higher quality"),
                "configurable": True,
                "fields": [{"key": "BRAVE_API_KEY", "label": "Brave API Key", "secret": True, "placeholder": "BSA..."}],
                "field_values": {"BRAVE_API_KEY": _mask(_e("BRAVE_API_KEY"))},
            },
            "gemini": {
                "label": "Gemini API", "icon": "✨", "category": "cloud",
                "description": "Configure Google Gemini access for higher quality text-to-diagram generation.",
                "status": "active" if _has("GOOGLE_API_KEY") else "inactive",
                "detail": "GOOGLE_API_KEY configured — ready for Gemini providers" if _has("GOOGLE_API_KEY") else "Set GOOGLE_API_KEY to enable Gemini providers",
                "configurable": True,
                "fields": [{"key": "GOOGLE_API_KEY", "label": "Gemini API Key", "secret": True, "placeholder": "AIza..."}],
                "field_values": {"GOOGLE_API_KEY": _mask(_e("GOOGLE_API_KEY"))},
            },
            "file_system": {
                "label": "Local File System", "icon": "📁", "category": "built-in",
                "description": "Read and write files on the local machine via ZeroClaw built-in tools.",
                "status": "active",
                "detail": "file_read · file_write · shell (ZeroClaw built-in)",
                "configurable": False,
            },
            "arxiv": {
                "label": "ArXiv", "icon": "📚", "category": "built-in",
                "description": "Search and fetch papers from ArXiv across cs.CV, cs.AI, cs.LG and more.",
                "status": "active",
                "detail": "Free public API — no key required",
                "configurable": False,
            },
            "semantic_scholar": {
                "label": "Semantic Scholar", "icon": "🔬", "category": "built-in",
                "description": "Search papers with citation counts and author data.",
                "status": "active" if _has("SEMANTIC_SCHOLAR_API_KEY") else "limited",
                "detail": "API key set — full access" if _has("SEMANTIC_SCHOLAR_API_KEY") else "No key — rate limited. Add SEMANTIC_SCHOLAR_API_KEY for full access.",
                "configurable": True,
                "fields": [{"key": "SEMANTIC_SCHOLAR_API_KEY", "label": "API Key", "secret": True, "placeholder": "optional"}],
                "field_values": {"SEMANTIC_SCHOLAR_API_KEY": _mask(_e("SEMANTIC_SCHOLAR_API_KEY"))},
            },
            "email": {
                "label": "Email (SMTP)", "icon": "📧", "category": "integration",
                "description": "Send research summaries, paper alerts, and digest reports via email.",
                "status": "active" if _has("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD") else "inactive",
                "detail": f"SMTP: {_e('SMTP_HOST') or 'not configured'}",
                "configurable": True,
                "fields": [
                    {"key": "SMTP_HOST", "label": "SMTP Host", "secret": False, "placeholder": "smtp.gmail.com"},
                    {"key": "SMTP_PORT", "label": "Port", "secret": False, "placeholder": "587"},
                    {"key": "SMTP_USER", "label": "Username", "secret": False, "placeholder": "you@gmail.com"},
                    {"key": "SMTP_PASSWORD", "label": "App Password", "secret": True, "placeholder": ""},
                    {"key": "SMTP_FROM", "label": "From Address", "secret": False, "placeholder": "cv-agent@example.com"},
                    {"key": "SMTP_TO", "label": "Default Recipient", "secret": False, "placeholder": "you@example.com"},
                ],
                "field_values": {
                    "SMTP_HOST": _e("SMTP_HOST"), "SMTP_PORT": _e("SMTP_PORT"),
                    "SMTP_USER": _e("SMTP_USER"), "SMTP_PASSWORD": "••••" if _e("SMTP_PASSWORD") else "",
                    "SMTP_FROM": _e("SMTP_FROM"), "SMTP_TO": _e("SMTP_TO"),
                },
            },
            "huggingface": {
                "label": "HuggingFace Hub", "icon": "🤗", "category": "integration",
                "description": "Access private models, datasets, and run inference via HF Hub.",
                "status": "active" if _has("HF_TOKEN") else "inactive",
                "detail": "Token set — private models accessible" if _has("HF_TOKEN") else "No HF_TOKEN — public models only",
                "configurable": True,
                "fields": [{"key": "HF_TOKEN", "label": "Access Token", "secret": True, "placeholder": "hf_..."}],
                "field_values": {"HF_TOKEN": _mask(_e("HF_TOKEN"))},
            },
            "kaggle": {
                "label": "Kaggle", "icon": "🏆", "category": "integration",
                "description": "Download competition datasets, submit predictions, and monitor leaderboards.",
                "status": "active" if _has("KAGGLE_USERNAME", "KAGGLE_KEY") else "inactive",
                "detail": f"User: {_e('KAGGLE_USERNAME') or 'not configured'}",
                "configurable": True,
                "fields": [
                    {"key": "KAGGLE_USERNAME", "label": "Username", "secret": False, "placeholder": "your-kaggle-name"},
                    {"key": "KAGGLE_KEY", "label": "API Key", "secret": True, "placeholder": "from kaggle.com → Settings"},
                ],
                "field_values": {"KAGGLE_USERNAME": _e("KAGGLE_USERNAME"), "KAGGLE_KEY": _mask(_e("KAGGLE_KEY"))},
            },
            "github": {
                "label": "GitHub", "icon": "🐙", "category": "integration",
                "description": "Read/write repos, open issues, search code, and manage CI workflows.",
                "status": "active" if _has("GITHUB_TOKEN") else "inactive",
                "detail": "Token set — repo access enabled" if _has("GITHUB_TOKEN") else "No GITHUB_TOKEN — public repos only",
                "configurable": True,
                "fields": [{"key": "GITHUB_TOKEN", "label": "Personal Access Token", "secret": True, "placeholder": "ghp_..."}],
                "field_values": {"GITHUB_TOKEN": _mask(_e("GITHUB_TOKEN"))},
            },
            "azure_ml": {
                "label": "Azure ML", "icon": "☁️", "category": "cloud",
                "description": "Submit distributed training and fine-tuning jobs to Azure ML compute clusters.",
                "status": "active" if _has("AZURE_SUBSCRIPTION_ID", "AZURE_ML_WORKSPACE") else "inactive",
                "detail": f"Workspace: {_e('AZURE_ML_WORKSPACE') or 'not configured'}",
                "configurable": True,
                "fields": [
                    {"key": "AZURE_SUBSCRIPTION_ID", "label": "Subscription ID", "secret": False, "placeholder": "xxxxxxxx-xxxx-..."},
                    {"key": "AZURE_RESOURCE_GROUP", "label": "Resource Group", "secret": False, "placeholder": "my-rg"},
                    {"key": "AZURE_ML_WORKSPACE", "label": "Workspace Name", "secret": False, "placeholder": "my-aml-workspace"},
                    {"key": "AZURE_ML_COMPUTE", "label": "Compute Target", "secret": False, "placeholder": "gpu-cluster"},
                    {"key": "AZURE_CLIENT_ID", "label": "Service Principal ID", "secret": True, "placeholder": ""},
                    {"key": "AZURE_CLIENT_SECRET", "label": "SP Secret", "secret": True, "placeholder": ""},
                    {"key": "AZURE_TENANT_ID", "label": "Tenant ID", "secret": True, "placeholder": ""},
                ],
                "field_values": {
                    "AZURE_SUBSCRIPTION_ID": _e("AZURE_SUBSCRIPTION_ID"),
                    "AZURE_RESOURCE_GROUP": _e("AZURE_RESOURCE_GROUP"),
                    "AZURE_ML_WORKSPACE": _e("AZURE_ML_WORKSPACE"),
                    "AZURE_ML_COMPUTE": _e("AZURE_ML_COMPUTE"),
                    "AZURE_CLIENT_ID": "••••" if _e("AZURE_CLIENT_ID") else "",
                    "AZURE_CLIENT_SECRET": "••••" if _e("AZURE_CLIENT_SECRET") else "",
                    "AZURE_TENANT_ID": "••••" if _e("AZURE_TENANT_ID") else "",
                },
            },
            "runpod": {
                "label": "RunPod / GPU Cloud", "icon": "🚀", "category": "cloud",
                "description": "Rent on-demand GPU pods for training and inference at low cost.",
                "status": "active" if _has("RUNPOD_API_KEY") else "inactive",
                "detail": "API key set" if _has("RUNPOD_API_KEY") else "No RUNPOD_API_KEY set",
                "configurable": True,
                "fields": [{"key": "RUNPOD_API_KEY", "label": "API Key", "secret": True, "placeholder": "from runpod.io → Settings"}],
                "field_values": {"RUNPOD_API_KEY": _mask(_e("RUNPOD_API_KEY"))},
            },
        }
        return JSONResponse(powers)

    @app.post("/api/powers/{power_id}/configure")
    async def configure_power(power_id: str, body: dict):
        """Update credentials for a power. Persists to .env and refreshes os.environ from .env."""
        from dotenv import load_dotenv as _load_dotenv
        fields: dict = body.get("fields", {})
        updates: dict[str, str] = {}
        for key, value in fields.items():
            v = str(value) if value is not None else ""
            if v and not v.startswith("••"):
                os.environ[key] = v
                if key == "HF_TOKEN":
                    os.environ["HUGGING_FACE_HUB_TOKEN"] = v
                updates[key] = v
        env_path = _PROJECT_ROOT / ".env"
        _persist_env_updates(env_path, updates)
        if "HF_TOKEN" in updates:
            _persist_huggingface_token(updates["HF_TOKEN"])
        # Re-load .env into os.environ so new values are visible immediately
        # (load_dotenv at import time won't pick up changes made after startup)
        _load_dotenv(env_path, override=True)
        return JSONResponse({"ok": True, "updated": list(updates.keys())})

    # ── Skills ─────────────────────────────────────────────────────────────

    @app.get("/api/skills")
    async def list_skills():
        """Return agent skills with readiness status based on active powers and installed packages."""
        import importlib.util as _ilu

        def _e(k: str) -> str: return os.environ.get(k, "").strip()
        def _has(*keys: str) -> bool: return all(_e(k) for k in keys)
        def _pkg(n: str) -> bool: return _ilu.find_spec(n) is not None

        has_kaggle = _has("KAGGLE_USERNAME", "KAGGLE_KEY")
        has_email  = _has("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")
        has_azure  = _has("AZURE_SUBSCRIPTION_ID", "AZURE_ML_WORKSPACE")
        has_hf     = bool(_e("HF_TOKEN"))
        has_3d     = _pkg("open3d") or _pkg("trimesh") or _pkg("pyntcloud")
        has_video  = _pkg("cv2") or _pkg("decord")
        has_paperbanana = _pkg("paperbanana")

        from cv_agent.local_model_manager import is_model_downloaded
        from cv_agent.tools.segment_anything import get_sam3_runtime_status

        has_monkey_ocr = is_model_downloaded("monkey-ocr")
        has_paddle_ocr = _pkg("paddleocr")
        has_any_ocr    = has_monkey_ocr or has_paddle_ocr
        sam3_runtime = get_sam3_runtime_status()
        has_sam3_pkg = bool(sam3_runtime["has_sam3_pkg"])
        has_sam3_model = bool(sam3_runtime["has_sam3_model"])
        has_sam3_mlx_model = bool(sam3_runtime["has_sam3_mlx_model"])
        has_mlx_pkg = bool(sam3_runtime["has_mlx_pkg"])
        has_mlx_src = bool(sam3_runtime["has_mlx_src"])
        has_any_sam3_model = bool(sam3_runtime["has_any_model"])
        sam3_ready = bool(sam3_runtime["ready"])

        import sys as _sys
        _py = _sys.executable

        sam3_status = "ready"
        sam3_missing: list[str] = []
        sam3_models: list[dict[str, str]] = []
        sam3_commands: list[str] = []
        sam3_install: str | None = None

        if sam3_ready:
            sam3_status = "ready"
        elif has_sam3_mlx_model:
            sam3_status = "needs-install"
            if not has_mlx_pkg:
                sam3_missing.append("mlx package")
                sam3_commands.append(f'"{_py}" -m pip install mlx')
            if not has_mlx_src:
                sam3_missing.append("mlx_sam3 source")
                sam3_commands.insert(0, "git clone https://github.com/Deekshith-Dade/mlx_sam3.git")
            if not has_mlx_pkg and not has_mlx_src:
                sam3_install = "git clone https://github.com/Deekshith-Dade/mlx_sam3.git && pip install mlx"
            elif not has_mlx_src:
                sam3_install = "git clone https://github.com/Deekshith-Dade/mlx_sam3.git"
            elif not has_mlx_pkg:
                sam3_install = "pip install mlx"
        elif has_sam3_model:
            sam3_status = "needs-install"
            if not has_sam3_pkg:
                sam3_missing.append("sam3 package")
                sam3_commands.extend([
                    "git clone https://github.com/facebookresearch/sam3",
                    f'"{_py}" -m pip install -e sam3/',
                ])
                sam3_install = "git clone https://github.com/facebookresearch/sam3 && pip install -e sam3/"
        elif has_sam3_pkg or has_mlx_pkg or has_mlx_src:
            sam3_status = "needs-model"
            sam3_missing.append("SAM 3 or SAM 3 MLX model weights")
            sam3_models = [
                {"id": "sam3-mlx", "label": "SAM 3 MLX (3.4 GB, Apple Silicon)"},
                {"id": "sam3", "label": "SAM 3 (~6.9 GB, gated)"},
            ]
        else:
            sam3_status = "needs-install"
            sam3_missing.extend([
                "sam3 package or mlx runtime",
                "SAM 3 or SAM 3 MLX model weights",
            ])
            sam3_models = [
                {"id": "sam3-mlx", "label": "SAM 3 MLX (3.4 GB, Apple Silicon)"},
                {"id": "sam3", "label": "SAM 3 (~6.9 GB, gated)"},
            ]
            sam3_commands = [
                "git clone https://github.com/facebookresearch/sam3",
                f'"{_py}" -m pip install -e sam3/',
                "git clone https://github.com/Deekshith-Dade/mlx_sam3.git",
                f'"{_py}" -m pip install mlx',
            ]
            sam3_install = "git clone https://github.com/facebookresearch/sam3 && pip install -e sam3/"

        def _skill(label, icon, category, description, status, tools,
                   missing=None, packages=None, models=None, powers=None,
                   model=None, model_label=None, install=None, commands=None,
                   view=None):
            return {
                "label": label, "icon": icon, "category": category,
                "description": description, "status": status, "tools": tools,
                "missing": missing or [],
                "packages": packages or [],   # list of pip package names to install
                "models": models or [],        # list of {id, label} model dicts to download
                "powers": powers or [],        # list of {id, label} power dicts to configure
                "commands": commands or [],    # list of shell commands to run in order
                "model": model, "model_label": model_label,
                "install": install,
                "view": view,
            }

        skills = {
            "research_blog": _skill(
                "Write Research Blog", "✍️", "content",
                "Generate weekly digest posts, paper summaries, and deep-dive articles on CV breakthroughs.",
                "ready", ["search_arxiv", "web_search", "file_write"],
            ),
            "weekly_digest": _skill(
                "Weekly Digest", "📰", "content",
                "Curated weekly magazine of CV breakthroughs — auto-pulled from ArXiv and web, formatted as Markdown.",
                "ready", ["search_arxiv", "web_search", "file_write"],
            ),
            "email_reports": _skill(
                "Email Reports", "📧", "content",
                "Send automated digest emails and paper alerts to a recipient list.",
                "ready" if has_email else "needs-power", [],
                missing=[] if has_email else ["Email power (SMTP)"],
                powers=[] if has_email else [{"id": "email", "label": "Email (SMTP)"}],
            ),
            "2d_image_processing": _skill(
                "2D Image Processing", "🖼️", "vision",
                "Analyse, describe, and compare 2D images using VLMs (Qwen2.5-VL, LLaVA) and MLX vision models.",
                "ready", ["analyze_image", "describe_image", "compare_images", "pull_vision_model"],
            ),
            "3d_image_processing": _skill(
                "3D Image Processing", "🧊", "vision",
                "Process point clouds, depth maps, mesh data, and NeRF outputs using Open3D or Trimesh.",
                "ready" if has_3d else "needs-install", ["shell", "file_read"],
                missing=[] if has_3d else ["open3d"],
                packages=[] if has_3d else ["open3d"],
                install=None if has_3d else "pip install open3d",
            ),
            "video_understanding": _skill(
                "Video Understanding", "🎥", "vision",
                "Analyse video streams, extract key frames, and understand temporal patterns in CV datasets.",
                "ready" if has_video else "needs-install", ["analyze_image", "shell"],
                missing=[] if has_video else ["opencv-python"],
                packages=[] if has_video else ["opencv-python"],
                install=None if has_video else "pip install opencv-python",
            ),
            "image_stitching": _skill(
                "Image Stitching", "🧩", "vision",
                "Stitch multiple overlapping images into seamless panoramas or mosaics using OpenCV feature matching.",
                "ready" if _pkg("cv2") else "needs-install", ["shell", "file_read", "file_write"],
                missing=[] if _pkg("cv2") else ["opencv-python"],
                packages=[] if _pkg("cv2") else ["opencv-python"],
                install=None if _pkg("cv2") else "pip install opencv-python",
            ),
            "object_detection": _skill(
                "Object Detection", "🎯", "vision",
                "Detect and localise objects using torchvision Faster R-CNN / FCOS / RetinaNet or HuggingFace RT-DETR (Apache 2.0 / BSD-3 only).",
                "ready" if (_pkg("torchvision") or _pkg("transformers")) else "needs-install",
                ["analyze_image", "shell"],
                missing=[] if (_pkg("torchvision") or _pkg("transformers")) else ["torchvision"],
                packages=[] if (_pkg("torchvision") or _pkg("transformers")) else ["torchvision"],
                install=None if (_pkg("torchvision") or _pkg("transformers")) else "pip install torchvision",
            ),
            "object_tracking": _skill(
                "Object Tracking", "📡", "vision",
                "Track objects across video frames using supervision (MIT) with ByteTrack / SORT, or SAM 3 video segmentation.",
                "ready" if _pkg("supervision") else "needs-install", ["shell", "file_read", "file_write"],
                missing=[] if _pkg("supervision") else ["supervision"],
                packages=[] if _pkg("supervision") else ["supervision"],
                install=None if _pkg("supervision") else "pip install supervision",
            ),
            "segment_anything": _skill(
                "Segment Anything (SAM3)", "✂️", "vision",
                "Segment any object in images or videos using SAM3 (848M params). "
                "Supports natural-language text prompts, bounding-box prompts, and video object tracking. "
                "PyTorch model is gated — request access at hf.co/facebook/sam3. "
                "MLX model (Apple Silicon, ~2× faster) available without gating.",
                sam3_status,
                ["segment_with_text", "segment_with_box", "segment_video"],
                missing=sam3_missing,
                packages=[],
                models=[] if has_any_sam3_model else sam3_models,
                commands=sam3_commands,
                install=sam3_install,
            ),
            "text_to_image": _skill(
                "Text → Image", "🖼️", "vision",
                "Generate images from text prompts using diffusers (Apache 2.0) — SD-Turbo, SDXL-Turbo. Runs locally on MPS / CUDA / CPU.",
                "ready" if _pkg("diffusers") else "needs-install", ["shell", "file_write"],
                missing=[] if _pkg("diffusers") else ["diffusers", "accelerate"],
                packages=[] if _pkg("diffusers") else ["diffusers", "transformers", "accelerate"],
                models=[] if _pkg("diffusers") else [{"id": "sd-turbo", "label": "SD-Turbo (4.8 GB)"}],
                install=None if _pkg("diffusers") else "pip install diffusers transformers accelerate",
            ),
            "super_resolution": _skill(
                "Super Resolution", "🔭", "vision",
                "Upscale images 2×–4× using spandrel (MIT) — supports ESRGAN, SwinIR, HAT, and Real-ESRGAN architectures.",
                "ready" if (_pkg("spandrel") or _pkg("basicsr")) else "needs-install",
                ["shell", "file_read", "file_write"],
                missing=[] if (_pkg("spandrel") or _pkg("basicsr")) else ["spandrel"],
                packages=[] if (_pkg("spandrel") or _pkg("basicsr")) else ["spandrel"],
                install=None if (_pkg("spandrel") or _pkg("basicsr")) else "pip install spandrel",
            ),
            "image_denoising": _skill(
                "Image Denoising", "✨", "vision",
                "Remove noise from images using kornia (Apache 2.0) — Gaussian, bilateral, NLM, and diffusion-based denoisers.",
                "ready" if (_pkg("kornia") or _pkg("skimage")) else "needs-install",
                ["shell", "file_read", "file_write"],
                missing=[] if (_pkg("kornia") or _pkg("skimage")) else ["kornia"],
                packages=[] if (_pkg("kornia") or _pkg("skimage")) else ["kornia"],
                install=None if (_pkg("kornia") or _pkg("skimage")) else "pip install kornia",
            ),
            "document_extraction": _skill(
                "OCR · Text Extraction", "📄", "vision",
                "Extract text from images and documents using Apple MLX-accelerated Monkey OCR (v1.5) or PaddleOCR (multi-language).",
                "ready" if has_any_ocr else "needs-install", ["shell", "file_read", "file_write"],
                missing=[] if has_any_ocr else ["paddleocr", "mlx-vlm"],
                packages=[] if has_any_ocr else ["paddleocr", "paddlepaddle", "mlx-vlm"],
                install=None if has_any_ocr else "pip install paddleocr paddlepaddle mlx-vlm",
                view="ocr",
            ),
            "paper_to_spec": _skill(
                "Paper → Spec", "📋", "research",
                "Convert papers to spec.md files with equations, architecture diagrams, and implementation requirements.",
                "ready", ["fetch_arxiv_paper", "extract_equations", "generate_spec"],
            ),
            "knowledge_graph": _skill(
                "Knowledge Graph", "🕸️", "research",
                "Build and query Obsidian-compatible vaults linking papers, methods, datasets, and concepts.",
                "ready", ["add_paper_to_graph", "query_graph", "export_graph"],
            ),
            "equation_extraction": _skill(
                "Equation Extraction", "∑", "research",
                "Extract LaTeX equations, loss functions, and mathematical formulations from PDF papers.",
                "ready", ["extract_equations", "extract_key_info"],
            ),
            "text_to_diagram": _skill(
                "Text → Diagram", "🧭", "research",
                "Paste or write text and generate diagrams via Paperbanana (Ollama + matplotlib).",
                "ready" if has_paperbanana else "needs-install", ["text_to_diagram"],
                missing=[] if has_paperbanana else ["paperbanana"],
                packages=[] if has_paperbanana else ["paperbanana"],
                install=None if has_paperbanana else "pip install -e ./paperbanana",
            ),
            "kaggle_competition": _skill(
                "Kaggle Competition", "🏆", "ml",
                "Analyse tasks, download datasets, build baselines, and submit competition predictions.",
                "ready" if has_kaggle else "needs-power", ["web_search", "shell", "file_read", "file_write"],
                missing=[] if has_kaggle else ["Kaggle API credentials"],
                powers=[] if has_kaggle else [{"id": "kaggle", "label": "Kaggle (API key)"}],
            ),
            "model_fine_tuning": _skill(
                "Model Fine-Tuning", "🎯", "ml",
                "Fine-tune vision models with HuggingFace Trainer locally or on Azure ML compute clusters.",
                "ready" if (has_hf or has_azure) else "needs-power", ["shell", "file_read", "file_write"],
                missing=([] if has_hf else ["HuggingFace token"]) + ([] if has_azure else ["Azure ML"]),
                powers=([] if has_hf else [{"id": "huggingface", "label": "HuggingFace Hub"}]) +
                       ([] if has_azure else [{"id": "azure_ml", "label": "Azure ML"}]),
            ),
            "dataset_analysis": _skill(
                "Dataset Analysis", "📊", "ml",
                "Profile CV datasets, compute statistics, visualise class distributions and annotation quality.",
                "ready", ["shell", "file_read", "analyze_image"],
            ),
            "dataset_visualization": _skill(
                "Dataset Visualization", "🔬", "ml",
                "Browse and visualise downloaded datasets — images with annotation overlays for classification labels, "
                "bounding boxes, and segmentation masks. Supports all HuggingFace dataset formats.",
                "ready" if _pkg("PIL") or _pkg("Pillow") else "needs-install",
                ["shell", "file_read"],
                packages=[] if (_pkg("PIL") or _pkg("Pillow")) else ["Pillow", "datasets"],
                install=None if (_pkg("PIL") or _pkg("Pillow")) else "pip install Pillow datasets",
            ),
        }

        # Dynamically check Eko sidecar for agentic_workflows skill
        eko_ready = False
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{config.workflow.eko_sidecar_url.rstrip('/')}/health")
                eko_ready = r.status_code == 200
        except Exception:
            pass

        skills["agentic_workflows"] = _skill(
            "Agentic Workflows", "🗺️", "research",
            "Define and run multi-step autonomous research workflows orchestrated by the Eko engine. "
            "Includes headless browser automation via Playwright, human-in-the-loop checkpoints, "
            "and reusable template saving.",
            "ready" if eko_ready else "needs-power",
            ["browser_navigate", "browser_screenshot", "browser_extract_text", "browser_click"],
            missing=[] if eko_ready else ["Eko Workflow Engine (start from Server Management)"],
        )

        return JSONResponse(skills)

    @app.post("/api/skills/install-packages")
    async def install_skill_packages(body: dict):
        """Stream pip install output as SSE for a list of packages."""
        import json as _json
        import sys as _sys
        from fastapi.responses import StreamingResponse as _SR

        packages: list[str] = body.get("packages", [])
        if not packages:
            return JSONResponse({"error": "no packages specified"}, status_code=400)

        async def _stream():
            cmd = [_sys.executable, "-m", "pip", "install", *packages]
            cmd_str = "$ pip install " + " ".join(packages)
            yield f'data: {_json.dumps({"line": cmd_str})}\n\n'
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                if line:
                    yield f'data: {_json.dumps({"line": line})}\n\n'
            await proc.wait()
            if proc.returncode == 0:
                yield f'data: {_json.dumps({"status": "__done__", "success": True})}\n\n'
            else:
                yield f'data: {_json.dumps({"status": "__done__", "success": False, "returncode": proc.returncode})}\n\n'

        return _SR(_stream(), media_type="text/event-stream",
                   headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/skills/run-command")
    async def run_skill_command(body: dict):
        """Stream output of a shell command as SSE (used for git clone / pip install -e steps)."""
        import json as _json
        from fastapi.responses import StreamingResponse as _SR

        command: str = body.get("command", "").strip()
        if not command:
            return JSONResponse({"error": "no command specified"}, status_code=400)

        async def _stream():
            yield f'data: {_json.dumps({"line": f"$ {command}"})}\n\n'
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                if line:
                    yield f'data: {_json.dumps({"line": line})}\n\n'
            await proc.wait()
            done = {"status": "__done__", "success": proc.returncode == 0, "returncode": proc.returncode}
            yield f'data: {_json.dumps(done)}\n\n'

        return _SR(_stream(), media_type="text/event-stream",
                   headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── SAM3 Playground ────────────────────────────────────────────────────

    @app.post("/api/upload-image")
    async def upload_image_generic(file: UploadFile = File(...)):
        """Generic image upload — saves to output/uploads/, returns {path, url}."""
        import uuid
        from pathlib import Path as _P
        upload_dir = _P("output/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = _P(file.filename or "image.jpg").suffix.lower() or ".jpg"
        fname = f"upload_{uuid.uuid4().hex[:12]}{ext}"
        dest = upload_dir / fname
        dest.write_bytes(await file.read())
        return JSONResponse({"path": str(dest), "url": f"/output/uploads/{fname}"})

    @app.post("/api/sam3/upload")
    async def sam3_upload_image(file: UploadFile = File(...)):
        """Accept an image upload, save to output/segments/uploads/, return path + dimensions."""
        import uuid
        from pathlib import Path as _P
        try:
            from PIL import Image as _PIL
        except ImportError:
            _PIL = None

        upload_dir = _P("output/segments/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)

        ext = _P(file.filename or "image.jpg").suffix.lower() or ".jpg"
        fname = f"upload_{uuid.uuid4().hex[:12]}{ext}"
        dest = upload_dir / fname

        data = await file.read()
        dest.write_bytes(data)

        w, h = 0, 0
        if _PIL:
            try:
                img = _PIL.open(dest)
                w, h = img.size
            except Exception:
                pass

        return JSONResponse({
            "image_path": str(dest),
            "url": f"/output/segments/uploads/{fname}",
            "width": w,
            "height": h,
        })

    @app.get("/api/sam3/status")
    async def sam3_status():
        """Check whether any SAM3 backend is available for the playground."""
        from cv_agent.tools.segment_anything import get_sam3_runtime_status

        sam3_runtime = get_sam3_runtime_status()
        has_pkg = bool(sam3_runtime["has_sam3_pkg"])
        has_model = bool(sam3_runtime["has_any_model"])
        ready = bool(sam3_runtime["ready"])

        if ready:
            message = "SAM3 ready"
        elif sam3_runtime["has_sam3_mlx_model"]:
            missing = []
            if not sam3_runtime["has_mlx_pkg"]:
                missing.append("install mlx")
            if not sam3_runtime["has_mlx_src"]:
                missing.append("clone mlx_sam3")
            message = (
                "SAM3-MLX weights found — " + " and ".join(missing) + " to use this skill"
                if missing
                else "SAM3-MLX weights found"
            )
        elif sam3_runtime["has_sam3_model"]:
            message = "SAM3 weights found — install sam3 package to use this skill"
        elif has_pkg or sam3_runtime["has_mlx_pkg"] or sam3_runtime["has_mlx_src"]:
            message = "Download SAM3 or SAM3-MLX weights from the Models page"
        else:
            message = "Install sam3 or SAM3-MLX runtime, then download model weights to use this skill"

        return JSONResponse({
            "ready": ready,
            "has_pkg": has_pkg,
            "has_model": has_model,
            "message": message,
            "available_models": sam3_runtime["available_models"],
        })

    @app.post("/api/sam3/segment")
    async def sam3_segment_endpoint(body: dict):
        """Run SAM3 segmentation on an uploaded image. Supports text and box prompt modes."""
        import json as _json
        from pathlib import Path as _P
        from cv_agent.tools.segment_anything import (
            segment_with_text, segment_with_box,
            _load_sam3_image, _load_sam3_mlx_image,
            _overlay_masks, _save_overlay, _extract_masks_scores_boxes,
        )

        image_path  = body.get("image_path", "")
        mode        = body.get("mode", "text")
        model_id    = body.get("model", "sam3")

        if not image_path:
            return JSONResponse({"error": "image_path is required"}, status_code=400)
        if not _P(image_path).exists():
            return JSONResponse({"error": f"Image file not found: {image_path}"}, status_code=404)

        # Dispatch to correct loader based on model_id
        if model_id == "sam3-mlx":
            def _run_mlx_sync() -> str:
                from PIL import Image as _Img
                loaded = _load_sam3_mlx_image()
                if loaded is None:
                    return _json.dumps({"error": "SAM3-MLX not available. Download the 'sam3-mlx' model and install mlx (pip install mlx)."})
                _model, processor = loaded
                try:
                    image = _Img.open(image_path).convert("RGB")
                    state = processor.set_image(image)
                    if mode == "text":
                        prompt = body.get("prompt", "").strip()
                        if not prompt:
                            return _json.dumps({"error": "prompt is required for text mode"})
                        output = processor.set_text_prompt(prompt=prompt, state=state)
                    elif mode == "box":
                        box_raw = body.get("box")
                        if not box_raw:
                            return _json.dumps({"error": "box is required for box mode"})
                        b = box_raw if isinstance(box_raw, dict) else _json.loads(box_raw)
                        output = processor.add_geometric_prompt(
                            box=[b["x1"], b["y1"], b["x2"], b["y2"]], label=True, state=state
                        )
                    else:
                        return _json.dumps({"error": f"Unknown mode: {mode}"})
                    masks, scores, boxes_out = _extract_masks_scores_boxes(output)
                    _lbl = prompt if mode == "text" else ""
                    overlay = _overlay_masks(image, masks, scores=scores, boxes=boxes_out, label=_lbl)
                    out_file = _save_overlay(image_path, overlay)
                    return _json.dumps({
                        "output_path": out_file,
                        "mask_count": len(masks),
                        "scores": [round(s, 4) for s in scores],
                        "boxes": [b.tolist() if hasattr(b, "tolist") else b for b in boxes_out],
                        "model": "SAM3-MLX",
                    })
                except Exception as exc:
                    return _json.dumps({"error": f"SAM3-MLX inference failed: {exc}"})

            result_json = await asyncio.to_thread(_run_mlx_sync)
        else:
            # Default: PyTorch SAM3
            if mode == "text":
                prompt = body.get("prompt", "").strip()
                if not prompt:
                    return JSONResponse({"error": "prompt is required for text mode"}, status_code=400)
                result_json = await asyncio.to_thread(
                    segment_with_text.invoke,
                    {"image_path": image_path, "prompt": prompt, "output_path": ""},
                )
            elif mode == "box":
                box = body.get("box")
                if not box:
                    return JSONResponse({"error": "box is required for box mode"}, status_code=400)
                result_json = await asyncio.to_thread(
                    segment_with_box.invoke,
                    {"image_path": image_path, "box_json": _json.dumps(box), "output_path": ""},
                )
            else:
                return JSONResponse({"error": f"Unknown mode: {mode}"}, status_code=400)

        result = _json.loads(result_json)

        # Convert relative output path → web-accessible URL (/output/...)
        if "output_path" in result and result["output_path"]:
            result["output_url"] = "/" + result["output_path"].replace("\\", "/").lstrip("/")

        return JSONResponse(result)

    # ── PaddleOCR ──────────────────────────────────────────────────────────

    @app.get("/api/ocr/status")
    async def ocr_status():
        import importlib.util as _ilu
        has_paddle = _ilu.find_spec("paddleocr") is not None
        has_mlx = _ilu.find_spec("mlx_vlm") is not None
        from cv_agent.local_model_manager import is_model_downloaded
        import asyncio
        has_monkey = await asyncio.to_thread(is_model_downloaded, "monkey-ocr")
        has_pkg = has_paddle or (has_mlx and has_monkey)
        return JSONResponse({"ready": has_pkg, "message": "OCR Engine ready" if has_pkg else "OCR engine not installed"})

    @app.post("/api/ocr/run")
    async def ocr_run(body: dict):
        """Run OCR on an uploaded image."""
        import json as _json
        from pathlib import Path as _P
        from cv_agent.tools.ocr import run_ocr
        import importlib.util as _ilu
        from cv_agent.local_model_manager import is_model_downloaded
        import asyncio

        image_path = body.get("image_path", "")
        lang = body.get("lang", "en")

        if not image_path:
            return JSONResponse({"error": "image_path is required"}, status_code=400)
        if not _P(image_path).exists():
            return JSONResponse({"error": f"Image not found: {image_path}"}, status_code=404)
        
        has_paddle = _ilu.find_spec("paddleocr") is not None
        has_monkey = await asyncio.to_thread(is_model_downloaded, "monkey-ocr") and _ilu.find_spec("mlx_vlm") is not None
        
        engine = "monkeyocr" if has_monkey else "paddleocr"

        try:
            result_json = await asyncio.to_thread(
                run_ocr.invoke,
                {"image_path": image_path, "lang": lang, "engine": engine, "render_overlay": True},
            )
            result = _json.loads(result_json)
        except Exception as exc:
            return JSONResponse({"error": f"OCR failed: {exc}"}, status_code=500)
        if "overlay_path" in result and result["overlay_path"]:
            result["overlay_url"] = "/" + result["overlay_path"].replace("\\", "/").lstrip("/")
        return JSONResponse(result)

    # ── Overview ───────────────────────────────────────────────────────────

    @app.get("/api/overview")
    async def overview():
        """Aggregate dashboard stats."""
        import importlib.util as _ilu

        def _e(k: str) -> str:
            return os.environ.get(k, "").strip()

        # Models
        from cv_agent.tools.hardware_probe import list_ollama_models
        models = list_ollama_models(config.vision.ollama.host)

        # Vault notes count
        vault = Path(config.knowledge.vault_path).expanduser().resolve()
        vault_notes = len(list(vault.rglob("*.md"))) if vault.exists() else 0

        # Specs and digests count
        specs_dir = Path(config.spec.output_dir).expanduser().resolve()
        specs_count = len(list(specs_dir.glob("*.md"))) if specs_dir.exists() else 0
        digests_dir = Path(config.output.digests_dir).expanduser().resolve()
        digests_count = len(list(digests_dir.glob("*.md"))) if digests_dir.exists() else 0

        # Powers
        def _has(*keys: str) -> bool:
            return all(_e(k) for k in keys)
        power_defs = [
            ("internet_search", True),
            ("file_system", True),
            ("arxiv", True),
            ("semantic_scholar", bool(_e("SEMANTIC_SCHOLAR_API_KEY"))),
            ("email", _has("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")),
            ("huggingface", bool(_e("HF_TOKEN"))),
            ("kaggle", _has("KAGGLE_USERNAME", "KAGGLE_KEY")),
            ("github", bool(_e("GITHUB_TOKEN"))),
            ("azure_ml", _has("AZURE_SUBSCRIPTION_ID", "AZURE_ML_WORKSPACE")),
            ("runpod", bool(_e("RUNPOD_API_KEY"))),
        ]
        powers_active = sum(1 for _, active in power_defs if active)

        # Skills
        has_3d = _ilu.find_spec("open3d") is not None or _ilu.find_spec("trimesh") is not None
        has_video = _ilu.find_spec("cv2") is not None or _ilu.find_spec("decord") is not None
        has_paperbanana = _ilu.find_spec("paperbanana") is not None
        skill_ready = [
            True, True, _has("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"),
            True, has_3d, has_video, True, True, True,
            has_paperbanana,
            _has("KAGGLE_USERNAME", "KAGGLE_KEY"),
            bool(_e("HF_TOKEN")) or _has("AZURE_SUBSCRIPTION_ID", "AZURE_ML_WORKSPACE"),
            True,
        ]
        skills_ready = sum(skill_ready)

        # Channels
        channel_keys = [
            "TELEGRAM_ENABLED", "DISCORD_ENABLED",
            "WHATSAPP_ENABLED", "SIGNAL_ENABLED",
        ]
        channels_enabled = sum(
            1 for k in channel_keys if _e(k).lower() == "true"
        )

        # ZeroClaw mode
        try:
            import importlib.metadata as _meta
            _meta.version("zeroclaw-tools")
            zc_mode = "package"
        except Exception:
            zc_mode = "shim"

        return JSONResponse({
            "status": "ok",
            "agent_name": config.name,
            "llm_model": config.llm.model,
            "vision_model": config.vision.ollama.default_model,
            "vault_path": config.knowledge.vault_path,
            "models_pulled": len(models),
            "skills_ready": skills_ready,
            "skills_total": len(skill_ready),
            "powers_active": powers_active,
            "powers_total": len(power_defs),
            "channels_enabled": channels_enabled,
            "channels_total": len(channel_keys),
            "vault_notes": vault_notes,
            "specs_count": specs_count,
            "digests_count": digests_count,
            "zeroclaw_mode": zc_mode,
        })

    # ── Sessions ───────────────────────────────────────────────────────────

    @app.get("/api/sessions")
    async def list_sessions():
        """Return chat session info."""
        sessions = []
        if hasattr(app.state, "sessions"):
            sessions = app.state.sessions
        return JSONResponse({"sessions": sessions})

    # ── Cron Jobs ──────────────────────────────────────────────────────────

    @app.get("/api/cron")
    async def list_cron_jobs():
        """Return configured scheduled tasks."""
        digest_day = config.research.digest_day
        check_hours = config.research.check_interval_hours
        jobs = [
            {
                "name": "Weekly Research Digest",
                "icon": "📰",
                "description": f"Compile a curated digest of the latest CV breakthroughs from ArXiv, Papers With Code, and Semantic Scholar.",
                "schedule": f"Every {digest_day}",
                "enabled": True,
                "next_run": f"Next {digest_day}",
                "last_run": None,
            },
            {
                "name": "Research Monitor",
                "icon": "🔬",
                "description": f"Check all configured research sources for new papers and update the knowledge base.",
                "schedule": f"Every {check_hours}h",
                "enabled": True,
                "next_run": f"In {check_hours}h",
                "last_run": None,
            },
            {
                "name": "Knowledge Graph Sync",
                "icon": "🕸️",
                "description": "Re-scan the Obsidian vault and rebuild the knowledge graph from linked notes.",
                "schedule": "On demand",
                "enabled": True,
                "next_run": "Manual",
                "last_run": None,
            },
            {
                "id": "fine_tune",
                "name": "Model Fine-Tuning",
                "icon": "🎯",
                "description": "Fine-tune a vision model locally with HuggingFace Trainer. Supports image classification using ViT, ResNet, ConvNext and other HF vision models.",
                "schedule": "On demand",
                "enabled": True,
                "next_run": "Manual",
                "last_run": None,
                "type": "fine_tune",
                "runnable": True,
                "requires": ["transformers", "datasets", "accelerate"],
                "defaults": {
                    "model_id": "google/vit-base-patch16-224",
                    "dataset_id": "food101",
                    "label_column": "label",
                    "image_column": "image",
                    "epochs": 3,
                    "lr": "5e-5",
                    "batch_size": 16,
                    "output_name": "my-fine-tuned-model",
                },
            },
        ]
        
        # Add workflow templates
        from cv_agent.core.workflow_manager import workflow_manager
        try:
            templates = await workflow_manager.get_workflow_templates()
            for t in templates:
                jobs.append({
                    "id": t.get("id"),
                    "name": f"Workflow: {t.get('name', 'Unnamed')}",
                    "icon": "🗺️",
                    "description": t.get("description", ""),
                    "schedule": "On demand",
                    "enabled": True,
                    "next_run": "Manual",
                    "last_run": None,
                    "type": "workflow",
                    "runnable": True
                })
        except Exception as e:
            logger.warning(f"Failed to load workflow templates for cron view: {e}")

        return JSONResponse({"jobs": jobs})

    @app.post("/api/jobs/fine-tune/run")
    async def run_fine_tune_job(body: dict):
        """Stream HuggingFace Trainer fine-tuning output as SSE."""
        import sys as _sys
        import textwrap as _tw

        model_id    = body.get("model_id", "google/vit-base-patch16-224")
        dataset_id  = body.get("dataset_id", "food101")
        label_col   = body.get("label_column", "label")
        image_col   = body.get("image_column", "image")
        epochs      = int(body.get("epochs", 3))
        lr          = float(body.get("lr", 5e-5))
        batch_size  = int(body.get("batch_size", 16))
        output_name = body.get("output_name", "my-fine-tuned-model").strip().replace(" ", "-") or "my-fine-tuned-model"
        hf_token    = os.environ.get("HF_TOKEN") or None

        output_dir = _PROJECT_ROOT / "output" / "fine-tuned" / output_name
        output_dir.mkdir(parents=True, exist_ok=True)

        train_script = _tw.dedent(f"""\
            import os, warnings
            warnings.filterwarnings("ignore")
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            {"os.environ['HF_TOKEN'] = " + repr(hf_token) if hf_token else ""}

            from datasets import load_dataset
            from transformers import (
                AutoImageProcessor, AutoModelForImageClassification,
                TrainingArguments, Trainer, DefaultDataCollator,
            )
            import numpy as np, evaluate, torch
            from PIL import Image

            print("⬇  Loading dataset: {dataset_id}")
            ds = load_dataset("{dataset_id}")

            # Auto-detect num_labels
            label_names = ds["train"].features["{label_col}"].names if hasattr(ds["train"].features.get("{label_col}", None), "names") else sorted(set(ds["train"]["{label_col}"]))
            num_labels = len(label_names) if isinstance(label_names, list) else int(max(ds["train"]["{label_col}"]) + 1)
            id2label = {{i: str(l) for i, l in enumerate(label_names)}} if isinstance(label_names, list) else {{i: str(i) for i in range(num_labels)}}
            label2id = {{v: k for k, v in id2label.items()}}
            print(f"✅ Dataset loaded — {{len(ds['train'])}} train samples, {{num_labels}} classes")

            print("⬇  Loading model: {model_id}")
            processor = AutoImageProcessor.from_pretrained("{model_id}")
            model = AutoModelForImageClassification.from_pretrained(
                "{model_id}", num_labels=num_labels,
                id2label=id2label, label2id=label2id, ignore_mismatched_sizes=True,
            )
            print("✅ Model loaded")

            def preprocess(batch):
                imgs = [img.convert("RGB") if isinstance(img, Image.Image) else Image.fromarray(img).convert("RGB") for img in batch["{image_col}"]]
                return processor(images=imgs, return_tensors="pt")

            ds = ds.with_transform(preprocess)

            metric = evaluate.load("accuracy")
            def compute_metrics(p):
                preds = np.argmax(p.predictions, axis=1)
                return metric.compute(predictions=preds, references=p.label_ids)

            args = TrainingArguments(
                output_dir="{output_dir}",
                num_train_epochs={epochs},
                per_device_train_batch_size={batch_size},
                per_device_eval_batch_size={batch_size},
                learning_rate={lr},
                eval_strategy="epoch",
                save_strategy="epoch",
                load_best_model_at_end=True,
                logging_steps=50,
                remove_unused_columns=False,
                report_to="none",
            )
            trainer = Trainer(
                model=model, args=args,
                train_dataset=ds["train"],
                eval_dataset=ds.get("validation") or ds.get("test"),
                processing_class=processor,
                compute_metrics=compute_metrics,
                data_collator=DefaultDataCollator(),
            )
            print("🚀 Training started")
            trainer.train()
            trainer.save_model("{output_dir}")
            processor.save_pretrained("{output_dir}")
            print(f"✅ Model saved to {output_dir}")
        """)

        script_path = output_dir / "train.py"
        script_path.write_text(train_script)

        async def _stream():
            yield f'data: {json.dumps({"line": f"🎯 Fine-tuning {model_id} on {dataset_id}"})}\n\n'
            yield f'data: {json.dumps({"line": f"📁 Output: output/fine-tuned/{output_name}"})}\n\n'
            proc = await asyncio.create_subprocess_exec(
                _sys.executable, str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(_PROJECT_ROOT),
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                if line:
                    yield f'data: {json.dumps({"line": line})}\n\n'
            await proc.wait()
            success = proc.returncode == 0
            yield f'data: {json.dumps({"status": "__done__", "success": success, "output_dir": str(output_dir)})}\n\n'

        return StreamingResponse(_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Datasets ───────────────────────────────────────────────────────────

    @app.get("/api/datasets/search")
    async def search_datasets(q: str, source: str = "huggingface", limit: int = 10):
        """Search HuggingFace Hub or Kaggle for datasets matching q."""
        import asyncio as _asyncio

        def _hf_search():
            try:
                from huggingface_hub import list_datasets as _list_ds
                results = []
                for ds in _list_ds(search=q, limit=limit, sort="downloads", direction=-1):
                    results.append({
                        "id": ds.id,
                        "name": ds.id.split("/")[-1].replace("-", " ").replace("_", " ").title(),
                        "full_id": ds.id,
                        "downloads": getattr(ds, "downloads", 0),
                        "likes": getattr(ds, "likes", 0),
                        "tags": list(getattr(ds, "tags", []))[:6],
                        "source": "huggingface",
                        "url": f"https://huggingface.co/datasets/{ds.id}",
                    })
                return results
            except Exception as exc:
                return {"error": str(exc)}

        def _kaggle_search():
            try:
                import kaggle
                results = []
                for ds in kaggle.api.dataset_list(search=q, page_size=limit):
                    results.append({
                        "id": f"{ds.ref}",
                        "name": ds.title,
                        "full_id": ds.ref,
                        "downloads": getattr(ds, "downloadCount", 0),
                        "likes": getattr(ds, "voteCount", 0),
                        "tags": [],
                        "size_mb": getattr(ds, "totalBytes", 0) // (1024 * 1024),
                        "source": "kaggle",
                        "url": f"https://www.kaggle.com/datasets/{ds.ref}",
                    })
                return results
            except Exception as exc:
                return {"error": str(exc)}

        loop = _asyncio.get_running_loop()
        fn = _hf_search if source == "huggingface" else _kaggle_search
        data = await loop.run_in_executor(None, fn)
        if isinstance(data, dict) and "error" in data:
            return JSONResponse({"results": [], "error": data["error"]})
        return JSONResponse({"results": data})

    @app.post("/api/datasets/add-external")
    async def add_external_dataset(req: Request):
        """Register an external HF/Kaggle dataset into the catalog for download."""
        body = await req.json()
        dataset_id = body.get("id", "").strip().replace("/", "--")
        if not dataset_id:
            return JSONResponse({"error": "id required"}, status_code=400)
        from cv_agent.dataset_manager import _ALL, _BASE_DIR, DatasetEntry, _COMPLETE_SENTINEL, get_downloaded_size_gb
        import asyncio as _asyncio
        from fastapi.responses import StreamingResponse as _SR

        source = body.get("source", "huggingface")
        hf_repo = body.get("full_id", body.get("id"))
        name = body.get("name", dataset_id)
        size_gb = float(body.get("size_gb") or 0.5)

        if dataset_id not in _ALL:
            entry = DatasetEntry(
                id=dataset_id, name=name, desc=body.get("desc", ""),
                size_gb=size_gb, hf_repo=hf_repo,
            )
            _ALL[dataset_id] = entry

        async def _stream():
            entry = _ALL[dataset_id]
            try:
                from huggingface_hub import snapshot_download as _dl
            except ImportError:
                yield f'data: {json.dumps({"error": "huggingface_hub not installed"})}\n\n'
                return

            hf_token = os.environ.get("HF_TOKEN") or None
            local_dir = _BASE_DIR / dataset_id
            local_dir.mkdir(parents=True, exist_ok=True)

            import asyncio
            progress_queue: asyncio.Queue[dict] = asyncio.Queue()

            def _download():
                cache_dl_dir = local_dir / ".cache" / "huggingface" / "download"
                if cache_dl_dir.exists():
                    for lf in cache_dl_dir.glob("*.lock"):
                        lf.unlink(missing_ok=True)
                try:
                    _dl(repo_id=hf_repo, repo_type="dataset", local_dir=str(local_dir),
                        local_dir_use_symlinks=False, token=hf_token)
                    (local_dir / _COMPLETE_SENTINEL).touch()
                    progress_queue.put_nowait({"status": "__done__"})
                except Exception as exc:
                    progress_queue.put_nowait({"error": str(exc)})

            loop = asyncio.get_running_loop()
            dl_task = loop.run_in_executor(None, _download)
            yield f'data: {json.dumps({"status": "Starting download…", "dataset": name, "hf_repo": hf_repo})}\n\n'

            while not dl_task.done():
                while not progress_queue.empty():
                    ev = progress_queue.get_nowait()
                    yield f"data: {json.dumps(ev)}\n\n"
                    if ev.get("status") == "__done__" or ev.get("error"):
                        return
                current_gb = await loop.run_in_executor(None, get_downloaded_size_gb, dataset_id)
                yield f'data: {json.dumps({"status": "Downloading…", "downloaded_gb": current_gb, "total_gb": size_gb})}\n\n'
                await asyncio.sleep(1.5)

            while not progress_queue.empty():
                ev = progress_queue.get_nowait()
                yield f"data: {json.dumps(ev)}\n\n"
                if ev.get("status") == "__done__" or ev.get("error"):
                    return
            yield f'data: {json.dumps({"status": "__done__"})}\n\n'

        return _SR(_stream(), media_type="text/event-stream",
                   headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/datasets")
    async def list_datasets():
        from cv_agent.dataset_manager import get_catalog_with_status
        return JSONResponse({"datasets": get_catalog_with_status()})

    @app.get("/api/datasets/{dataset_id}")
    async def get_dataset(dataset_id: str):
        from cv_agent.dataset_manager import _ALL, is_dataset_downloaded, get_downloaded_size_gb
        entry = _ALL.get(dataset_id)
        if not entry:
            return JSONResponse({"error": f"Unknown dataset: {dataset_id}"}, status_code=404)
        downloaded = is_dataset_downloaded(dataset_id)
        return JSONResponse({
            "id": entry.id, "name": entry.name, "hf_repo": entry.hf_repo,
            "downloaded": downloaded,
            "local_size_gb": get_downloaded_size_gb(dataset_id) if downloaded else None,
        })

    @app.post("/api/datasets/{dataset_id}/download")
    async def download_dataset(dataset_id: str):
        from cv_agent.dataset_manager import stream_hf_download
        from fastapi.responses import StreamingResponse as _SR
        return _SR(
            stream_hf_download(dataset_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.delete("/api/datasets/{dataset_id}")
    async def delete_dataset_route(dataset_id: str):
        from cv_agent.dataset_manager import delete_dataset, _ALL
        if dataset_id not in _ALL:
            return JSONResponse({"error": f"Unknown dataset: {dataset_id}"}, status_code=404)
        delete_dataset(dataset_id)
        return JSONResponse({"ok": True})

    @app.get("/api/datasets/{dataset_id}/samples")
    async def dataset_samples(dataset_id: str, split: str = "train", offset: int = 0, limit: int = 12):
        """Return base64-encoded sample images with annotation overlays for visualization."""
        import asyncio as _asyncio
        from cv_agent.dataset_manager import _ALL, get_dataset_local_path, is_dataset_downloaded

        # Accept external (search-downloaded) datasets too
        entry = _ALL.get(dataset_id)
        local_dir = get_dataset_local_path(dataset_id)

        if not local_dir.exists():
            return JSONResponse({"error": "Dataset not downloaded"}, status_code=400)

        def _load():
            import io, base64
            try:
                from PIL import Image, ImageDraw
            except ImportError:
                return {"error": "Pillow not installed — run: pip install Pillow"}
            try:
                import datasets as hf_ds
            except ImportError:
                return {"error": "datasets not installed — run: pip install datasets"}

            # Check for old-style loading script (not supported by datasets >= 3.x)
            loading_scripts = list(local_dir.glob("*.py"))
            has_only_script = loading_scripts and not any(
                f.suffix in {".parquet", ".arrow", ".json", ".csv", ".jsonl"}
                for f in local_dir.rglob("*") if f.is_file() and not f.name.startswith(".")
                and f.name not in {"README.md"} and ".gitattributes" not in f.name
            )
            if has_only_script:
                return {
                    "error": f"This dataset uses an old loading script ({loading_scripts[0].name}) "
                             "that is no longer supported by the HuggingFace datasets library (v3+). "
                             "Try a dataset in Parquet format such as Food-101, CIFAR-100, or Oxford Pets.",
                    "script_based": True,
                }

            # Strategy 1: load parquet/imagefolder from local snapshot
            # Strategy 2: load_from_disk (save_to_disk format)
            # Strategy 3: raw image file scan
            ds_split = None

            try:
                loaded = hf_ds.load_dataset(str(local_dir.resolve()), split=split)
                ds_split = loaded
            except Exception:
                try:
                    loaded = hf_ds.load_from_disk(str(local_dir.resolve()))
                    ds_split = loaded[split] if split in loaded else next(iter(loaded.values()))
                except Exception:
                    pass

            if ds_split is None:
                # Final fallback: scan for local image files
                exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
                imgs = sorted([f for f in local_dir.rglob("*") if f.suffix.lower() in exts])
                if not imgs:
                    return {"error": "Could not load dataset — no Parquet/Arrow/image files found. "
                            "The dataset may need to be re-downloaded, or is in an unsupported format."}
                total_imgs = len(imgs)
                page_imgs = imgs[offset:offset + limit]
                samples = []
                for i, p in enumerate(page_imgs):
                    try:
                        img = Image.open(p).convert("RGB")
                        img.thumbnail((320, 320), Image.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=82)
                        b64 = base64.b64encode(buf.getvalue()).decode()
                        samples.append({"idx": offset + i, "image": f"data:image/jpeg;base64,{b64}",
                                        "label": p.parent.name, "filename": p.name})
                    except Exception:
                        continue
                return {"samples": samples, "total": total_imgs, "split": split,
                        "task": getattr(entry, "task", "") if entry else "", "fallback": True}

            total = len(ds_split)
            end = min(offset + limit, total)
            subset_iter = ds_split.select(range(offset, end))
            features = ds_split.features
            image_col  = next((c for c in ["image", "img", "pixel_values", "jpg", "png"] if c in features), None)
            label_col  = next((c for c in ["label", "labels", "class", "category", "scene_category", "fine_label", "coarse_label"] if c in features), None)
            mask_col   = next((c for c in ["annotation", "mask", "segmentation"] if c in features), None)
            bbox_col   = next((c for c in ["objects", "bbox", "bboxes"] if c in features), None)
            label_names = None
            if label_col and hasattr(features.get(label_col), "names"):
                label_names = features[label_col].names
            features = ds_split.features

            # Detect columns
            image_col  = next((c for c in ["image", "img", "pixel_values", "jpg", "png"] if c in features), None)
            label_col  = next((c for c in ["label", "labels", "class", "category", "scene_category", "fine_label", "coarse_label"] if c in features), None)
            mask_col   = next((c for c in ["annotation", "mask", "segmentation", "semantic_segmentation"] if c in features), None)
            bbox_col   = next((c for c in ["objects", "bbox", "bboxes", "annotations"] if c in features), None)

            import numpy as np

            COLORS = [(255,99,71),(50,205,50),(30,144,255),(255,215,0),(238,130,238),(255,165,0),(0,206,209),(220,20,60)]

            samples = []
            for i, row in enumerate(subset_iter):
                img = row.get(image_col) if image_col else None
                if img is None:
                    continue
                if not isinstance(img, Image.Image):
                    try:
                        img = Image.fromarray(np.array(img))
                    except Exception:
                        continue
                img = img.convert("RGB")

                # Resize for display
                img.thumbnail((320, 320), Image.LANCZOS)
                w, h = img.size

                # Segmentation mask overlay
                if mask_col:
                    raw_mask = row.get(mask_col)
                    if raw_mask is not None:
                        try:
                            if not isinstance(raw_mask, Image.Image):
                                raw_mask = Image.fromarray(np.array(raw_mask))
                            raw_mask = raw_mask.resize((w, h), Image.NEAREST).convert("L")
                            mask_arr = np.array(raw_mask)
                            # Colorize: each class id → a distinct hue
                            palette = np.zeros((256, 3), dtype=np.uint8)
                            for idx in range(256):
                                c = COLORS[idx % len(COLORS)]
                                palette[idx] = c
                            colored = palette[mask_arr]
                            overlay = Image.fromarray(colored, "RGB")
                            img = Image.blend(img, overlay, alpha=0.45)
                        except Exception:
                            pass

                draw = ImageDraw.Draw(img)
                label_text = ""

                # Classification label
                if label_col:
                    val = row.get(label_col)
                    if isinstance(val, int) and label_names and val < len(label_names):
                        label_text = label_names[val]
                    elif isinstance(val, str):
                        label_text = val
                    if label_text:
                        tw = min(len(label_text) * 7 + 8, w)
                        draw.rectangle([0, 0, tw, 18], fill=(0, 0, 0))
                        draw.text((4, 2), label_text[:36], fill=(255, 255, 255))

                # Bounding boxes
                if bbox_col:
                    objs = row.get(bbox_col)
                    if isinstance(objs, dict):
                        bboxes = objs.get("bbox") or objs.get("bboxes", [])
                        obj_labels = objs.get("category", objs.get("label", []))
                        for j, bb in enumerate(bboxes or []):
                            col = COLORS[j % len(COLORS)]
                            if len(bb) == 4:
                                x0, y0, x1, y1 = bb
                                draw.rectangle([x0, y0, x1, y1], outline=col, width=2)
                                lbl = obj_labels[j] if obj_labels and j < len(obj_labels) else ""
                                if isinstance(lbl, int) and label_names and lbl < len(label_names):
                                    lbl = label_names[lbl]
                                if lbl:
                                    draw.rectangle([x0, y0 - 14, x0 + len(str(lbl)) * 6 + 4, y0], fill=col)
                                    draw.text((x0 + 2, y0 - 13), str(lbl), fill=(255, 255, 255))

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=82)
                b64 = base64.b64encode(buf.getvalue()).decode()
                samples.append({
                    "idx": offset + i,
                    "image": f"data:image/jpeg;base64,{b64}",
                    "label": label_text,
                    "has_mask": mask_col is not None,
                    "has_bbox": bbox_col is not None,
                })

            return {
                "samples": samples,
                "total": total,
                "split": split,
                "task": getattr(entry, "task", "") if entry else "",
                "label_names": (label_names[:30] if label_names else None),
                "columns": {
                    "image": image_col, "label": label_col,
                    "mask": mask_col, "bbox": bbox_col,
                },
            }

        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _load)
        if isinstance(result, dict) and "error" in result and "samples" not in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)

    # ── Workflows ──────────────────────────────────────────────────────────

    @app.post("/api/workflows/run")
    async def run_workflow(body: dict):
        """Submit a workflow to the Eko sidecar."""
        from cv_agent.core.workflow_manager import workflow_manager
        desc = body.get("description")
        if not desc:
            return JSONResponse({"error": "Description is required"}, status_code=400)
        try:
            result = await workflow_manager.submit_workflow(desc)
            return JSONResponse(result, status_code=202)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/tools")
    async def list_tools():
        """List all available tools and their JSON schemas for Eko sidecar."""
        from cv_agent.agent import build_tools
        from cv_agent.config import load_config
        config = load_config()
        tools = build_tools(config)
        tool_list = []
        for t in tools:
            name = getattr(t, "name", getattr(t, "__name__", "unknown"))
            desc = getattr(t, "description", getattr(t, "__doc__", ""))
            
            # Simple schema extraction for zeroclaw / smolagents tools
            parameters = {"type": "object", "properties": {}}
            if hasattr(t, "args_schema") and t.args_schema:
                schema = t.args_schema.schema()
                parameters = {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", [])
                }
            elif hasattr(t, "inputs"):
                # smolagents style
                props = {}
                req = []
                for k, v in t.inputs.items():
                    props[k] = {"type": v.get("type", "string"), "description": v.get("description", "")}
                    req.append(k)
                parameters = {"type": "object", "properties": props, "required": req}
                
            tool_list.append({
                "name": name,
                "description": desc,
                "parameters": parameters
            })
        return JSONResponse({"tools": tool_list})

    @app.post("/api/tools/execute")
    async def execute_tool(body: dict):
        """Execute a Python tool on behalf of the Eko sidecar."""
        from cv_agent.agent import build_tools
        from cv_agent.config import load_config
        import inspect
        
        name = body.get("name")
        args = body.get("arguments", {})
        
        if not name:
            return JSONResponse({"error": "Tool name is required"}, status_code=400)
            
        config = load_config()
        tools = build_tools(config)
        
        target_tool = None
        for t in tools:
            t_name = getattr(t, "name", getattr(t, "__name__", None))
            if t_name == name:
                target_tool = t
                break
                
        if not target_tool:
            return JSONResponse({"error": f"Tool '{name}' not found"}, status_code=404)
            
        try:
            # LangChain BaseTool.invoke(input) takes a dict as its first positional
            # arg — do NOT unpack with **args or it errors with "missing 'input'".
            if hasattr(target_tool, "invoke"):
                result = target_tool.invoke(args)
            elif hasattr(target_tool, "func"):
                func = target_tool.func
                result = await func(**args) if inspect.iscoroutinefunction(func) else func(**args)
            else:
                result = await target_tool(**args) if inspect.iscoroutinefunction(target_tool) else target_tool(**args)

            return JSONResponse({"result": result})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/workflows/{run_id}/stream")
    async def stream_workflow(run_id: str):
        """Proxy the SSE execution stream from the Eko sidecar to the frontend."""
        from cv_agent.core.workflow_manager import workflow_manager
        from fastapi.responses import StreamingResponse as _SR
        import json

        async def _proxy_stream():
            async for data in workflow_manager.stream_workflow_status(run_id):
                yield f"data: {json.dumps(data)}\n\n"

        return _SR(_proxy_stream(), media_type="text/event-stream",
                   headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/workflows/checkpoint/{checkpoint_id}")
    async def resolve_workflow_checkpoint(checkpoint_id: str, body: dict):
        """Resolve a paused workflow checkpoint."""
        from cv_agent.core.workflow_manager import workflow_manager
        approved = body.get("approved", True)
        feedback = body.get("feedback", "")
        try:
            result = await workflow_manager.resolve_checkpoint(checkpoint_id, approved, feedback)
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/workflows/templates")
    async def list_workflow_templates():
        """Retrieve all saved workflow templates."""
        from cv_agent.core.workflow_manager import workflow_manager
        try:
            templates = await workflow_manager.get_workflow_templates()
            return JSONResponse({"templates": templates})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/workflows/templates")
    async def save_workflow_template(body: dict):
        """Save a new workflow template."""
        from cv_agent.core.workflow_manager import workflow_manager
        name = body.get("name")
        description = body.get("description")
        steps = body.get("steps", [])
        
        if not name or not description:
            return JSONResponse({"error": "Name and description are required"}, status_code=400)
            
        try:
            result = await workflow_manager.save_workflow_template(name, description, steps)
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Debug ──────────────────────────────────────────────────────────────

    @app.get("/api/debug")
    async def debug_info():
        """Return dependency and environment debug info."""
        import importlib.metadata as _meta
        import importlib.util as _ilu
        import sys

        deps = [
            "fastapi", "uvicorn", "httpx", "pydantic", "pyyaml",
            "jinja2", "networkx", "Pillow", "feedparser", "tiktoken",
            "rich", "click", "python-dotenv", "markdown",
            "zeroclaw-tools", "langchain-core", "langgraph",
            "mlx", "mlx-vlm", "open3d", "opencv-python",
        ]
        dep_list = []
        for d in deps:
            try:
                ver = _meta.version(d)
                dep_list.append({"name": d, "installed": True, "version": ver})
            except _meta.PackageNotFoundError:
                dep_list.append({"name": d, "installed": False, "version": None})

        tools = [
            "analyze_image", "describe_image", "compare_images",
            "mlx_analyze_image", "fetch_arxiv_paper", "search_arxiv",
            "extract_equations", "extract_key_info",
            "add_paper_to_graph", "query_graph", "export_graph",
            "generate_spec", "generate_spec_from_url",
        ]

        env = {
            "Python": sys.version.split()[0],
            "Platform": sys.platform,
            "Prefix": sys.prefix,
            "Agent": config.name,
            "LLM Provider": config.llm.provider,
            "LLM Model": config.llm.model,
            "Vision Model": config.vision.ollama.default_model,
            "Ollama Host": config.vision.ollama.host,
            "Vault Path": config.knowledge.vault_path,
        }

        return JSONResponse({
            "dependencies": dep_list,
            "tools": tools,
            "environment": env,
        })

    # ── Logs WebSocket ─────────────────────────────────────────────────────

    _log_buffer: list[str] = []

    class _WSLogHandler(logging.Handler):
        """Captures log records into a ring buffer for the WebSocket stream."""
        def emit(self, record: logging.LogRecord) -> None:
            msg = self.format(record)
            _log_buffer.append(msg)
            if len(_log_buffer) > 2000:
                _log_buffer.pop(0)

    _ws_handler = _WSLogHandler()
    _ws_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(_ws_handler)
    logging.getLogger("uvicorn.access").addHandler(_ws_handler)
    logging.getLogger("uvicorn.error").addHandler(_ws_handler)

    @app.websocket("/ws/logs")
    async def ws_logs(websocket: WebSocket):
        await websocket.accept()
        # Send buffered logs first
        for line in _log_buffer[-200:]:
            await websocket.send_text(line)
        cursor = len(_log_buffer)
        try:
            while True:
                await asyncio.sleep(0.5)
                new_logs = _log_buffer[cursor:]
                for line in new_logs:
                    await websocket.send_text(line)
                cursor = len(_log_buffer)
        except WebSocketDisconnect:
            pass

    # -------------------------------------------------------------------------
    # CV-Playground endpoints
    # -------------------------------------------------------------------------

    from cv_agent.agent import build_tools
    from cv_agent.pipeline.skill_registry import SkillRegistryAdapter
    from cv_agent.pipeline.storage import (
        list_pipelines as _list_pipelines,
        load_pipeline as _load_pipeline,
        save_pipeline as _save_pipeline,
    )
    from cv_agent.pipeline.models import PipelineGraph, BlockInstance, Edge, RunContext, RunStatus
    from cv_agent.pipeline.dag_runner import DAGRunner

    def _get_playground_tools() -> list:
        try:
            return build_tools(config)
        except Exception as exc:
            logger.warning("build_tools failed in playground: %s", exc)
            return []

    def _pipeline_storage_dir() -> str:
        return config.workflow.storage_dir

    def _make_tool_map(tools: list) -> dict:
        return {t.name: t for t in tools}

    @app.get("/api/playground/skills")
    async def playground_skills():
        """Return all available skill blocks derived from the live build_tools() registry."""
        tools = await asyncio.to_thread(_get_playground_tools)
        adapter = SkillRegistryAdapter(tools)
        return {"skills": [s.model_dump() for s in adapter.list_skills()]}

    # Active pipeline runs: run_id -> asyncio.Queue of WS events
    _pipeline_run_queues: dict[str, asyncio.Queue] = {}

    @app.websocket("/ws/workflows/{run_id}")
    async def ws_pipeline(websocket: WebSocket, run_id: str):
        """Stream pipeline execution events.  Also handles legacy Eko workflow streams."""
        await websocket.accept()
        queue = _pipeline_run_queues.get(run_id)
        if queue is None:
            # Legacy Eko path: proxy to Eko sidecar if configured
            try:
                wm = WorkflowManager(config)
                async for event in wm.stream_workflow_status(run_id):
                    await websocket.send_text(json.dumps(event))
            except Exception as exc:
                await websocket.send_text(json.dumps({"type": "error", "error": str(exc)}))
            finally:
                try:
                    await websocket.close()
                except Exception:
                    pass
            return

        # Pipeline run path: drain the queue
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    break
                if event is None:  # sentinel — run finished
                    break
                await websocket.send_text(json.dumps(event))
        except WebSocketDisconnect:
            pass
        finally:
            _pipeline_run_queues.pop(run_id, None)
            try:
                await websocket.close()
            except Exception:
                pass

    async def _execute_pipeline(run_id: str, pipeline: PipelineGraph, inputs: dict) -> None:
        """Background task: run DAG and push events to the WS queue."""
        queue = _pipeline_run_queues[run_id]
        tools = await asyncio.to_thread(_get_playground_tools)
        tool_map = _make_tool_map(tools)
        adapter = SkillRegistryAdapter(tools)

        async def _status_callback(node_id: str, status, message: str | None = None):
            event = {"type": "node_status", "run_id": run_id, "node_id": node_id,
                     "status": status.value, "timestamp": datetime.utcnow().isoformat()}
            await queue.put(event)
            if status.value == "done":
                pass  # output sent separately via node_output event
            elif status.value == "error":
                err_event = {"type": "node_error", "run_id": run_id, "node_id": node_id,
                             "block_name": node_id, "error": message or "",
                             "skipped": (message or "").startswith("Skipped"),
                             "timestamp": datetime.utcnow().isoformat()}
                await queue.put(err_event)

        # T033: build agent runner map so delegate_* blocks call async runners directly
        from cv_agent.agents.blog_writer import run_blog_writer_agent
        from cv_agent.agents.paper_to_code import run_paper_to_code_agent
        from cv_agent.agents.data_visualization import run_data_visualization_agent
        from cv_agent.agents.website_maintenance import run_website_maintenance_agent
        from cv_agent.agents.model_training import run_model_training_agent
        from cv_agent.agents.digest import run_digest_agent as run_digest_writer_agent
        _agent_runner_map = {
            "delegate_blog_writer": lambda msg: run_blog_writer_agent(msg),
            "delegate_paper_to_code": lambda msg: run_paper_to_code_agent(msg),
            "delegate_data_visualization": lambda msg: run_data_visualization_agent(msg),
            "delegate_website_maintenance": lambda msg: run_website_maintenance_agent(msg),
            "delegate_model_training": lambda msg: run_model_training_agent(msg),
            "delegate_digest_writer": lambda msg: run_digest_writer_agent(msg),
        }
        runner = DAGRunner(tool_map=tool_map, status_callback=_status_callback,
                           skill_registry=adapter, agent_runner_map=_agent_runner_map)
        try:
            node_outputs = await runner.run(pipeline, inputs)
            # Emit node_output for each completed node
            for node in pipeline.nodes:
                output = node_outputs.get(node.id)
                if output is not None:
                    block_name = node.skill_name.replace("__", "").replace("_", " ").title()
                    out_event = {"type": "node_output", "run_id": run_id, "node_id": node.id,
                                 "block_name": node.skill_name, "output": str(output),
                                 "timestamp": datetime.utcnow().isoformat()}
                    await queue.put(out_event)
            errored = sum(1 for v in node_outputs.values() if v is None)
            done_event = {"type": "pipeline_done", "run_id": run_id,
                          "status": "partial_error" if errored else "done",
                          "completed_nodes": len(node_outputs) - errored,
                          "errored_nodes": errored,
                          "timestamp": datetime.utcnow().isoformat()}
            await queue.put(done_event)
        except Exception as exc:
            await queue.put({"type": "pipeline_done", "run_id": run_id, "status": "error",
                             "completed_nodes": 0, "errored_nodes": len(pipeline.nodes),
                             "error": str(exc), "timestamp": datetime.utcnow().isoformat()})
        finally:
            await queue.put(None)  # sentinel

    @app.post("/api/pipelines/run")
    async def pipeline_run_adhoc(request: Request):
        """Ad-hoc pipeline run — full graph in body, no prior save required."""
        body = await request.json()
        inputs = body.pop("inputs", {})
        try:
            pipeline = PipelineGraph.model_validate(body)
        except Exception as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        run_id = str(uuid.uuid4())
        _pipeline_run_queues[run_id] = asyncio.Queue()
        asyncio.create_task(_execute_pipeline(run_id, pipeline, inputs))
        return {"run_id": run_id, "ws_url": f"/ws/workflows/{run_id}"}

    @app.post("/api/pipelines/{pipeline_id}/run")
    async def pipeline_run_saved(pipeline_id: str, request: Request):
        """Run a previously saved pipeline by ID."""
        body = await request.json()
        inputs = body.get("inputs", {})
        try:
            pipeline = await _load_pipeline(pipeline_id, _pipeline_storage_dir())
        except FileNotFoundError:
            return JSONResponse({"detail": "Pipeline not found."}, status_code=404)
        run_id = str(uuid.uuid4())
        _pipeline_run_queues[run_id] = asyncio.Queue()
        asyncio.create_task(_execute_pipeline(run_id, pipeline, inputs))
        return {"run_id": run_id, "ws_url": f"/ws/workflows/{run_id}"}

    @app.post("/api/pipelines")
    async def pipeline_save(request: Request):
        """Save (create or overwrite) a named pipeline."""
        body = await request.json()
        overwrite = body.pop("overwrite", False)
        try:
            graph = PipelineGraph.model_validate(body)
        except Exception as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        if not graph.name:
            return JSONResponse({"detail": "Pipeline name is required."}, status_code=422)
        try:
            file_path = await _save_pipeline(graph, _pipeline_storage_dir(), overwrite=overwrite)
            status = "overwritten" if overwrite else "created"
            return {"status": status, "id": file_path.stem, "name": graph.name,
                    "filename": file_path.name}
        except FileExistsError:
            return JSONResponse({
                "status": "conflict",
                "message": f"A pipeline named '{graph.name}' already exists.",
                "existing_id": __import__("re").sub(r"[^\w\s-]", "", graph.name.lower().replace(" ", "-"))
            }, status_code=409)

    @app.get("/api/pipelines")
    async def pipeline_list():
        """List all saved pipelines."""
        pipelines = await _list_pipelines(_pipeline_storage_dir())
        return {"pipelines": pipelines}

    @app.get("/api/pipelines/{pipeline_id}")
    async def pipeline_get(pipeline_id: str):
        """Load a saved pipeline by ID."""
        try:
            graph = await _load_pipeline(pipeline_id, _pipeline_storage_dir())
            return graph.model_dump(mode="json")
        except FileNotFoundError:
            return JSONResponse({"detail": "Pipeline not found."}, status_code=404)

    return app


# Module-level app instance for `uvicorn cv_agent.web:app --reload`
app = create_app()


def run_server(config: AgentConfig | None = None, host: str = "127.0.0.1", port: int = 8420):
    """Start the web UI server."""
    import uvicorn
    _app = create_app(config)
    print(f"\n  CV Zero Claw Agent UI → http://{host}:{port}\n")
    uvicorn.run(_app, host=host, port=port, log_level="info")
