use async_trait::async_trait;
use serde_json::Value;

pub mod file;
pub mod http_tool;
pub mod paper_fetch;
pub mod shell;
pub mod vision;
pub mod web_search;

pub use file::{FileReadTool, FileWriteTool};
pub use http_tool::HttpTool;
pub use paper_fetch::{ArxivFetchTool, ArxivSearchTool, PaperPdfTool};
pub use shell::ShellTool;
pub use vision::VisionTool;
pub use web_search::WebSearchTool;

use crate::config::AgentConfig;

/// Every tool must implement this trait.
#[async_trait]
pub trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn description(&self) -> &str;
    /// JSON Schema object describing the tool parameters.
    fn parameters_schema(&self) -> Value;
    /// Execute the tool with parsed arguments.
    async fn call(&self, args: Value) -> anyhow::Result<String>;
}

pub type ToolBox = Vec<Box<dyn Tool>>;

/// Construct the full tool list for the agent.
pub fn build_tools(config: &AgentConfig) -> ToolBox {
    vec![
        Box::new(ShellTool),
        Box::new(FileReadTool),
        Box::new(FileWriteTool),
        Box::new(WebSearchTool::new()),
        Box::new(HttpTool::new()),
        Box::new(VisionTool::new(&config.vision.ollama)),
        Box::new(ArxivFetchTool::new()),
        Box::new(ArxivSearchTool::new()),
        Box::new(PaperPdfTool::new()),
    ]
}

/// Format tool list as a JSON array string to inject into the system prompt.
pub fn format_tools_prompt(tools: &[Box<dyn Tool>]) -> String {
    let schemas: Vec<Value> = tools
        .iter()
        .map(|t| {
            serde_json::json!({
                "name": t.name(),
                "description": t.description(),
                "parameters": t.parameters_schema(),
            })
        })
        .collect();

    serde_json::to_string_pretty(&schemas).unwrap_or_default()
}
