use anyhow::Context;
use async_trait::async_trait;
use reqwest::Client;
use serde::Deserialize;
use serde_json::{json, Value};
use tracing::debug;

use super::Tool;

pub struct WebSearchTool {
    http: Client,
}

impl WebSearchTool {
    pub fn new() -> Self {
        Self {
            http: Client::builder()
                .user_agent("zeroclaw-agent/0.1 (research bot)")
                .timeout(std::time::Duration::from_secs(20))
                .build()
                .expect("http client"),
        }
    }
}

/// DuckDuckGo Instant Answer API response (subset)
#[derive(Debug, Deserialize)]
struct DdgResponse {
    #[serde(rename = "AbstractText")]
    abstract_text: Option<String>,
    #[serde(rename = "AbstractURL")]
    abstract_url: Option<String>,
    #[serde(rename = "AbstractSource")]
    abstract_source: Option<String>,
    #[serde(rename = "RelatedTopics")]
    related_topics: Option<Vec<DdgTopic>>,
    #[serde(rename = "Answer")]
    answer: Option<String>,
}

#[derive(Debug, Deserialize)]
struct DdgTopic {
    #[serde(rename = "Text")]
    text: Option<String>,
    #[serde(rename = "FirstURL")]
    first_url: Option<String>,
}

/// Brave Search API response (subset)
#[derive(Debug, Deserialize)]
struct BraveResponse {
    web: Option<BraveWeb>,
}

#[derive(Debug, Deserialize)]
struct BraveWeb {
    results: Vec<BraveResult>,
}

#[derive(Debug, Deserialize)]
struct BraveResult {
    title: String,
    url: String,
    description: Option<String>,
}

#[async_trait]
impl Tool for WebSearchTool {
    fn name(&self) -> &str {
        "web_search"
    }

    fn description(&self) -> &str {
        "Search the web using DuckDuckGo (or Brave Search if BRAVE_API_KEY is set). \
        Returns titles, URLs, and snippets for the top results."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 8)",
                    "default": 8
                }
            },
            "required": ["query"]
        })
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let query = args["query"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'query' argument"))?;
        let max_results = args["max_results"].as_u64().unwrap_or(8) as usize;

        debug!("web_search: {}", query);

        // Use Brave if API key is available
        if let Ok(brave_key) = std::env::var("BRAVE_API_KEY") {
            return self.brave_search(query, max_results, &brave_key).await;
        }

        self.ddg_search(query, max_results).await
    }
}

impl WebSearchTool {
    async fn ddg_search(&self, query: &str, max_results: usize) -> anyhow::Result<String> {
        let resp = self
            .http
            .get("https://api.duckduckgo.com/")
            .query(&[
                ("q", query),
                ("format", "json"),
                ("no_html", "1"),
                ("skip_disambig", "1"),
            ])
            .send()
            .await
            .context("DDG request failed")?;

        let ddg: DdgResponse = resp.json().await.context("DDG JSON parse")?;

        let mut lines: Vec<String> = vec![format!("## Web Search: \"{query}\"\n")];

        // Instant answer
        if let Some(ref ans) = ddg.answer {
            if !ans.is_empty() {
                lines.push(format!("**Answer:** {ans}\n"));
            }
        }

        // Abstract
        if let Some(ref abs_text) = ddg.abstract_text {
            if !abs_text.is_empty() {
                let src = ddg.abstract_source.as_deref().unwrap_or("DDG");
                let url = ddg.abstract_url.as_deref().unwrap_or("");
                lines.push(format!("**{src}:** {abs_text}\n<{url}>\n"));
            }
        }

        // Related topics
        if let Some(topics) = ddg.related_topics {
            let mut count = 0;
            for topic in topics.into_iter().take(max_results) {
                if let (Some(text), Some(url)) = (topic.text, topic.first_url) {
                    lines.push(format!("- {text}\n  <{url}>"));
                    count += 1;
                    if count >= max_results {
                        break;
                    }
                }
            }
        }

        if lines.len() <= 1 {
            Ok(format!("No results found for: {query}"))
        } else {
            Ok(lines.join("\n"))
        }
    }

    async fn brave_search(
        &self,
        query: &str,
        max_results: usize,
        api_key: &str,
    ) -> anyhow::Result<String> {
        let resp = self
            .http
            .get("https://api.search.brave.com/res/v1/web/search")
            .header("Accept", "application/json")
            .header("X-Subscription-Token", api_key)
            .query(&[("q", query), ("count", &max_results.to_string())])
            .send()
            .await
            .context("Brave search request failed")?;

        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Err(anyhow::anyhow!("Brave API error {status}: {body}"));
        }

        let brave: BraveResponse = resp.json().await.context("Brave JSON parse")?;

        let mut lines: Vec<String> = vec![format!("## Web Search: \"{query}\"\n")];

        if let Some(web) = brave.web {
            for result in web.results.into_iter().take(max_results) {
                let desc = result.description.as_deref().unwrap_or("No description");
                lines.push(format!("**{}**\n{}\n<{}>", result.title, desc, result.url));
            }
        }

        if lines.len() <= 1 {
            Ok(format!("No results found for: {query}"))
        } else {
            Ok(lines.join("\n\n"))
        }
    }
}
