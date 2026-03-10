"""Shared outbound HTTP helpers with a repo-wide SSL verification policy."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx as _httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

_FALSEY = {"0", "false", "no", "off"}
_TRUEY = {"1", "true", "yes", "on"}
_warned_ssl_disabled = False
_huggingface_hub_configured = False


def _log_ssl_policy(verify: bool | str) -> None:
    global _warned_ssl_disabled
    if verify is False and not _warned_ssl_disabled:
        logger.warning(
            "Outbound SSL certificate verification is disabled via CV_SSL_VERIFY. "
            "Set CV_SSL_VERIFY=true to re-enable validation."
        )
        _warned_ssl_disabled = True


def httpx_verify() -> bool | str:
    """Return the active SSL verification policy for outbound HTTP(S) requests.

    `CV_SSL_VERIFY` supports:
    - `false` / `0` / `off`: disable certificate verification
    - `true` / `1` / `on`: enable certificate verification
    - any other non-empty string: treat as a CA bundle path

    The default is `true` for security. Set to `false` if behind self-signed
    corporate or local proxy CAs.
    """
    raw = os.environ.get("CV_SSL_VERIFY", "true").strip()
    if not raw:
        verify: bool | str = True
    else:
        normalized = raw.lower()
        if normalized in _TRUEY:
            verify = True
        elif normalized in _FALSEY:
            verify = False
        else:
            verify = raw

    _log_ssl_policy(verify)
    return verify


def build_httpx_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Inject the repo-wide SSL policy unless the caller overrides it explicitly."""
    kwargs.setdefault("verify", httpx_verify())
    return kwargs


def create_httpx_client(**kwargs: Any) -> _httpx.Client:
    """Create a synchronous httpx client using the shared SSL policy."""
    return _httpx.Client(**build_httpx_kwargs(**kwargs))


def create_async_httpx_client(**kwargs: Any) -> _httpx.AsyncClient:
    """Create an async httpx client using the shared SSL policy."""
    return _httpx.AsyncClient(**build_httpx_kwargs(**kwargs))


def configure_huggingface_hub() -> bool:
    """Register shared SSL-aware HTTP clients for huggingface_hub.

    The Hub client uses its own global httpx clients, so this opt-in bridge keeps
    Hugging Face dataset/model downloads aligned with `CV_SSL_VERIFY`.
    """
    global _huggingface_hub_configured

    if _huggingface_hub_configured:
        return True

    try:
        from huggingface_hub import set_async_client_factory, set_client_factory
    except ImportError:
        return False

    try:
        from huggingface_hub.utils._http import (
            async_hf_request_event_hook,
            async_hf_response_event_hook,
            hf_request_event_hook,
        )
        sync_event_hooks: dict[str, list[Any]] = {"request": [hf_request_event_hook]}
        async_event_hooks: dict[str, list[Any]] = {
            "request": [async_hf_request_event_hook],
            "response": [async_hf_response_event_hook],
        }
    except Exception:
        sync_event_hooks = {}
        async_event_hooks = {}

    def _sync_factory() -> _httpx.Client:
        return create_httpx_client(
            event_hooks=sync_event_hooks,
            follow_redirects=True,
            timeout=None,
        )

    def _async_factory() -> _httpx.AsyncClient:
        return create_async_httpx_client(
            event_hooks=async_event_hooks,
            follow_redirects=True,
            timeout=None,
        )

    set_client_factory(_sync_factory)
    set_async_client_factory(_async_factory)
    _huggingface_hub_configured = True
    return True


class _HttpxProxy:
    """Small proxy that preserves the `httpx` API while injecting SSL settings."""

    def __getattr__(self, name: str) -> Any:
        if name == "Client":
            return self.client
        if name == "AsyncClient":
            return self.async_client
        return getattr(_httpx, name)

    def client(self, *args: Any, **kwargs: Any) -> _httpx.Client:
        return _httpx.Client(*args, **build_httpx_kwargs(**kwargs))

    def async_client(self, *args: Any, **kwargs: Any) -> _httpx.AsyncClient:
        return _httpx.AsyncClient(*args, **build_httpx_kwargs(**kwargs))

    def request(self, method: str, url: str, *args: Any, **kwargs: Any) -> _httpx.Response:
        return _httpx.request(method, url, *args, **build_httpx_kwargs(**kwargs))

    def get(self, url: str, *args: Any, **kwargs: Any) -> _httpx.Response:
        return _httpx.get(url, *args, **build_httpx_kwargs(**kwargs))

    def post(self, url: str, *args: Any, **kwargs: Any) -> _httpx.Response:
        return _httpx.post(url, *args, **build_httpx_kwargs(**kwargs))

    def put(self, url: str, *args: Any, **kwargs: Any) -> _httpx.Response:
        return _httpx.put(url, *args, **build_httpx_kwargs(**kwargs))

    def patch(self, url: str, *args: Any, **kwargs: Any) -> _httpx.Response:
        return _httpx.patch(url, *args, **build_httpx_kwargs(**kwargs))

    def delete(self, url: str, *args: Any, **kwargs: Any) -> _httpx.Response:
        return _httpx.delete(url, *args, **build_httpx_kwargs(**kwargs))


httpx = _HttpxProxy()

__all__ = [
    "httpx",
    "httpx_verify",
    "build_httpx_kwargs",
    "create_httpx_client",
    "create_async_httpx_client",
    "configure_huggingface_hub",
]
