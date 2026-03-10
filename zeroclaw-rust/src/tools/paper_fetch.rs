use anyhow::Context;
use async_trait::async_trait;
use chrono::{DateTime, NaiveDate, Utc};
use reqwest::Client;
use serde_json::{json, Value};
use tracing::debug;

use super::Tool;

const ARXIV_API_BASE: &str = "https://export.arxiv.org/api/query";

pub struct ArxivFetchTool {
    http: Client,
}

pub struct ArxivSearchTool {
    http: Client,
}

pub struct PaperPdfTool {
    http: Client,
}

impl ArxivFetchTool {
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

impl ArxivSearchTool {
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

impl PaperPdfTool {
    pub fn new() -> Self {
        Self {
            http: Client::builder()
                .user_agent("zeroclaw-agent/0.1")
                .timeout(std::time::Duration::from_secs(120))
                .redirect(reqwest::redirect::Policy::limited(5))
                .build()
                .expect("http client"),
        }
    }
}

/// Extract the ArXiv paper ID from a URL or return the raw string if already an ID.
fn extract_arxiv_id(url_or_id: &str) -> String {
    // Match patterns like arxiv.org/abs/2312.00785 or arxiv.org/pdf/2312.00785
    let patterns = [
        regex::Regex::new(r"arxiv\.org/abs/(\d{4}\.\d{4,5})").unwrap(),
        regex::Regex::new(r"arxiv\.org/pdf/(\d{4}\.\d{4,5})").unwrap(),
    ];
    for pat in &patterns {
        if let Some(cap) = pat.captures(url_or_id) {
            return cap[1].to_string();
        }
    }
    url_or_id.trim().to_string()
}

/// Parse Atom XML feed from ArXiv and return formatted entries as strings.
fn parse_arxiv_feed(xml: &str) -> Vec<String> {
    // We parse manually using string operations since pulling in a full XML lib
    // would add a heavy dependency. ArXiv Atom is well-structured enough.
    let mut entries: Vec<String> = vec![];
    let mut pos = 0;

    while let Some(start) = xml[pos..].find("<entry>") {
        let abs_start = pos + start;
        let Some(end_rel) = xml[abs_start..].find("</entry>") else {
            break;
        };
        let abs_end = abs_start + end_rel + "</entry>".len();
        let entry = &xml[abs_start..abs_end];

        let title = extract_tag(entry, "title")
            .unwrap_or_default()
            .replace('\n', " ");
        let summary = extract_tag(entry, "summary")
            .unwrap_or_default()
            .replace('\n', " ");
        let published = extract_tag(entry, "published").unwrap_or_default();
        let id_url = extract_tag(entry, "id").unwrap_or_default();
        let paper_id = id_url.split("/abs/").last()
            .unwrap_or("")
            .split('v')
            .next()
            .unwrap_or("")
            .trim()
            .to_string();

        // Extract authors
        let mut authors: Vec<String> = vec![];
        let mut author_pos = 0;
        while let Some(a_start) = entry[author_pos..].find("<author>") {
            let abs_a = author_pos + a_start;
            let Some(a_end_rel) = entry[abs_a..].find("</author>") else {
                break;
            };
            let author_block = &entry[abs_a..abs_a + a_end_rel + "</author>".len()];
            if let Some(name) = extract_tag(author_block, "name") {
                authors.push(name);
            }
            author_pos = abs_a + a_end_rel + "</author>".len();
        }

        let authors_str = if authors.len() > 5 {
            format!("{}, et al.", authors[..5].join(", "))
        } else {
            authors.join(", ")
        };

        let pub_date = &published[..published.len().min(10)];
        let abstract_short = if summary.len() > 300 {
            format!("{}...", &summary[..297])
        } else {
            summary.clone()
        };

        entries.push(format!(
            "**{title}**\n\
            ID: {paper_id} | Date: {pub_date}\n\
            Authors: {authors_str}\n\
            Abstract: {abstract_short}\n\
            URL: https://arxiv.org/abs/{paper_id}"
        ));

        pos = abs_end;
    }

    entries
}

fn extract_tag<'a>(xml: &'a str, tag: &str) -> Option<String> {
    let open = format!("<{tag}");
    let close = format!("</{tag}>");
    let start = xml.find(&open)?;
    // Find the end of the opening tag (could have attributes)
    let tag_end = xml[start..].find('>')?;
    let content_start = start + tag_end + 1;
    let end = xml[content_start..].find(&close)?;
    Some(xml[content_start..content_start + end].trim().to_string())
}

#[async_trait]
impl Tool for ArxivFetchTool {
    fn name(&self) -> &str {
        "fetch_arxiv_paper"
    }

