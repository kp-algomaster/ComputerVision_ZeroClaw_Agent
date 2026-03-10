use anyhow::Context;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio_stream::Stream;
use tracing::{debug, info, warn};

use crate::config::AgentConfig;
use crate::llm::{LlmClient, Message};
use crate::tools::{build_tools, format_tools_prompt, ToolBox};

const MAX_TOOL_ROUNDS: u32 = 10;

pub const SYSTEM_PROMPT_TEMPLATE: &str = r#"You are CV Zero Claw, an expert computer vision research assistant with live access to ArXiv, the web, and local tools.

═══════════════════════════════════════════════════════
MANDATORY TOOL-USE POLICY — READ CAREFULLY
═══════════════════════════════════════════════════════
You MUST use tools for every research and paper question. NEVER answer from training data or prior knowledge when current information is needed.

• ANY question about "latest", "recent", or "new papers" in CV → call `search_arxiv` FIRST (days_back=30 or 7 as appropriate), then summarise the actual results you received.
• ANY question about a specific paper → call `fetch_arxiv_paper` with the ID or URL before answering anything.
• ANY vision/image task → call `analyze_image` with the image path.
• If unsure whether a tool will help — use the tool. Your value comes from real, live results.

DO NOT produce a text answer before calling at least one tool for any research question.
═══════════════════════════════════════════════════════

To use a tool, respond with ONLY a JSON object in this exact format (no markdown, no text before or after):
{"name": "tool_name", "arguments": {"arg1": "value1"}}

When you have gathered enough information, respond normally in markdown.

Available tools:
{TOOLS_JSON}

When synthesising results from tools:
- Lead with the most impactful / novel findings
- Extract core contributions, mathematical formulations, and datasets
- Note comparison baselines and practical implementability
- Link related work where relevant
"#;

pub struct Agent {
    config: AgentConfig,
    llm: LlmClient,
    tools: ToolBox,
}

impl Agent {
    pub fn new(config: AgentConfig) -> anyhow::Result<Self> {
        let llm = LlmClient::new(config.llm.clone()).context("creating LLM client")?;
        let tools = build_tools(&config);
        Ok(Self { config, llm, tools })
    }

    fn build_system_prompt(&self) -> String {
        let tools_json = format_tools_prompt(&self.tools);
        SYSTEM_PROMPT_TEMPLATE.replace("{TOOLS_JSON}", &tools_json)
    }

    /// Run the ReAct loop for a single user message and return the final answer.
    pub async fn run(&self, message: &str, history: &[Message]) -> anyhow::Result<String> {
        let system_prompt = self.build_system_prompt();
        let mut messages: Vec<Message> = vec![Message::system(&system_prompt)];
        messages.extend_from_slice(history);
        messages.push(Message::user(message));

        let mut rounds = 0u32;
        loop {
            if rounds >= MAX_TOOL_ROUNDS {
                warn!("max tool rounds ({MAX_TOOL_ROUNDS}) reached");
                break;
            }

            let resp = self.llm.chat(messages.clone()).await?;
            let content = resp.content.trim().to_string();
            messages.push(Message::assistant(&content));

            if let Some((tool_name, tool_args)) = extract_tool_call(&content) {
                info!("tool call: {} {:?}", tool_name, tool_args);

                let result = match self.tools.iter().find(|t| t.name() == tool_name) {
                    Some(tool) => {
                        tool.call(tool_args)
                            .await
                            .unwrap_or_else(|e| format!("Error executing tool: {e}"))
                    }
                    None => format!("Unknown tool: {tool_name}. Available tools: {}",
                        self.tools.iter().map(|t| t.name()).collect::<Vec<_>>().join(", ")),
                };

                debug!("tool result ({} chars): {}", result.len(), &result[..result.len().min(200)]);
                messages.push(Message::tool(&tool_name, &result));
                rounds += 1;
                continue;
            }

            // No tool call — this is the final answer
            let clean = strip_leading_tool_calls(&content);
            return Ok(clean);
        }

        // Max rounds exceeded — return the last assistant message
        let fallback = messages
            .iter()
            .rev()
            .find(|m| matches!(m.role, crate::llm::types::Role::Assistant))
            .map(|m| strip_leading_tool_calls(&m.content))
            .unwrap_or_else(|| {
                "I reached my tool call limit without completing the research. \
                Please try a more specific question."
                    .to_string()
            });

        Ok(fallback)
    }

