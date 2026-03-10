use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::fs;
use tracing::debug;

use super::Tool;

pub struct FileReadTool;
pub struct FileWriteTool;

#[async_trait]
impl Tool for FileReadTool {
    fn name(&self) -> &str {
        "file_read"
    }

    fn description(&self) -> &str {
        "Read the contents of a file from disk. \
        Returns the file text (max 64 KB). \
        Use to inspect source files, configs, or saved research outputs."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file"
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to read (default 65536)",
                    "default": 65536
                }
            },
            "required": ["path"]
        })
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let path = args["path"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'path' argument"))?;

        let max_bytes = args["max_bytes"].as_u64().unwrap_or(65536) as usize;
        debug!("file_read: {}", path);

        let bytes = fs::read(path)
            .await
            .map_err(|e| anyhow::anyhow!("cannot read {path}: {e}"))?;

        let truncated = &bytes[..bytes.len().min(max_bytes)];
        let text = String::from_utf8_lossy(truncated).into_owned();

        if bytes.len() > max_bytes {
            Ok(format!("{text}\n\n[... truncated at {max_bytes} bytes ...]"))
        } else {
            Ok(text)
        }
    }
}

#[async_trait]
impl Tool for FileWriteTool {
    fn name(&self) -> &str {
        "file_write"
    }

    fn description(&self) -> &str {
        "Write content to a file on disk. Creates parent directories as needed. \
        Use to save research outputs, diagrams, or generated code."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to write"
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write"
                },
                "append": {
                    "type": "boolean",
                    "description": "If true, append to file instead of overwriting",
                    "default": false
                }
            },
            "required": ["path", "content"]
        })
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let path = args["path"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'path' argument"))?;
        let content = args["content"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'content' argument"))?;
        let append = args["append"].as_bool().unwrap_or(false);

        debug!("file_write: {} ({} bytes, append={})", path, content.len(), append);

        let target = std::path::Path::new(path);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).await?;
        }

        if append {
            use tokio::io::AsyncWriteExt;
            let mut file = fs::OpenOptions::new()
                .append(true)
                .create(true)
                .open(path)
                .await
                .map_err(|e| anyhow::anyhow!("cannot open {path} for append: {e}"))?;
            file.write_all(content.as_bytes()).await?;
        } else {
            fs::write(path, content.as_bytes())
                .await
                .map_err(|e| anyhow::anyhow!("cannot write {path}: {e}"))?;
        }

        Ok(format!("Written {} bytes to {}", content.len(), path))
    }
}
