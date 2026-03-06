from cv_agent.web import _is_chat_model_compatible, _select_default_chat_model


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
