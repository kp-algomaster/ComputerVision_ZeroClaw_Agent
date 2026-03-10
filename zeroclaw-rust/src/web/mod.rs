use std::sync::Arc;

use axum::{
    extract::State,
    http::StatusCode,
    response::{Html, IntoResponse, Json},
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tower_http::cors::{Any, CorsLayer};
use tracing::info;

use crate::agent::Agent;

pub mod ws;

/// Shared application state injected into axum handlers.
#[derive(Clone)]
pub struct AppState {
    pub agent: Arc<Agent>,
}

/// Build and return the axum Router.
pub fn build_router(state: AppState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    Router::new()
        .route("/health", get(health_handler))
        .route("/", get(index_handler))
        .route("/ws/chat", get(ws::ws_handler))
        .route("/api/chat", post(chat_handler))
        .with_state(state)
        .layer(cors)
}

/// Health check endpoint.
async fn health_handler() -> impl IntoResponse {
    Json(json!({"status": "ok", "service": "zeroclaw"}))
}

/// Serve a minimal built-in UI (no static files needed).
async fn index_handler() -> impl IntoResponse {
    Html(EMBEDDED_UI)
}

/// Simple REST chat endpoint (non-streaming) for testing.
#[derive(Debug, Deserialize)]
struct RestChatRequest {
    message: String,
    #[serde(default)]
    history: Vec<RestHistoryMessage>,
}

#[derive(Debug, Deserialize)]
struct RestHistoryMessage {
    role: String,
    content: String,
}

#[derive(Debug, Serialize)]
struct RestChatResponse {
    content: String,
}

async fn chat_handler(
    State(state): State<AppState>,
    Json(req): Json<RestChatRequest>,
) -> impl IntoResponse {
    use crate::llm::Message;

    let history: Vec<Message> = req
        .history
        .into_iter()
        .filter_map(|h| match h.role.as_str() {
            "user" => Some(Message::user(&h.content)),
            "assistant" => Some(Message::assistant(&h.content)),
            _ => None,
        })
        .collect();

    match state.agent.run(&req.message, &history).await {
        Ok(content) => (StatusCode::OK, Json(json!({ "content": content }))).into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({ "error": e.to_string() })),
        )
            .into_response(),
    }
}

/// Launch the web server on the given port.
pub async fn serve(agent: Arc<Agent>, port: u16) -> anyhow::Result<()> {
    let state = AppState { agent };
    let router = build_router(state);
    let addr = format!("0.0.0.0:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    info!("zeroclaw web server listening on http://{}", addr);
    axum::serve(listener, router).await?;
    Ok(())
}

/// Minimal embedded UI — a single-page chat interface.
const EMBEDDED_UI: &str = r#"<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>CV Zero Claw Agent</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #0f0f0f; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
    header { background: #1a1a2e; padding: 16px 24px; border-bottom: 1px solid #333; }
    header h1 { font-size: 1.2rem; color: #7eb8f7; }
    #messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
    .msg { max-width: 80%; padding: 12px 16px; border-radius: 8px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
    .msg.user { background: #1e3a5f; align-self: flex-end; }
    .msg.assistant { background: #1a1a2e; align-self: flex-start; border: 1px solid #333; }
    .msg.tool { background: #1a2a1a; align-self: flex-start; border: 1px solid #2a4a2a; font-size: 0.85rem; color: #90c890; }
    .msg.error { background: #3a1a1a; border: 1px solid #6a2a2a; color: #f08080; }
    #input-area { padding: 16px; background: #1a1a2e; border-top: 1px solid #333; display: flex; gap: 8px; }
    #input { flex: 1; background: #0f0f0f; color: #e0e0e0; border: 1px solid #444; border-radius: 6px; padding: 10px 14px; font-size: 1rem; resize: none; height: 60px; }
    #input:focus { outline: none; border-color: #7eb8f7; }
    #send-btn { background: #2563eb; color: white; border: none; border-radius: 6px; padding: 0 20px; cursor: pointer; font-size: 1rem; }
    #send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    #status { font-size: 0.8rem; color: #888; padding: 4px 0; }
  </style>
</head>
<body>
  <header>
    <h1>CV Zero Claw Agent</h1>
    <div id="status">Ready</div>
  </header>
  <div id="messages"></div>
  <div id="input-area">
    <textarea id="input" placeholder="Ask about computer vision research, papers, or analysis…" rows="2"></textarea>
    <button id="send-btn" onclick="sendMessage()">Send</button>
  </div>
  <script>
    const messages = document.getElementById('messages');
    const input = document.getElementById('input');
    const sendBtn = document.getElementById('send-btn');
    const status = document.getElementById('status');
    let ws = null;
    let history = [];
    let currentAssistantEl = null;
    let currentContent = '';

    function connect() {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws = new WebSocket(`${proto}//${location.host}/ws/chat`);

      ws.onopen = () => { status.textContent = 'Connected'; };
      ws.onclose = () => {
        status.textContent = 'Disconnected — reconnecting…';
        setTimeout(connect, 2000);
      };
      ws.onerror = () => { status.textContent = 'Connection error'; };

      ws.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        switch (data.type) {
          case 'token':
            if (!currentAssistantEl) {
              currentAssistantEl = addMsg('assistant', '');
              currentContent = '';
            }
            currentContent += data.content;
            currentAssistantEl.textContent = currentContent;
            scrollToBottom();
            break;
          case 'tool_start':
            addMsg('tool', `⚙ Calling tool: ${data.name}\nInput: ${data.input}`);
            status.textContent = `Running tool: ${data.name}…`;
            break;
          case 'tool_end':
            addMsg('tool', `✓ Tool ${data.name} done\nResult: ${(data.output || '').slice(0, 200)}…`);
            status.textContent = 'Thinking…';
            break;
          case 'done':
            if (data.content && !currentContent) {
              currentAssistantEl = addMsg('assistant', data.content);
            }
            history.push({ role: 'assistant', content: data.content || currentContent });
            currentAssistantEl = null;
            currentContent = '';
            status.textContent = 'Ready';
            sendBtn.disabled = false;
            scrollToBottom();
            break;
          case 'error':
            addMsg('error', `Error: ${data.message}`);
            status.textContent = 'Error';
            sendBtn.disabled = false;
            break;
        }
      };
    }

    function addMsg(role, text) {
      const el = document.createElement('div');
      el.className = `msg ${role}`;
      el.textContent = text;
      messages.appendChild(el);
      scrollToBottom();
      return el;
    }

    function scrollToBottom() {
      messages.scrollTop = messages.scrollHeight;
    }

    function sendMessage() {
      const text = input.value.trim();
      if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

      addMsg('user', text);
      history.push({ role: 'user', content: text });
      input.value = '';
      sendBtn.disabled = true;
      status.textContent = 'Thinking…';

      ws.send(JSON.stringify({ message: text, history: history.slice(-20) }));
    }

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    connect();
  </script>
</body>
</html>"#;
