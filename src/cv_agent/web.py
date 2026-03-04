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

import markdown
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cv_agent.config import AgentConfig, load_config

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def create_app(config: AgentConfig | None = None) -> FastAPI:
    """Create the FastAPI application."""
    if config is None:
        config = load_config()

    app = FastAPI(title="CV Zero Claw Agent", version="0.1.0")

    output_dir = _PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/output", StaticFiles(directory=output_dir), name="output")
    app.state.diagram_jobs = {}

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

                if not user_text.strip():
                    continue

                # Send typing indicator
                await websocket.send_text(json.dumps({"type": "typing", "status": True}))

                try:
                    from cv_agent.agent import run_agent_stream

                    # Signal stream start so client creates the message bubble
                    await websocket.send_text(json.dumps({
                        "type": "stream_start",
                        "role": "assistant",
                    }))

                    final_content = ""
                    async for event in run_agent_stream(user_text, config, history):
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
        import httpx as _hx
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

    @app.delete("/api/models/{name:path}")
    async def delete_model(name: str):
        """Delete a pulled model from Ollama."""
        import httpx as _httpx
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
            import httpx as _httpx
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
                "acceleration": hw.acceleration,
            } if hw else None,
            "recommended": [
                {
                    "name": m.name,
                    "provider": m.provider,
                    "fit": m.fit,
                    "quantization": m.quantization,
                    "score": round(m.composite_score, 1),
                    "vram_gb": round(m.vram_gb, 1),
                }
                for m in recs
            ],
        })

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
        """Update credentials for a power. Persists to .env."""
        fields: dict = body.get("fields", {})
        updates: dict[str, str] = {}
        for key, value in fields.items():
            v = str(value) if value is not None else ""
            if v and not v.startswith("••"):
                os.environ[key] = v
                updates[key] = v
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

        skills = {
            "research_blog": {
                "label": "Write Research Blog", "icon": "✍️", "category": "content",
                "description": "Generate weekly digest posts, paper summaries, and deep-dive articles on CV breakthroughs.",
                "status": "ready",
                "tools": ["search_arxiv", "web_search", "file_write"],
                "missing": [],
            },
            "weekly_digest": {
                "label": "Weekly Digest", "icon": "📰", "category": "content",
                "description": "Curated weekly magazine of CV breakthroughs — auto-pulled from ArXiv and web, formatted as Markdown.",
                "status": "ready",
                "tools": ["search_arxiv", "web_search", "file_write"],
                "missing": [],
            },
            "email_reports": {
                "label": "Email Reports", "icon": "📧", "category": "content",
                "description": "Send automated digest emails and paper alerts to a recipient list.",
                "status": "ready" if has_email else "needs-power",
                "tools": [],
                "missing": [] if has_email else ["Email power"],
            },
            "2d_image_processing": {
                "label": "2D Image Processing", "icon": "🖼️", "category": "vision",
                "description": "Analyse, describe, and compare 2D images using VLMs (Qwen2.5-VL, LLaVA) and MLX vision models.",
                "status": "ready",
                "tools": ["analyze_image", "describe_image", "compare_images", "pull_vision_model"],
                "missing": [],
            },
            "3d_image_processing": {
                "label": "3D Image Processing", "icon": "🧊", "category": "vision",
                "description": "Process point clouds, depth maps, mesh data, and NeRF outputs using Open3D or Trimesh.",
                "status": "ready" if has_3d else "needs-install",
                "tools": ["shell", "file_read"],
                "missing": [] if has_3d else ["open3d or trimesh"],
                "install": None if has_3d else "pip install open3d",
            },
            "video_understanding": {
                "label": "Video Understanding", "icon": "🎥", "category": "vision",
                "description": "Analyse video streams, extract key frames, and understand temporal patterns in CV datasets.",
                "status": "ready" if has_video else "needs-install",
                "tools": ["analyze_image", "shell"],
                "missing": [] if has_video else ["opencv-python or decord"],
                "install": None if has_video else "pip install opencv-python",
            },
            "paper_to_spec": {
                "label": "Paper → Spec", "icon": "📋", "category": "research",
                "description": "Convert papers to spec.md files with equations, architecture diagrams, and implementation requirements.",
                "status": "ready",
                "tools": ["fetch_arxiv_paper", "extract_equations", "generate_spec"],
                "missing": [],
            },
            "knowledge_graph": {
                "label": "Knowledge Graph", "icon": "🕸️", "category": "research",
                "description": "Build and query Obsidian-compatible vaults linking papers, methods, datasets, and concepts.",
                "status": "ready",
                "tools": ["add_paper_to_graph", "query_graph", "export_graph"],
                "missing": [],
            },
            "equation_extraction": {
                "label": "Equation Extraction", "icon": "∑", "category": "research",
                "description": "Extract LaTeX equations, loss functions, and mathematical formulations from PDF papers.",
                "status": "ready",
                "tools": ["extract_equations", "extract_key_info"],
                "missing": [],
            },
            "text_to_diagram": {
                "label": "Text → Diagram", "icon": "🧭", "category": "research",
                "description": "Paste or write text and generate diagrams via Paperbanana (Ollama + matplotlib).",
                "status": "ready" if has_paperbanana else "needs-install",
                "tools": ["text_to_diagram"],
                "missing": [] if has_paperbanana else ["paperbanana"],
                "install": None if has_paperbanana else "pip install -e /tmp/paperbanana",
            },
            "kaggle_competition": {
                "label": "Kaggle Competition", "icon": "🏆", "category": "ml",
                "description": "Analyse tasks, download datasets, build baselines, and submit competition predictions.",
                "status": "ready" if has_kaggle else "needs-power",
                "tools": ["web_search", "shell", "file_read", "file_write"],
                "missing": [] if has_kaggle else ["Kaggle power"],
            },
            "model_fine_tuning": {
                "label": "Model Fine-Tuning", "icon": "🎯", "category": "ml",
                "description": "Fine-tune vision models with HuggingFace Trainer locally or on Azure ML compute clusters.",
                "status": "ready" if (has_hf or has_azure) else "needs-power",
                "tools": ["shell", "file_read", "file_write"],
                "missing": ([] if has_hf else ["HuggingFace power"]) + ([] if has_azure else ["Azure ML power"]),
            },
            "dataset_analysis": {
                "label": "Dataset Analysis", "icon": "📊", "category": "ml",
                "description": "Profile CV datasets, compute statistics, visualise class distributions and annotation quality.",
                "status": "ready",
                "tools": ["shell", "file_read", "analyze_image"],
                "missing": [],
            },
        }
        return JSONResponse(skills)

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
        ]
        return JSONResponse({"jobs": jobs})

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

    return app


# Module-level app instance for `uvicorn cv_agent.web:app --reload`
app = create_app()


def run_server(config: AgentConfig | None = None, host: str = "127.0.0.1", port: int = 8420):
    """Start the web UI server."""
    import uvicorn
    _app = create_app(config)
    print(f"\n  CV Zero Claw Agent UI → http://{host}:{port}\n")
    uvicorn.run(_app, host=host, port=port, log_level="info")
