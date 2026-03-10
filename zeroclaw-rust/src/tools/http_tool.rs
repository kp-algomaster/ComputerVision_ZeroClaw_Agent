use anyhow::Context;
use async_trait::async_trait;
use reqwest::Client;
use serde_json::{json, Value};
use std::collections::HashMap;
use tracing::debug;

use super::Tool;

pub struct HttpTool {
    http: Client,
}

impl HttpTool {
    pub fn new() -> Self {
        Self {
            http: Client::builder()
                .user_agent("zeroclaw-agent/0.1")
                .timeout(std::time::Duration::from_secs(30))
                .redirect(reqwest::redirect::Policy::limited(5))
                .build()
                .expect("http client"),
        }
    }
}

#[async_trait]
impl Tool for HttpTool {
    fn name(&self) -> &str {
        "http_request"
    }

    fn description(&self) -> &str {
        "Make an HTTP request to any URL and return the response body (max 32 KB). \
        Supports GET, POST, PUT, DELETE. Use for fetching web pages, APIs, or raw content."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to request"
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method (default: GET)",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
                    "default": "GET"
                },
                "headers": {
                    "type": "object",
                    "description": "Optional HTTP headers as key-value pairs",
                    "additionalProperties": { "type": "string" }
                },
                "body": {
                    "type": "string",
                    "description": "Optional request body (for POST/PUT/PATCH)"
                },
                "timeout_secs": {
                    "type": "integer",
                    "description": "Request timeout in seconds (default 30)",
                    "default": 30
                }
            },
            "required": ["url"]
        })
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let url = args["url"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'url' argument"))?;
        let method = args["method"].as_str().unwrap_or("GET").to_uppercase();

        debug!("http_request: {} {}", method, url);

        let timeout_secs = args["timeout_secs"].as_u64().unwrap_or(30);

        let mut req = match method.as_str() {
            "GET" => self.http.get(url),
            "POST" => self.http.post(url),
            "PUT" => self.http.put(url),
            "DELETE" => self.http.delete(url),
            "PATCH" => self.http.patch(url),
            "HEAD" => self.http.head(url),
            other => return Err(anyhow::anyhow!("unsupported method: {other}")),
        };

        req = req.timeout(std::time::Duration::from_secs(timeout_secs));

        // Apply headers
        if let Some(headers) = args["headers"].as_object() {
            for (k, v) in headers {
                if let Some(val) = v.as_str() {
                    req = req.header(k, val);
                }
            }
        }

        // Apply body
        if let Some(body) = args["body"].as_str() {
            req = req.body(body.to_string());
        }

        let resp = req.send().await.context("HTTP request failed")?;
        let status = resp.status();
        let headers_summary = resp
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("unknown")
            .to_string();

        let body_bytes = resp.bytes().await.context("reading response body")?;
        const MAX_BODY: usize = 32768;
        let body_str = String::from_utf8_lossy(&body_bytes[..body_bytes.len().min(MAX_BODY)]);
        let truncated = body_bytes.len() > MAX_BODY;

        let mut result = format!(
            "HTTP {status} | Content-Type: {headers_summary}\n\n{body_str}"
        );

        if truncated {
            result.push_str(&format!(
                "\n\n[... truncated at {} bytes of {} total ...]",
                MAX_BODY,
                body_bytes.len()
            ));
        }

        Ok(result)
    }
}
