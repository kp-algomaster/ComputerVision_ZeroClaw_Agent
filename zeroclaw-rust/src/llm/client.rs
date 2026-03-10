use anyhow::{anyhow, Context};
use futures_util::StreamExt;
use reqwest::Client;
use serde_json::{json, Value};
use tokio_stream::Stream;
use tracing::{debug, warn};

use crate::config::LlmConfig;
use super::types::{ChatRequest, ChatResponse, Message, OaiResponse, OaiStreamChunk, StreamToken};

pub struct LlmClient {
    http: Client,
    config: LlmConfig,
}

impl LlmClient {
    pub fn new(config: LlmConfig) -> anyhow::Result<Self> {
        let http = Client::builder()
            .timeout(std::time::Duration::from_secs(300))
            .build()
            .context("building HTTP client")?;
        Ok(Self { http, config })
    }

    fn chat_url(&self) -> String {
        format!("{}/chat/completions", self.config.base_url.trim_end_matches('/'))
    }

    fn build_body(&self, messages: &[Message], stream: bool) -> Value {
        // Convert Role::Tool → "user" since many Ollama builds don't support "tool" role in v1 API
        let msgs: Vec<Value> = messages
            .iter()
            .map(|m| {
                let role_str = match m.role {
                    crate::llm::types::Role::System => "system",
                    crate::llm::types::Role::User => "user",
                    crate::llm::types::Role::Assistant => "assistant",
                    crate::llm::types::Role::Tool => "user",
                };
                let mut obj = json!({
                    "role": role_str,
                    "content": m.content,
                });
                if let Some(ref name) = m.name {
                    // Prefix tool results with name for clarity
                    if matches!(m.role, crate::llm::types::Role::Tool) {
                        obj["content"] = json!(format!("[Tool: {}]\n{}", name, m.content));
                    }
                }
                obj
            })
            .collect();

        json!({
            "model": self.config.model,
            "messages": msgs,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": stream,
        })
    }

    fn request_builder(&self, body: &Value) -> reqwest::RequestBuilder {
        let mut req = self
            .http
            .post(&self.chat_url())
            .json(body);

        if let Some(ref key) = self.config.api_key {
            if !key.is_empty() {
                req = req.bearer_auth(key);
            }
        }

        req
    }

    pub async fn chat(&self, messages: Vec<Message>) -> anyhow::Result<ChatResponse> {
        let body = self.build_body(&messages, false);
        debug!("POST {} (non-stream)", self.chat_url());

        let resp = self
            .request_builder(&body)
            .send()
            .await
            .context("sending chat request")?;

        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(anyhow!("LLM API error {status}: {text}"));
        }

        let oai: OaiResponse = resp.json().await.context("parsing chat response")?;
        let choice = oai.choices.into_iter().next().ok_or_else(|| anyhow!("no choices in response"))?;
        let content = choice.message.content.unwrap_or_default();
        Ok(ChatResponse {
            content,
            finish_reason: choice.finish_reason,
        })
    }

    pub async fn chat_stream(
        &self,
        messages: Vec<Message>,
    ) -> anyhow::Result<impl Stream<Item = StreamToken>> {
        let body = self.build_body(&messages, true);
        debug!("POST {} (stream)", self.chat_url());

        let resp = self
            .request_builder(&body)
            .send()
            .await
            .context("sending streaming chat request")?;

        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(anyhow!("LLM stream API error {status}: {text}"));
        }

        let byte_stream = resp.bytes_stream();

        // We collect partial SSE lines across byte chunks
        let stream = async_stream::stream! {
            let mut buf = String::new();
            tokio::pin!(byte_stream);

            while let Some(chunk_result) = byte_stream.next().await {
                let chunk = match chunk_result {
                    Ok(b) => b,
                    Err(e) => {
                        warn!("stream chunk error: {e}");
                        break;
                    }
                };

                buf.push_str(&String::from_utf8_lossy(&chunk));

                // Process all complete lines
                while let Some(newline_pos) = buf.find('\n') {
                    let line = buf[..newline_pos].trim_end_matches('\r').to_string();
                    buf = buf[newline_pos + 1..].to_string();

                    if line.starts_with("data: ") {
                        let data = &line["data: ".len()..];
                        if data == "[DONE]" {
                            yield StreamToken { delta: String::new(), done: true };
                            return;
                        }
                        match serde_json::from_str::<OaiStreamChunk>(data) {
                            Ok(chunk) => {
                                if let Some(choice) = chunk.choices.into_iter().next() {
                                    let done = choice.finish_reason.is_some();
                                    let delta = choice.delta.content.unwrap_or_default();
                                    yield StreamToken { delta, done };
                                    if done {
                                        return;
                                    }
                                }
                            }
                            Err(e) => {
                                debug!("SSE parse error: {e} — line: {data}");
                            }
                        }
                    }
                }
            }

            yield StreamToken { delta: String::new(), done: true };
        };

        Ok(stream)
    }
}
