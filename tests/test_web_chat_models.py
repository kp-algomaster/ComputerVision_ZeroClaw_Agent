from fastapi.testclient import TestClient

import cv_agent.web as web
from cv_agent.config import load_config
from cv_agent.web import _is_chat_model_compatible, _select_default_chat_model


def _sam3_runtime_status(**overrides):
    status = {
        "has_sam3_pkg": False,
        "has_sam3_model": False,
        "sam3_ready": False,
        "has_mlx_pkg": False,
        "has_mlx_src": False,
        "has_sam3_mlx_model": False,
        "sam3_mlx_ready": False,
        "has_any_model": False,
        "ready": False,
        "available_models": [],
    }
    status.update(overrides)
    return status


def test_chat_model_compatibility_accepts_completion_models():
    assert _is_chat_model_compatible("qwen3.5:9b", ["completion", "tools", "thinking"])


def test_chat_model_compatibility_rejects_embedding_models():
    assert not _is_chat_model_compatible("nomic-embed-text:latest", ["completion"])


def test_select_default_chat_model_prefers_requested_then_configured_then_first():
    models = ["qwen3.5:9b", "gpt-oss:20b"]

    assert _select_default_chat_model(models, "missing:model", "gpt-oss:20b") == "gpt-oss:20b"
    assert _select_default_chat_model(models, "qwen3.5:9b", "missing:model") == "qwen3.5:9b"
    assert _select_default_chat_model(models, "missing:model") == "qwen3.5:9b"
    assert _select_default_chat_model([], "missing:model") == ""


def test_configure_power_creates_env_and_persists_hf_token(monkeypatch, tmp_path):
    persisted: dict[str, str] = {}

    monkeypatch.setattr(web, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        web,
        "_persist_huggingface_token",
        lambda token: persisted.setdefault("token", token) or True,
    )
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)

    client = TestClient(web.create_app(load_config()))
    response = client.post(
        "/api/powers/huggingface/configure",
        json={"fields": {"HF_TOKEN": "hf_test_token"}},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "updated": ["HF_TOKEN"]}
    assert (tmp_path / ".env").read_text() == "HF_TOKEN=hf_test_token\n"
    assert persisted["token"] == "hf_test_token"
    assert web.os.environ["HF_TOKEN"] == "hf_test_token"
    assert web.os.environ["HUGGING_FACE_HUB_TOKEN"] == "hf_test_token"


def test_list_skills_treats_sam3_mlx_as_sufficient(monkeypatch):
    monkeypatch.setattr("cv_agent.local_model_manager.is_model_downloaded", lambda _model_id: False)
    monkeypatch.setattr(
        "cv_agent.tools.segment_anything.get_sam3_runtime_status",
        lambda: _sam3_runtime_status(
            has_mlx_pkg=True,
            has_mlx_src=True,
            has_sam3_mlx_model=True,
            sam3_mlx_ready=True,
            has_any_model=True,
            ready=True,
            available_models=[
                {"id": "sam3-mlx", "label": "SAM 3 MLX (Apple Silicon)", "ready": True, "needs": []}
            ],
        ),
    )

    client = TestClient(web.create_app(load_config()))
    response = client.get("/api/skills")

    assert response.status_code == 200
    skill = response.json()["segment_anything"]
    assert skill["status"] == "ready"
    assert skill["missing"] == []
    assert skill["models"] == []


def test_list_skills_does_not_require_pytorch_weights_when_sam3_mlx_downloaded(monkeypatch):
    monkeypatch.setattr("cv_agent.local_model_manager.is_model_downloaded", lambda _model_id: False)
    monkeypatch.setattr(
        "cv_agent.tools.segment_anything.get_sam3_runtime_status",
        lambda: _sam3_runtime_status(
            has_sam3_mlx_model=True,
            has_any_model=True,
            ready=False,
            available_models=[
                {
                    "id": "sam3-mlx",
                    "label": "SAM 3 MLX (Apple Silicon)",
                    "ready": False,
                    "needs": ["mlx package (pip install mlx)", "mlx_sam3 source"],
                }
            ],
        ),
    )

    client = TestClient(web.create_app(load_config()))
    response = client.get("/api/skills")

    assert response.status_code == 200
    skill = response.json()["segment_anything"]
    assert skill["status"] == "needs-install"
    assert skill["models"] == []
    assert "sam3 package" not in skill["missing"]
    assert "SAM 3 or SAM 3 MLX model weights" not in skill["missing"]
    assert "mlx package" in skill["missing"]
    assert "mlx_sam3 source" in skill["missing"]


def test_sam3_status_is_ready_with_mlx_only_backend(monkeypatch):
    monkeypatch.setattr(
        "cv_agent.tools.segment_anything.get_sam3_runtime_status",
        lambda: _sam3_runtime_status(
            has_mlx_pkg=True,
            has_mlx_src=True,
            has_sam3_mlx_model=True,
            sam3_mlx_ready=True,
            has_any_model=True,
            ready=True,
            available_models=[
                {"id": "sam3-mlx", "label": "SAM 3 MLX (Apple Silicon)", "ready": True, "needs": []}
            ],
        ),
    )

    client = TestClient(web.create_app(load_config()))
    response = client.get("/api/sam3/status")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["has_model"] is True
    assert response.json()["message"] == "SAM3 ready"
