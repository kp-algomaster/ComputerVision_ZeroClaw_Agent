use anyhow::Context;
use async_trait::async_trait;
use base64::{engine::general_purpose::STANDARD as B64, Engine};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::fs;
use tracing::debug;

use crate::config::OllamaVisionConfig;
use super::Tool;

pub struct VisionTool {
    http: Client,
    config: OllamaVisionConfig,
}

impl VisionTool {
    pub fn new(config: &OllamaVisionConfig) -> Self {
        Self {
            http: Client::builder()
                .timeout(std::time::Duration::from_secs(config.timeout_secs))
                .build()
                .expect("http client"),
            config: config.clone(),
        }
    }

    async fn encode_image(path: &str) -> anyhow::Result<String> {
        let bytes = fs::read(path)
            .await
            .with_context(|| format!("reading image file: {path}"))?;
        Ok(B64.encode(&bytes))
    }
}

#[derive(Debug, Serialize)]
struct OllamaChatRequest {
    model: String,
    messages: Vec<OllamaMessage>,
    stream: bool,
    options: OllamaOptions,
}

#[derive(Debug, Serialize)]
struct OllamaMessage {
    role: String,
    content: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    images: Vec<String>,
}

#[derive(Debug, Serialize)]
struct OllamaOptions {
    num_predict: u32,
}

#[derive(Debug, Deserialize)]
struct OllamaChatResponse {
    message: OllamaResponseMessage,
}

#[derive(Debug, Deserialize)]
struct OllamaResponseMessage {
    content: String,
}

#[async_trait]
impl Tool for VisionTool {
    fn name(&self) -> &str {
        "analyze_image"
    }

    fn description(&self) -> &str {
        "Analyze an image using the Ollama vision model (e.g. qwen2.5-vl). \
        Accepts a local file path. Returns a detailed description or answer to the prompt."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the image file (PNG, JPEG, etc.)"
                },
                "prompt": {
                    "type": "string",
                    "description": "Question or instruction for the vision model",
                    "default": "Analyze this image in detail."
                },
                "model": {
                    "type": "string",
                    "description": "Ollama vision model to use (optional, uses default from config)"
                }
            },
            "required": ["image_path"]
        })
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let image_path = args["image_path"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'image_path' argument"))?;
        let prompt = args["prompt"]
            .as_str()
            .unwrap_or("Analyze this image in detail.");
        let model = args["model"]
            .as_str()
            .unwrap_or(&self.config.default_model)
            .to_string();

        debug!("vision: analyzing {} with model {}", image_path, model);

        let image_b64 = Self::encode_image(image_path).await?;

        let host = self.config.host.trim_end_matches('/');
        let url = format!("{host}/api/chat");

        let request_body = OllamaChatRequest {
            model,
            messages: vec![OllamaMessage {
                role: "user".into(),
                content: prompt.to_string(),
                images: vec![image_b64],
            }],
            stream: false,
            options: OllamaOptions {
                num_predict: self.config.max_tokens,
            },
        };

        let resp = self
            .http
            .post(&url)
            .json(&request_body)
            .send()
            .await
            .context("sending vision request to Ollama")?;

        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(anyhow::anyhow!("Ollama vision error {status}: {text}"));
        }

        let ollama_resp: OllamaChatResponse = resp.json().await.context("parsing Ollama response")?;
        Ok(ollama_resp.message.content)
    }
}
