"""Configuration loader for CV Agent."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class OllamaConfig(BaseModel):
    host: str = "http://localhost:11434"
    default_model: str = "qwen2.5-vl:7b"
    models: list[str] = Field(default_factory=lambda: ["qwen2.5-vl:7b"])
    timeout: int = 120
    max_tokens: int = 4096


class MLXConfig(BaseModel):
    enabled: bool = True
    models: list[str] = Field(default_factory=list)
    cache_dir: str = "~/.cache/mlx-cv-agent"


class VisionConfig(BaseModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    mlx: MLXConfig = Field(default_factory=MLXConfig)


class LLMConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen2.5:7b"
    api_key: str = ""
    base_url: str = "http://localhost:11434/v1"
    temperature: float = 0.3
    max_tokens: int = 8192


class LlmfitConfig(BaseModel):
    enabled: bool = True
    auto_select_model: bool = True   # update llm.model / vision model at startup if a better fit is found
    min_fit: str = "good"            # minimum fit quality: perfect | good | marginal
    vision_use_case: str = "multimodal"
    general_use_case: str = "general"


class ArxivSourceConfig(BaseModel):
    enabled: bool = True
    categories: list[str] = Field(default_factory=lambda: ["cs.CV", "cs.AI", "cs.LG"])
    max_results_per_query: int = 50
    queries: list[str] = Field(default_factory=list)


class PapersWithCodeConfig(BaseModel):
    enabled: bool = True
    areas: list[str] = Field(default_factory=lambda: ["computer-vision"])


class SemanticScholarConfig(BaseModel):
    enabled: bool = True
    api_key: str = ""
    fields_of_study: list[str] = Field(default_factory=lambda: ["Computer Science"])
    min_citation_count: int = 5


class ResearchSourcesConfig(BaseModel):
    arxiv: ArxivSourceConfig = Field(default_factory=ArxivSourceConfig)
    papers_with_code: PapersWithCodeConfig = Field(default_factory=PapersWithCodeConfig)
    semantic_scholar: SemanticScholarConfig = Field(default_factory=SemanticScholarConfig)


class ResearchConfig(BaseModel):
    sources: ResearchSourcesConfig = Field(default_factory=ResearchSourcesConfig)
    check_interval_hours: int = 12
    digest_day: str = "Monday"


class KnowledgeConfig(BaseModel):
    vault_path: str = "./vault"
    vault_name: str = "CV_Research"
    entity_types: list[str] = Field(
        default_factory=lambda: [
            "paper", "method", "dataset", "architecture",
            "loss_function", "metric", "task", "author", "institution",
        ]
    )
    link_types: list[str] = Field(
        default_factory=lambda: [
            "proposes", "uses", "extends", "evaluates_on",
            "outperforms", "cites", "authored_by",
        ]
    )


class SpecConfig(BaseModel):
    output_dir: str = "./output/specs"
    template: str = "templates/spec.md.j2"


class TextToDiagramConfig(BaseModel):
    enabled: bool = True
    vlm_provider: str = "ollama"
    image_provider: str = "matplotlib"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_vlm_model: str = "qwen2.5-vl:7b"
    ollama_code_model: str = "qwen2.5-coder:latest"
    default_iterations: int = 2
    output_dir: str = "./output/diagrams"
    default_diagram_type: str = "methodology"


class OutputConfig(BaseModel):
    base_dir: str = "./output"
    digests_dir: str = "./output/digests"
    format: str = "markdown"


class TelegramConfig(BaseModel):
    enabled: bool = Field(default_factory=lambda: os.environ.get("TELEGRAM_ENABLED", "false").lower() == "true")
    bot_token: str = Field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    chat_id: str = Field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))


class WhatsAppConfig(BaseModel):
    enabled: bool = Field(default_factory=lambda: os.environ.get("WHATSAPP_ENABLED", "false").lower() == "true")
    access_token: str = Field(default_factory=lambda: os.environ.get("WHATSAPP_ACCESS_TOKEN", ""))
    phone_number_id: str = Field(default_factory=lambda: os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""))


class SignalConfig(BaseModel):
    enabled: bool = Field(default_factory=lambda: os.environ.get("SIGNAL_ENABLED", "false").lower() == "true")
    cli_path: str = Field(default_factory=lambda: os.environ.get("SIGNAL_CLI_PATH", "signal-cli"))
    phone_number: str = Field(default_factory=lambda: os.environ.get("SIGNAL_PHONE_NUMBER", ""))
    recipient: str = Field(default_factory=lambda: os.environ.get("SIGNAL_RECIPIENT", ""))


class DiscordConfig(BaseModel):
    enabled: bool = Field(default_factory=lambda: os.environ.get("DISCORD_ENABLED", "false").lower() == "true")
    webhook_url: str = Field(default_factory=lambda: os.environ.get("DISCORD_WEBHOOK_URL", ""))


class RemoteConnectionsConfig(BaseModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    signal: SignalConfig = Field(default_factory=SignalConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl_llm: int = 86400        # 24h — LLM response cache
    ttl_tools: int = 604800     # 7 days — paper/PDF fetches
    ttl_search: int = 3600      # 1h — search results
    max_history_chars: int = 32000  # ~8k tokens; trim context beyond this


class WorkflowConfig(BaseModel):
    enabled: bool = True
    eko_sidecar_url: str = "http://localhost:7862"
    storage_dir: str = "./output/.workflows"
    max_execution_time_minutes: int = 30
    default_model: str = "qwen2.5-vl:7b"


class AgentInstanceConfig(BaseModel):
    enabled: bool = True
    model_override: str = ""  # empty = use global config.llm.model


class AgentsConfig(BaseModel):
    blog_writer: AgentInstanceConfig = Field(default_factory=AgentInstanceConfig)
    website_maintenance: AgentInstanceConfig = Field(default_factory=AgentInstanceConfig)
    model_training: AgentInstanceConfig = Field(default_factory=AgentInstanceConfig)
    data_visualization: AgentInstanceConfig = Field(default_factory=AgentInstanceConfig)
    paper_to_code: AgentInstanceConfig = Field(default_factory=AgentInstanceConfig)
    digest_writer: AgentInstanceConfig = Field(default_factory=AgentInstanceConfig)


class AgentConfig(BaseModel):
    name: str = "CV Research Agent"
    description: str = "Autonomous computer vision research agent"
    log_level: str = "INFO"
    vision: VisionConfig = Field(default_factory=VisionConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    llmfit: LlmfitConfig = Field(default_factory=LlmfitConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    spec: SpecConfig = Field(default_factory=SpecConfig)
    text_to_diagram: TextToDiagramConfig = Field(default_factory=TextToDiagramConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    remote: RemoteConnectionsConfig = Field(default_factory=RemoteConnectionsConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)

def _resolve_env_vars(data: dict | list | str) -> dict | list | str:
    """Recursively resolve ${VAR:-default} patterns in config values."""
    if isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_vars(item) for item in data]
    if isinstance(data, str) and "${" in data:
        import re
        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            default = match.group(3) if match.group(3) is not None else ""
            return os.environ.get(var_name, default)
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-(.*?))?\}", _replace, data)
    return data


def load_config(config_path: str | Path | None = None) -> AgentConfig:
    """Load agent configuration from YAML file with env var resolution."""
    if config_path is None:
        config_path = _PROJECT_ROOT / "config" / "agent_config.yaml"
    config_path = Path(config_path)

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        if raw and isinstance(raw, dict):
            # Remove top-level 'agent' wrapper keys that are flat
            agent_flat = {}
            for key in ("name", "description", "log_level"):
                if "agent" in raw and key in raw["agent"]:
                    agent_flat[key] = raw["agent"][key]
            merged = {**agent_flat, **{k: v for k, v in raw.items() if k != "agent"}}
            resolved = _resolve_env_vars(merged)
            return AgentConfig(**resolved)

    return AgentConfig()
