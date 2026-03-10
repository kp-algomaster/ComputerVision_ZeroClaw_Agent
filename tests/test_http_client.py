import sys
import types

from cv_agent import http_client
from cv_agent.http_client import build_httpx_kwargs, httpx_verify


def test_httpx_verify_defaults_to_false(monkeypatch):
    monkeypatch.delenv("CV_SSL_VERIFY", raising=False)

    assert httpx_verify() is False
    assert build_httpx_kwargs(timeout=5)["verify"] is False


def test_httpx_verify_supports_true(monkeypatch):
    monkeypatch.setenv("CV_SSL_VERIFY", "true")

    assert httpx_verify() is True
    assert build_httpx_kwargs(timeout=5)["verify"] is True


def test_httpx_verify_supports_custom_ca_bundle_path(monkeypatch):
    monkeypatch.setenv("CV_SSL_VERIFY", "/tmp/custom-ca.pem")

    assert httpx_verify() == "/tmp/custom-ca.pem"
    assert build_httpx_kwargs(timeout=5)["verify"] == "/tmp/custom-ca.pem"


def test_configure_huggingface_hub_registers_shared_client_factories(monkeypatch):
    sync_holder: dict[str, object] = {}
    async_holder: dict[str, object] = {}
    sync_kwargs: dict[str, object] = {}
    async_kwargs: dict[str, object] = {}

    fake_hf = types.ModuleType("huggingface_hub")
    fake_hf.set_client_factory = lambda factory: sync_holder.setdefault("factory", factory)
    fake_hf.set_async_client_factory = lambda factory: async_holder.setdefault("factory", factory)

    fake_hf_http = types.ModuleType("huggingface_hub.utils._http")

    def hf_request_event_hook(request):
        return request

    async def async_hf_request_event_hook(request):
        return request

    async def async_hf_response_event_hook(response):
        return response

    fake_hf_http.hf_request_event_hook = hf_request_event_hook
    fake_hf_http.async_hf_request_event_hook = async_hf_request_event_hook
    fake_hf_http.async_hf_response_event_hook = async_hf_response_event_hook

    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)
    monkeypatch.setitem(sys.modules, "huggingface_hub.utils._http", fake_hf_http)
    monkeypatch.setattr(http_client, "_huggingface_hub_configured", False)
    monkeypatch.setattr(
        http_client,
        "create_httpx_client",
        lambda **kwargs: sync_kwargs.setdefault("kwargs", kwargs) or "sync-client",
    )
    monkeypatch.setattr(
        http_client,
        "create_async_httpx_client",
        lambda **kwargs: async_kwargs.setdefault("kwargs", kwargs) or "async-client",
    )

    assert http_client.configure_huggingface_hub() is True

    sync_factory = sync_holder["factory"]
    async_factory = async_holder["factory"]

    sync_factory()
    async_factory()

    assert sync_kwargs["kwargs"]["follow_redirects"] is True
    assert sync_kwargs["kwargs"]["timeout"] is None
    assert sync_kwargs["kwargs"]["event_hooks"]["request"] == [hf_request_event_hook]
    assert async_kwargs["kwargs"]["follow_redirects"] is True
    assert async_kwargs["kwargs"]["timeout"] is None
    assert async_kwargs["kwargs"]["event_hooks"]["request"] == [async_hf_request_event_hook]
    assert async_kwargs["kwargs"]["event_hooks"]["response"] == [async_hf_response_event_hook]
