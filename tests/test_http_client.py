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
