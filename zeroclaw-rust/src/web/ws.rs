use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    response::Response,
};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::{debug, info, warn};

use crate::agent::{Agent, AgentEvent};
use crate::llm::Message as LlmMessage;
use crate::web::AppState;

/// Incoming WebSocket message from the browser client.
#[derive(Debug, Deserialize)]
pub struct WsChatRequest {
    pub message: String,
    #[serde(default)]
    pub history: Vec<WsHistoryMessage>,
}

/// A single turn in the conversation history sent by the client.
#[derive(Debug, Deserialize)]
pub struct WsHistoryMessage {
    pub role: String,
    pub content: String,
}

/// Outgoing WebSocket message to the browser client.
#[derive(Debug, Serialize)]
pub struct WsResponse {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

impl From<AgentEvent> for WsResponse {
    fn from(event: AgentEvent) -> Self {
        match event {
            AgentEvent::StreamToken { content } => WsResponse {
                kind: "token".into(),
                content: Some(content),
                name: None,
                input: None,
                output: None,
                message: None,
            },
            AgentEvent::ToolStart { name, input } => WsResponse {
                kind: "tool_start".into(),
                content: None,
                name: Some(name),
                input: Some(input),
                output: None,
                message: None,
            },
            AgentEvent::ToolEnd { name, output } => WsResponse {
                kind: "tool_end".into(),
                content: None,
                name: Some(name),
                input: None,
                output: Some(output),
                message: None,
            },
            AgentEvent::Done { content } => WsResponse {
                kind: "done".into(),
                content: Some(content),
                name: None,
                input: None,
                output: None,
                message: None,
            },
            AgentEvent::Error { message } => WsResponse {
                kind: "error".into(),
                content: None,
                name: None,
                input: None,
                output: None,
                message: Some(message),
            },
        }
    }
}

/// Axum handler that upgrades the connection to a WebSocket.
pub async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    info!("WebSocket upgrade requested");
    ws.on_upgrade(|socket| handle_socket(socket, state))
}

async fn handle_socket(socket: WebSocket, state: AppState) {
    let (mut sender, mut receiver) = socket.split();

    while let Some(msg_result) = receiver.next().await {
        let msg = match msg_result {
            Ok(m) => m,
            Err(e) => {
                warn!("WebSocket receive error: {e}");
                break;
            }
        };

        let text = match msg {
            Message::Text(t) => t,
            Message::Close(_) => {
                debug!("WebSocket close received");
                break;
            }
            _ => continue,
        };

        // Parse the incoming chat request
        let req: WsChatRequest = match serde_json::from_str(&text) {
            Ok(r) => r,
            Err(e) => {
                let err = WsResponse {
                    kind: "error".into(),
                    content: None,
                    name: None,
                    input: None,
                    output: None,
                    message: Some(format!("Invalid request JSON: {e}")),
                };
                let _ = sender
                    .send(Message::Text(serde_json::to_string(&err).unwrap().into()))
                    .await;
                continue;
            }
        };

        // Convert history to LLM messages
        let history: Vec<LlmMessage> = req
            .history
            .into_iter()
            .filter_map(|h| match h.role.as_str() {
                "user" => Some(LlmMessage::user(&h.content)),
                "assistant" => Some(LlmMessage::assistant(&h.content)),
                _ => None,
            })
            .collect();

        // Run the agent stream
        let stream_result = state.agent.run_stream(&req.message, &history).await;

        match stream_result {
            Ok(stream) => {
                tokio::pin!(stream);
                while let Some(event) = stream.next().await {
                    let ws_resp: WsResponse = event.into();
                    let json = match serde_json::to_string(&ws_resp) {
                        Ok(j) => j,
                        Err(e) => {
                            warn!("serialization error: {e}");
                            continue;
                        }
                    };
                    if sender.send(Message::Text(json.into())).await.is_err() {
                        // Client disconnected
                        return;
                    }
                }
            }
            Err(e) => {
                let err = WsResponse {
                    kind: "error".into(),
                    content: None,
                    name: None,
                    input: None,
                    output: None,
                    message: Some(format!("Agent error: {e}")),
                };
                let _ = sender
                    .send(Message::Text(serde_json::to_string(&err).unwrap().into()))
                    .await;
            }
        }
    }

    debug!("WebSocket connection closed");
}