    /// Stream version of the ReAct loop that yields AgentEvents.
    pub async fn run_stream(
        &self,
        message: &str,
        history: &[Message],
    ) -> anyhow::Result<impl Stream<Item = AgentEvent>> {
        let system_prompt = self.build_system_prompt();
        let mut messages: Vec<Message> = vec![Message::system(&system_prompt)];
        messages.extend_from_slice(history);
        messages.push(Message::user(message));

        // We need owned references for the async closure
        let llm = std::sync::Arc::new(LlmClient::new(self.config.llm.clone())?);
        let tools: std::sync::Arc<ToolBox> = std::sync::Arc::new(build_tools(&self.config));

        let stream = async_stream::stream! {
            let mut msgs = messages;
            let mut rounds = 0u32;

            'outer: loop {
                if rounds >= MAX_TOOL_ROUNDS {
                    warn!("max tool rounds ({MAX_TOOL_ROUNDS}) reached in stream");
                    yield AgentEvent::Error {
                        message: "Max tool rounds reached. Try a more specific question.".into(),
                    };
                    break;
                }

                // Stream the LLM response
                let stream_result = llm.chat_stream(msgs.clone()).await;
                let mut token_stream = match stream_result {
                    Ok(s) => s,
                    Err(e) => {
                        yield AgentEvent::Error { message: format!("LLM error: {e}") };
                        break;
                    }
                };

                let mut full_content = String::new();
                let mut token_buf = String::new();
                let mut is_tool_call = false;

                tokio::pin!(token_stream);
                while let Some(tok) = token_stream.next().await {
                    if tok.done {
                        break;
                    }

                    token_buf.push_str(&tok.delta);

                    // Check if we're accumulating a tool call JSON
                    let trimmed = token_buf.trim_start();
                    if trimmed.starts_with('{') || "{\"name\"".starts_with(trimmed) {
                        // Possibly a tool call — keep buffering without streaming to UI
                        is_tool_call = true;
                        continue;
                    }

                    // Flush buffered text as a stream token
                    if !token_buf.is_empty() {
                        full_content.push_str(&token_buf);
                        yield AgentEvent::StreamToken { content: token_buf.clone() };
                        token_buf.clear();
                    }
                }

                // Flush any remaining buffer
                if !token_buf.is_empty() {
                    full_content.push_str(&token_buf);
                    if !is_tool_call {
                        yield AgentEvent::StreamToken { content: token_buf };
                    }
                }

                let content = full_content.trim().to_string();
                msgs.push(Message::assistant(&content));

                // Check for tool call
                if let Some((tool_name, tool_args)) = extract_tool_call(&content) {
                    let input_preview = serde_json::to_string(&tool_args)
                        .unwrap_or_default()
                        .chars()
                        .take(200)
                        .collect::<String>();

                    yield AgentEvent::ToolStart {
                        name: tool_name.clone(),
                        input: input_preview,
                    };

                    let result = match tools.iter().find(|t| t.name() == tool_name) {
                        Some(tool) => {
                            tool.call(tool_args)
                                .await
                                .unwrap_or_else(|e| format!("Error: {e}"))
                        }
                        None => format!("Unknown tool: {tool_name}"),
                    };

                    let output_preview = result.chars().take(500).collect::<String>();
                    yield AgentEvent::ToolEnd {
                        name: tool_name.clone(),
                        output: output_preview,
                    };

                    msgs.push(Message::tool(&tool_name, &result));
                    rounds += 1;
                    continue 'outer;
                }

                // Final answer
                let final_text = strip_leading_tool_calls(&content);
                yield AgentEvent::Done { content: final_text };
                break;
            }
        };

        Ok(stream)
    }
}

/// Parse a tool call JSON from LLM output.
/// Returns `(tool_name, arguments)` if found.
///
/// Uses a balanced-brace parser to correctly handle nested objects.
pub fn extract_tool_call(text: &str) -> Option<(String, Value)> {
    let trimmed = text.trim();

    // Find the first '{' character
    let start = trimmed.find('{')?;
    let s = &trimmed[start..];

    // Balance braces to find the full JSON object
    let json_str = extract_balanced_braces(s)?;

    let val: Value = serde_json::from_str(json_str).ok()?;
    let obj = val.as_object()?;

    // Must have "name" key to be a tool call
    let name = obj.get("name")?.as_str()?.to_string();

    // "arguments" or "args" or default to empty object
    let arguments = obj
        .get("arguments")
        .or_else(|| obj.get("args"))
        .cloned()
        .unwrap_or(Value::Object(serde_json::Map::new()));

    Some((name, arguments))
}

/// Extract a substring that forms a balanced `{...}` JSON object from the start of `s`.
fn extract_balanced_braces(s: &str) -> Option<&str> {
    let mut depth = 0i32;
    let mut in_string = false;
    let mut escape_next = false;
    let chars: Vec<char> = s.chars().collect();
    let mut byte_end = 0usize;

    for (i, &ch) in chars.iter().enumerate() {
        // Update byte offset
        byte_end += ch.len_utf8();

        if escape_next {
            escape_next = false;
            continue;
        }

        if in_string {
            match ch {
                '\\' => escape_next = true,
                '"' => in_string = false,
                _ => {}
            }
        } else {
            match ch {
                '"' => in_string = true,
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        return Some(&s[..byte_end]);
                    }
                }
                _ => {}
            }
        }
    }

    None
}

/// Strip leading JSON tool-call objects from text (for final answer cleanup).
fn strip_leading_tool_calls(text: &str) -> String {
    let mut s = text.trim().to_string();
    loop {
        let trimmed = s.trim_start().to_string();
        if !trimmed.starts_with('{') {
            break;
        }
        if let Some(json_str) = extract_balanced_braces(&trimmed) {
            if let Ok(val) = serde_json::from_str::<Value>(json_str) {
                if val.get("name").is_some() {
                    s = trimmed[json_str.len()..].trim().to_string();
                    continue;
                }
            }
        }
        break;
    }
    s
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AgentEvent {
    ToolStart { name: String, input: String },
    ToolEnd { name: String, output: String },
    StreamToken { content: String },
    Done { content: String },
    Error { message: String },
}
