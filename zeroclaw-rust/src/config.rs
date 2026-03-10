use anyhow::Context;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AgentConfig {
    #[serde(default = "default_name")]
    pub name: String,
    #[serde(default = "default_description")]
    pub description: String,
    #[serde(default = "default_log_level")]
    pub log_level: String,
    #[serde(default)]
    pub llm: LlmConfig,
    #[serde(default)]
    pub vision: VisionConfig,
    #[serde(default)]
    pub research: ResearchConfig,
    #[serde(default)]
    pub output: OutputConfig,
    #[serde(default)]
    pub cache: CacheConfig,
}

fn default_name() -> String {
    "CV Research Agent".into()
}
fn default_description() -> String {
    "Autonomous computer vision research agent".into()
}
fn default_log_level() -> String {
    "INFO".into()
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct LlmConfig {
    #[serde(default = "default_provider")]
    pub provider: String,
    #[serde(default = "default_model")]
    pub model: String,
    #[serde(default = "default_base_url")]
    pub base_url: String,
    #[serde(default = "default_temperature")]
    pub temperature: f32,
    #[serde(default = "default_max_tokens")]
    pub max_tokens: u32,
    #[serde(default)]
    pub api_key: Option<String>,
}

fn default_provider() -> String {
    "ollama".into()
}
fn default_model() -> String {
    "qwen2.5:7b".into()
}
fn default_base_url() -> String {
    "http://localhost:11434/v1".into()
}
fn default_temperature() -> f32 {
    0.3
}
fn default_max_tokens() -> u32 {
    8192
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            provider: default_provider(),
            model: default_model(),
            base_url: default_base_url(),
            temperature: default_temperature(),
            max_tokens: default_max_tokens(),
            api_key: None,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct OllamaVisionConfig {
    #[serde(default = "default_ollama_host")]
    pub host: String,
    #[serde(default = "default_vision_model")]
    pub default_model: String,
    #[serde(default = "default_vision_models")]
    pub models: Vec<String>,
    #[serde(default = "default_vision_timeout")]
    pub timeout_secs: u64,
    #[serde(default = "default_vision_max_tokens")]
    pub max_tokens: u32,
}

fn default_ollama_host() -> String {
    "http://localhost:11434".into()
}
fn default_vision_model() -> String {
    "qwen2.5-vl:7b".into()
}
fn default_vision_models() -> Vec<String> {
    vec!["qwen2.5-vl:7b".into()]
}
fn default_vision_timeout() -> u64 {
    120
}
fn default_vision_max_tokens() -> u32 {
    4096
}

impl Default for OllamaVisionConfig {
    fn default() -> Self {
        Self {
            host: default_ollama_host(),
            default_model: default_vision_model(),
            models: default_vision_models(),
            timeout_secs: default_vision_timeout(),
            max_tokens: default_vision_max_tokens(),
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct VisionConfig {
    #[serde(default)]
    pub ollama: OllamaVisionConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ArxivSourceConfig {
    #[serde(default = "bool_true")]
    pub enabled: bool,
    #[serde(default = "default_arxiv_categories")]
    pub categories: Vec<String>,
    #[serde(default = "default_max_results")]
    pub max_results_per_query: u32,
    #[serde(default)]
    pub queries: Vec<String>,
}

fn bool_true() -> bool {
    true
}
fn default_arxiv_categories() -> Vec<String> {
    vec!["cs.CV".into(), "cs.AI".into(), "cs.LG".into()]
}
fn default_max_results() -> u32 {
    50
}

impl Default for ArxivSourceConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            categories: default_arxiv_categories(),
            max_results_per_query: default_max_results(),
            queries: vec![],
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct ResearchSourcesConfig {
    #[serde(default)]
    pub arxiv: ArxivSourceConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ResearchConfig {
    #[serde(default)]
    pub sources: ResearchSourcesConfig,
    #[serde(default = "default_check_interval")]
    pub check_interval_hours: u32,
    #[serde(default = "default_digest_day")]
    pub digest_day: String,
}

fn default_check_interval() -> u32 {
    12
}
fn default_digest_day() -> String {
    "Monday".into()
}

impl Default for ResearchConfig {
    fn default() -> Self {
        Self {
            sources: ResearchSourcesConfig::default(),
            check_interval_hours: default_check_interval(),
            digest_day: default_digest_day(),
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct OutputConfig {
    #[serde(default = "default_output_dir")]
    pub base_dir: String,
    #[serde(default = "default_digests_dir")]
    pub digests_dir: String,
}

fn default_output_dir() -> String {
    "./output".into()
}
fn default_digests_dir() -> String {
    "./output/digests".into()
}

impl Default for OutputConfig {
    fn default() -> Self {
        Self {
            base_dir: default_output_dir(),
            digests_dir: default_digests_dir(),
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CacheConfig {
    #[serde(default = "bool_true")]
    pub enabled: bool,
    #[serde(default = "default_ttl_llm")]
    pub ttl_llm: u64,
    #[serde(default = "default_ttl_tools")]
    pub ttl_tools: u64,
    #[serde(default = "default_ttl_search")]
    pub ttl_search: u64,
    #[serde(default = "default_max_history_chars")]
    pub max_history_chars: usize,
}

fn default_ttl_llm() -> u64 {
    86400
}
fn default_ttl_tools() -> u64 {
    604800
}
fn default_ttl_search() -> u64 {
    3600
}
fn default_max_history_chars() -> usize {
    32000
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            ttl_llm: default_ttl_llm(),
            ttl_tools: default_ttl_tools(),
            ttl_search: default_ttl_search(),
            max_history_chars: default_max_history_chars(),
        }
    }
}

impl AgentConfig {
    pub fn load() -> anyhow::Result<Self> {
        // Try to find config/agent_config.yaml relative to cwd or parent dirs
        let config_candidates = [
            std::path::PathBuf::from("config/agent_config.yaml"),
            std::path::PathBuf::from("../config/agent_config.yaml"),
            std::path::PathBuf::from("../../config/agent_config.yaml"),
        ];

        for path in &config_candidates {
            if path.exists() {
                let raw = std::fs::read_to_string(path)
                    .with_context(|| format!("reading {}", path.display()))?;
                let resolved = resolve_env_vars(&raw);
                let value: serde_yaml::Value = serde_yaml::from_str(&resolved)
                    .context("parsing agent_config.yaml")?;
                // Flatten the 'agent' top-level key into root
                let merged = flatten_agent_key(value);
                let config: AgentConfig = serde_yaml::from_value(merged)
                    .context("deserializing AgentConfig")?;
                return Ok(config);
            }
        }

        // Fall back to defaults
        Ok(AgentConfig::default())
    }
}

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            name: default_name(),
            description: default_description(),
            log_level: default_log_level(),
            llm: LlmConfig::default(),
            vision: VisionConfig::default(),
            research: ResearchConfig::default(),
            output: OutputConfig::default(),
            cache: CacheConfig::default(),
        }
    }
}

/// Flatten the optional 'agent:' wrapper key into the root map
fn flatten_agent_key(mut value: serde_yaml::Value) -> serde_yaml::Value {
    if let serde_yaml::Value::Mapping(ref mut map) = value {
        if let Some(agent_val) = map.remove("agent") {
            if let serde_yaml::Value::Mapping(agent_map) = agent_val {
                for (k, v) in agent_map {
                    map.insert(k, v);
                }
            }
        }
    }
    value
}

/// Replace `${VAR:-default}` and `${VAR}` patterns in a YAML string using env vars.
pub fn resolve_env_vars(input: &str) -> String {
    let re = Regex::new(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}").unwrap();
    re.replace_all(input, |caps: &regex::Captures| {
        let var_name = &caps[1];
        let default_val = caps.get(3).map(|m| m.as_str()).unwrap_or("");
        std::env::var(var_name).unwrap_or_else(|_| default_val.to_string())
    })
    .into_owned()
}
