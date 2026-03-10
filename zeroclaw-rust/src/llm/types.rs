use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    System,
    User,
    Assistant,
    Tool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub role: Role,
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}

impl Message {
    pub fn system(content: impl Into<String>) -> Self {
        Self { role: Role::System, content: content.into(), name: None }
    }

    pub fn user(content: impl Into<String>) -> Self {
        Self { role: Role::User, content: content.into(), name: None }
    }

    pub fn assistant(content: impl Into<String>) -> Self {
        Self { role: Role::Assistant, content: content.into(), name: None }
    }

    pub fn tool(tool_name: impl Into<String>, content: impl Into<String>) -> Self {
        Self {
            role: Role::Tool,
            content: content.into(),
            name: Some(tool_name.into()),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatRequest {
    pub model: String,
    pub messages: Vec<Message>,
    pub temperature: f32,
    pub max_tokens: u32,
    pub stream: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatResponse {
    pub content: String,
    pub finish_reason: Option<String>,
}

#[derive(Debug, Clone)]
pub struct StreamToken {
    pub delta: String,
    pub done: bool,
}

// Internal SSE response shapes from OpenAI-compatible endpoints

#[derive(Debug, Deserialize)]
pub struct OaiStreamChunk {
    pub choices: Vec<OaiStreamChoice>,
}

#[derive(Debug, Deserialize)]
pub struct OaiStreamChoice {
    pub delta: OaiDelta,
    pub finish_reason: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct OaiDelta {
    pub content: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct OaiResponse {
    pub choices: Vec<OaiChoice>,
}

#[derive(Debug, Deserialize)]
pub struct OaiChoice {
    pub message: OaiMessage,
    pub finish_reason: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct OaiMessage {
    pub content: Option<String>,
}