    fn description(&self) -> &str {
        "Fetch metadata and abstract for a single ArXiv paper. \
        Accepts an ArXiv URL (https://arxiv.org/abs/XXXX.XXXXX) or paper ID. \
        Returns title, authors, abstract, categories, and links."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "arxiv_url_or_id": {
                    "type": "string",
                    "description": "ArXiv paper URL or ID (e.g. '2312.00785' or 'https://arxiv.org/abs/2312.00785')"
                }
            },
            "required": ["arxiv_url_or_id"]
        })
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let input = args["arxiv_url_or_id"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'arxiv_url_or_id'"))?;

        let paper_id = extract_arxiv_id(input);
        debug!("fetch_arxiv_paper: {}", paper_id);

        let resp = self
            .http
            .get(ARXIV_API_BASE)
            .query(&[("id_list", &paper_id)])
            .send()
            .await
            .context("ArXiv API request")?;

        let xml = resp.text().await.context("reading ArXiv response")?;
        let entries = parse_arxiv_feed(&xml);

        if entries.is_empty() {
            return Ok(format!("No paper found for ID: {paper_id}"));
        }

        Ok(format!(
            "# ArXiv Paper: {paper_id}\n\n{}\n\nPDF: https://arxiv.org/pdf/{paper_id}.pdf",
            entries[0]
        ))
    }
}

#[async_trait]
impl Tool for ArxivSearchTool {
    fn name(&self) -> &str {
        "search_arxiv"
    }

    fn description(&self) -> &str {
        "Search ArXiv for papers matching a query in computer vision categories. \
        Returns a formatted list of matching papers with titles, authors, and abstracts."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'object detection transformer')"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default 10)",
                    "default": 10
                },
                "categories": {
                    "type": "string",
                    "description": "Comma-separated ArXiv categories (default: cs.CV)",
                    "default": "cs.CV"
                },
                "days_back": {
                    "type": "integer",
                    "description": "Only include papers from the last N days (default 30)",
                    "default": 30
                }
            },
            "required": ["query"]
        })
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let query = args["query"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'query'"))?;
        let max_results = args["max_results"].as_u64().unwrap_or(10).min(100);
        let categories = args["categories"].as_str().unwrap_or("cs.CV");
        let days_back = args["days_back"].as_u64().unwrap_or(30);

        debug!("search_arxiv: query='{}' days_back={}", query, days_back);

        let cat_list: Vec<String> = categories.split(',').map(|s| format!("cat:{}", s.trim())).collect();
        let cat_query = cat_list.join(" OR ");
        let full_query = format!("({query}) AND ({cat_query})");

        let resp = self
            .http
            .get(ARXIV_API_BASE)
            .query(&[
                ("search_query", full_query.as_str()),
                ("max_results", &max_results.to_string()),
                ("sortBy", "submittedDate"),
                ("sortOrder", "descending"),
            ])
            .send()
            .await
            .context("ArXiv search request")?;

        let xml = resp.text().await.context("reading ArXiv search response")?;
        let all_entries = parse_arxiv_feed(&xml);

        // Filter by date
        let cutoff = Utc::now() - chrono::Duration::days(days_back as i64);
        let cutoff_date = cutoff.format("%Y-%m-%d").to_string();

        let mut filtered: Vec<String> = vec![];
        for (i, entry) in all_entries.into_iter().enumerate() {
            // Extract date from second line "ID: XXXX | Date: YYYY-MM-DD"
            let date_str = entry
                .lines()
                .find(|l| l.starts_with("ID:"))
                .and_then(|l| l.split("Date:").nth(1))
                .map(|s| s.trim().to_string())
                .unwrap_or_default();

            if !date_str.is_empty() && date_str < cutoff_date {
                continue;
            }

            filtered.push(format!("### {}. {}", i + 1, entry));
        }

        if filtered.is_empty() {
            return Ok(format!(
                "No recent papers (last {days_back} days) found for: {query}"
            ));
        }

        Ok(format!(
            "# ArXiv Search: \"{query}\"\n**Found {} papers in the last {days_back} days**\n\n{}",
            filtered.len(),
            filtered.join("\n\n---\n\n")
        ))
    }
}

#[async_trait]
impl Tool for PaperPdfTool {
    fn name(&self) -> &str {
        "fetch_paper_pdf"
    }

    fn description(&self) -> &str {
        "Download the PDF of an ArXiv paper to disk. \
        Returns the local path and file size."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "arxiv_url_or_id": {
                    "type": "string",
                    "description": "ArXiv URL or paper ID"
                },
                "save_path": {
                    "type": "string",
                    "description": "Where to save the PDF (default: papers/<id>.pdf)"
                }
            },
            "required": ["arxiv_url_or_id"]
        })
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let input = args["arxiv_url_or_id"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'arxiv_url_or_id'"))?;

        let paper_id = extract_arxiv_id(input);
        let safe_id = paper_id.replace('/', "_");
        let pdf_url = format!("https://arxiv.org/pdf/{paper_id}.pdf");

        let save_path = args["save_path"]
            .as_str()
            .map(|s| s.to_string())
            .unwrap_or_else(|| format!("papers/{safe_id}.pdf"));

        debug!("fetch_paper_pdf: {} -> {}", pdf_url, save_path);

        let target = std::path::Path::new(&save_path);
        if let Some(parent) = target.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }

        let resp = self
            .http
            .get(&pdf_url)
            .send()
            .await
            .context("PDF download request")?;

        let status = resp.status();
        if !status.is_success() {
            return Err(anyhow::anyhow!("PDF download failed {status}"));
        }

        let bytes = resp.bytes().await.context("reading PDF bytes")?;
        tokio::fs::write(&save_path, &bytes).await?;

        let size_mb = bytes.len() as f64 / (1024.0 * 1024.0);
        Ok(format!("Downloaded: {save_path} ({size_mb:.1} MB)"))
    }
}
