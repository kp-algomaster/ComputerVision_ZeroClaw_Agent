"""Tests for configuration loading."""

from pathlib import Path

from cv_agent.config import AgentConfig, load_config


def test_default_config():
    """Default config loads without errors."""
    cfg = AgentConfig()
    assert cfg.name == "CV Research Agent"
    assert cfg.vision.ollama.default_model == "qwen2.5-vl:7b"
    assert cfg.llm.provider == "ollama"
    assert cfg.text_to_diagram.default_iterations == 2


def test_load_config_from_yaml(tmp_path: Path):
    """Config loads from a YAML file."""
    yaml_content = """
agent:
  name: "Test Agent"
  log_level: DEBUG
vision:
  ollama:
    default_model: "llava:13b"
llm:
  model: "qwen2.5:14b"
text_to_diagram:
  default_iterations: 4
"""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml_content)

    cfg = load_config(config_file)
    assert cfg.name == "Test Agent"
    assert cfg.log_level == "DEBUG"
    assert cfg.vision.ollama.default_model == "llava:13b"
    assert cfg.llm.model == "qwen2.5:14b"
    assert cfg.text_to_diagram.default_iterations == 4


def test_load_config_missing_file():
    """Missing config file falls back to defaults."""
    cfg = load_config("/nonexistent/path/config.yaml")
    assert cfg.name == "CV Research Agent"
