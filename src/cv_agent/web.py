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
        skill_ready = [
            True, True, _has("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"),
            True, has_3d, has_video, True, True, True,
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


def run_server(config: AgentConfig | None = None, host: str = "127.0.0.1", port: int = 8420):
    """Start the web UI server."""
    import uvicorn
    app = create_app(config)
    print(f"\n  CV Zero Claw Agent UI → http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
