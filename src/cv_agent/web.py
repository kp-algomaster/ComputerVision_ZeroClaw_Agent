"""Web UI server — FastAPI backend with chat and content viewer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
                    from cv_agent.agent import run_agent
                    response = await run_agent(user_text, config, history)

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

    return app


def run_server(config: AgentConfig | None = None, host: str = "127.0.0.1", port: int = 8420):
    """Start the web UI server."""
    import uvicorn
    app = create_app(config)
    print(f"\n  CV Zero Claw Agent UI → http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
