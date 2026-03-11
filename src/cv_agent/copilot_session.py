"""GitHub Copilot SDK session manager and streaming bridge."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy SDK imports — only resolved when Copilot is actually enabled.
# ---------------------------------------------------------------------------

try:
    from copilot import (  # type: ignore[import-untyped]
        CopilotClient,
        CopilotSession,
        PermissionHandler,
        StopError,
    )
    from copilot.generated.session_events import SessionEventType  # type: ignore[import-untyped]
    from copilot.types import CopilotClientOptions, ToolResult  # type: ignore[import-untyped]

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    CopilotClient = None  # type: ignore[assignment,misc]
    CopilotSession = None  # type: ignore[assignment,misc]
    PermissionHandler = None  # type: ignore[assignment,misc]
    StopError = Exception  # type: ignore[assignment,misc]
    SessionEventType = None  # type: ignore[assignment]
    CopilotClientOptions = None  # type: ignore[assignment]
    ToolResult = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


class ModelOption(TypedDict):
    id: str
    name: str
    has_vision: bool
    max_tokens: int
    is_default: bool


@dataclass
class CopilotSessionState:
    session: Any  # CopilotSession at runtime
    session_id: str
    model_id: str
    turn_count: int = 0
    is_running: bool = False
    created_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Streaming bridge
# ---------------------------------------------------------------------------


class CopilotStreamBridge:
    """Bridges Copilot SDK session events to the existing WS event dict format."""

    @staticmethod
    async def stream(
        session: Any,
        prompt: str,
        timeout: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator yielding WS-compatible event dicts from a Copilot turn."""
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        _last_content: list[str] = [""]  # mutable cell for handler closure

        def _handle_event(event: Any) -> None:  # noqa: ANN401
            try:
                etype = event.type
                data = event.data

                if etype in (
                    SessionEventType.ASSISTANT_STREAMING_DELTA,
                    SessionEventType.ASSISTANT_MESSAGE_DELTA,
                ):
                    chunk = getattr(data, "delta_content", None) or ""
                    if chunk:
                        queue.put_nowait({"type": "stream_token", "content": chunk})

                elif etype == SessionEventType.ASSISTANT_REASONING_DELTA:
                    chunk = getattr(data, "delta_content", None) or ""
                    if chunk:
                        queue.put_nowait({"type": "stream_token", "content": chunk})

                elif etype == SessionEventType.ASSISTANT_MESSAGE:
                    content = getattr(data, "content", None) or ""
                    if content:
                        _last_content[0] = content

                elif etype == SessionEventType.TOOL_EXECUTION_START:
                    name = getattr(data, "tool_name", None) or "unknown"
                    args = getattr(data, "arguments", None) or {}
                    queue.put_nowait({"type": "tool_start", "name": name, "input": str(args)[:500]})

                elif etype == SessionEventType.TOOL_EXECUTION_COMPLETE:
                    name = getattr(data, "tool_name", None) or "unknown"
                    output = (
                        getattr(data, "partial_output", None)
                        or str(getattr(data, "result", None) or "")
                    )
                    queue.put_nowait({"type": "tool_end", "name": name, "output": output[:500]})

                elif etype == SessionEventType.SESSION_ERROR:
                    msg = getattr(data, "message", None) or str(getattr(data, "error", "unknown error"))
                    queue.put_nowait({"type": "error", "message": msg})

            except Exception:
                logger.debug("Error in Copilot event handler", exc_info=True)

        unsubscribe = session.on(_handle_event)
        send_task: asyncio.Task[Any] = asyncio.create_task(
            session.send_and_wait({"prompt": prompt}, timeout=float(timeout))
        )

        try:
            while not send_task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                    yield event
                except asyncio.TimeoutError:
                    continue

            # Drain remaining queued events before final
            while not queue.empty():
                try:
                    yield queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            result_event = await send_task
            final = _last_content[0]
            if not final and result_event is not None:
                final = getattr(getattr(result_event, "data", None), "content", None) or ""
            yield {"type": "stream_end", "content": final}

        except StopError:
            send_task.cancel()
            yield {"type": "cancelled"}

        except asyncio.TimeoutError:
            send_task.cancel()
            yield {
                "type": "error",
                "message": (
                    "The request timed out waiting for the model to finish. "
                    "Agentic tasks with many tool calls can take a long time — "
                    "increase `copilot.session_timeout_s` in agent_config.yaml (current default: 600s)."
                ),
            }

        except Exception as exc:
            send_task.cancel()
            msg = str(exc)
            if "waiting for session.idle" in msg or "Timeout after" in msg:
                yield {
                    "type": "error",
                    "message": (
                        f"Session idle timeout ({timeout}s). "
                        "The agentic run used too many tool calls. "
                        "Increase `copilot.session_timeout_s` in agent_config.yaml."
                    ),
                }
            else:
                logger.exception("Copilot stream error")
                yield {"type": "error", "message": msg}

        finally:
            try:
                unsubscribe()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class CopilotManager:
    """Process-level singleton managing CopilotClient lifecycle and sessions."""

    def __init__(self) -> None:
        self._client: Any = None
        self._connected: bool = False
        self._config: Any = None  # AgentConfig at runtime
        self._sessions: dict[str, CopilotSessionState] = {}
        self._models_cache: list[ModelOption] = []
        self._models_cache_time: float = 0.0
        self._state_listeners: list[Any] = []  # websockets subscribed to status events

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self, config: Any) -> None:  # noqa: ANN401
        """Start the CopilotClient. Logs a warning and disables on failure."""
        self._config = config
        if not config.copilot.enabled:
            return
        if not _SDK_AVAILABLE:
            logger.warning("github-copilot-sdk not installed — Copilot integration disabled")
            return

        options: dict[str, Any] = {}
        if config.copilot.github_token:
            options["github_token"] = config.copilot.github_token
        if config.copilot.cli_path:
            options["cli_path"] = config.copilot.cli_path
        if config.copilot.cli_url:
            options["cli_url"] = config.copilot.cli_url

        try:
            self._client = CopilotClient(options or None)
            await self._client.start()
            self._connected = self._client.get_state() == "connected"
            if self._connected:
                logger.info("Copilot SDK connected (state=%s)", self._client.get_state())
            else:
                logger.warning(
                    "Copilot SDK started but state=%s — falling back to LangGraph backend",
                    self._client.get_state(),
                )
        except Exception as exc:
            logger.warning(
                "Copilot SDK unavailable (%s) — falling back to LangGraph backend", exc
            )
            self._connected = False
            self._client = None

    async def stop(self) -> None:
        """Stop all sessions and the client gracefully."""
        for state in list(self._sessions.values()):
            try:
                await state.session.disconnect()
            except Exception:
                pass
        self._sessions.clear()

        if self._client is not None:
            try:
                await self._client.stop()
            except Exception:
                pass
            self._client = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    # ── Session management ─────────────────────────────────────────────────

    async def get_or_create_session(
        self, ws_id: str, model_id: str = "", skills: list[Any] | None = None
    ) -> CopilotSessionState:
        """Return the existing session for this WS connection or create a new one.

        On first call for a given ws_id, builds Copilot skills from all registered
        LangChain tools via build_copilot_skills() and creates a new CopilotSession.
        Subsequent calls reuse the same session for multi-turn context retention.
        """
        if ws_id in self._sessions:
            state = self._sessions[ws_id]
            state.turn_count += 1
            return state

        # Build skills from all registered CV tools (T021)
        if skills is None and self._config is not None:
            try:
                from cv_agent.agent import build_tools
                from cv_agent.tools.copilot_skills import build_copilot_skills

                skills = build_copilot_skills(build_tools(self._config))
            except Exception as exc:
                logger.warning("Could not build Copilot skills: %s", exc)
                skills = []

        session_cfg: dict[str, Any] = {
            "on_permission_request": PermissionHandler.approve_all,
            "streaming": True,
        }
        effective_model = model_id or (self._config.copilot.default_model if self._config else "")
        if effective_model:
            session_cfg["model"] = effective_model
        if self._config and self._config.copilot.byok_provider:
            session_cfg["provider"] = self._config.copilot.byok_provider
        if skills:
            session_cfg["tools"] = skills

        session = await self._client.create_session(session_cfg)
        try:
            session_id = await self._client.get_last_session_id()
        except Exception:
            session_id = str(id(session))

        state = CopilotSessionState(
            session=session,
            session_id=session_id,
            model_id=effective_model,
            turn_count=1,
        )
        self._sessions[ws_id] = state
        return state

    async def close_session(self, ws_id: str) -> None:
        """Disconnect and remove session for a WebSocket connection."""
        state = self._sessions.pop(ws_id, None)
        if state is not None:
            try:
                await state.session.disconnect()
            except Exception:
                pass

    def abort_session(self, ws_id: str) -> None:
        """Synchronously abort an in-flight task (safe to call from async context)."""
        state = self._sessions.get(ws_id)
        if state and state.is_running:
            try:
                state.session.abort()
            except Exception:
                pass

    # ── Model enumeration ──────────────────────────────────────────────────

    async def list_models(self, default_model_id: str = "") -> list[ModelOption]:
        """Return available Copilot models, cached for 5 minutes."""
        if not self.is_connected():
            return []

        now = time.monotonic()
        if self._models_cache and (now - self._models_cache_time) < 300:
            return self._models_cache

        try:
            raw = await self._client.list_models()
            options: list[ModelOption] = []
            for m in raw:
                caps = getattr(m, "capabilities", None)
                supports = getattr(caps, "supports", None)
                limits = getattr(caps, "limits", None)
                has_vision = bool(getattr(supports, "vision", False)) if supports else False
                max_tokens = int(getattr(limits, "max_output_tokens", 0) or 0) if limits else 0
                options.append(
                    ModelOption(
                        id=m.id,
                        name=m.name,
                        has_vision=has_vision,
                        max_tokens=max_tokens,
                        is_default=(m.id == default_model_id),
                    )
                )
            self._models_cache = options
            self._models_cache_time = now
            return options
        except Exception as exc:
            logger.warning("Failed to enumerate Copilot models: %s", exc)
            return []

    # ── Status ─────────────────────────────────────────────────────────────

    async def get_status(self) -> dict[str, Any]:
        """Return SDK health dict for /api/copilot/status."""
        sdk_state = self._client.get_state() if self._client else "disconnected"
        auth_ok = False
        byok_mode = bool(self._config and self._config.copilot.byok_provider) if self._config else False

        if self._client and self.is_connected():
            try:
                auth_resp = await self._client.get_auth_status()
                auth_ok = bool(getattr(auth_resp, "authenticated", False))
            except Exception:
                pass

        return {
            "connected": self.is_connected(),
            "auth_ok": auth_ok,
            "sdk_state": sdk_state,
            "byok_mode": byok_mode,
            "active_sessions": len(self._sessions),
        }

    def register_state_listener(self, ws: Any) -> None:
        self._state_listeners.append(ws)

    def unregister_state_listener(self, ws: Any) -> None:
        self._state_listeners.discard(ws) if hasattr(self._state_listeners, "discard") else None
        if ws in self._state_listeners:
            self._state_listeners.remove(ws)


# Module-level singleton
copilot_manager = CopilotManager()
