mod agent;
mod config;
mod llm;
mod tools;
mod web;

use std::sync::Arc;

use anyhow::Context;
use clap::{Parser, Subcommand};
use tracing::{info, warn};
use tracing_subscriber::{EnvFilter, fmt};

use agent::Agent;
use config::AgentConfig;

#[derive(Parser)]
#[command(
    name = "zeroclaw",
    about = "CV Zero Claw — autonomous computer vision research agent",
    version
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Launch the web UI (WebSocket + REST API)
    Ui {
        /// Port to listen on
        #[arg(short, long, default_value_t = 8420)]
        port: u16,
    },
    /// Interactive CLI chat session
    Start,
    /// Fetch and summarise an ArXiv paper
    Paper {
        /// ArXiv URL or ID (e.g. https://arxiv.org/abs/2312.00785 or 2312.00785)
        url: String,
    },
    /// Search ArXiv for papers
    Search {
        /// Search query
        query: String,
        /// Number of results
        #[arg(short = 'n', long, default_value_t = 10)]
        max_results: u32,
        /// Days back to search
        #[arg(short, long, default_value_t = 30)]
        days: u32,
    },
}

fn init_logging(log_level: &str) {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(log_level));

    fmt()
        .with_env_filter(filter)
        .with_target(false)
        .compact()
        .init();
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load .env file if present
    let _ = dotenvy::dotenv();

    let cli = Cli::parse();

    let config = AgentConfig::load().unwrap_or_else(|e| {
        eprintln!("Config load error ({e}), using defaults");
        AgentConfig::default()
    });

    init_logging(&config.log_level);
    info!("CV Zero Claw starting — model: {}", config.llm.model);

    match cli.command {
        Command::Ui { port } => {
            let agent = Arc::new(Agent::new(config).context("creating agent")?);
            web::serve(agent, port).await?;
        }

        Command::Start => {
            run_interactive(config).await?;
        }

        Command::Paper { url } => {
            let agent = Agent::new(config).context("creating agent")?;
            let prompt = format!(
                "Fetch and analyse this paper, covering: title, authors, problem statement, \
                key contributions, methodology, results, and limitations.\n\nPaper: {url}"
            );
            let result = agent.run(&prompt, &[]).await?;
            println!("{result}");
        }

        Command::Search { query, max_results, days } => {
            let agent = Agent::new(config).context("creating agent")?;
            let prompt = format!(
                "Search ArXiv for '{query}' in the last {days} days (max_results={max_results}) \
                and summarise the most significant papers."
            );
            let result = agent.run(&prompt, &[]).await?;
            println!("{result}");
        }
    }

    Ok(())
}

/// Interactive CLI chat loop.
async fn run_interactive(config: AgentConfig) -> anyhow::Result<()> {
    use std::io::{self, BufRead, Write};
    use futures_util::StreamExt;

    let agent = Agent::new(config).context("creating agent")?;
    let mut history: Vec<llm::Message> = vec![];

    println!("CV Zero Claw Agent — Interactive Mode");
    println!("Type 'quit' or 'exit' to quit, 'clear' to reset history.\n");

    let stdin = io::stdin();
    loop {
        print!("\x1b[36myou>\x1b[0m ");
        io::stdout().flush()?;

        let mut line = String::new();
        match stdin.lock().read_line(&mut line) {
            Ok(0) => break, // EOF
            Ok(_) => {}
            Err(e) => {
                eprintln!("Read error: {e}");
                break;
            }
        }

        let input = line.trim().to_string();
        if input.is_empty() {
            continue;
        }

        match input.as_str() {
            "quit" | "exit" | "q" => break,
            "clear" => {
                history.clear();
                println!("History cleared.\n");
                continue;
            }
            "help" => {
                println!(
                    "Commands:\n  quit/exit — exit\n  clear — reset conversation history\n\
                    \nExample queries:\n\
                    - What are the latest vision transformer papers?\n\
                    - Fetch paper 2312.00785\n\
                    - Analyse image /path/to/image.png\n"
                );
                continue;
            }
            _ => {}
        }

        // Stream response
        let stream_result = agent.run_stream(&input, &history).await;
        let mut stream = match stream_result {
            Ok(s) => s,
            Err(e) => {
                eprintln!("\x1b[31mError:\x1b[0m {e}");
                continue;
            }
        };

        print!("\n\x1b[33magent>\x1b[0m ");
        io::stdout().flush()?;

        let mut final_content = String::new();
        tokio::pin!(stream);

        while let Some(event) = stream.next().await {
            match event {
                agent::AgentEvent::StreamToken { content } => {
                    print!("{content}");
                    io::stdout().flush()?;
                }
                agent::AgentEvent::ToolStart { name, input } => {
                    print!("\n\x1b[90m[tool: {name}({})]\x1b[0m\n", &input[..input.len().min(80)]);
                    io::stdout().flush()?;
                }
                agent::AgentEvent::ToolEnd { name, output: _ } => {
                    print!("\x1b[90m[{name} done]\x1b[0m ");
                    io::stdout().flush()?;
                }
                agent::AgentEvent::Done { content } => {
                    final_content = content;
                }
                agent::AgentEvent::Error { message } => {
                    eprintln!("\n\x1b[31mError:\x1b[0m {message}");
                }
            }
        }

        println!("\n");

        // Update conversation history
        history.push(llm::Message::user(&input));
        if !final_content.is_empty() {
            history.push(llm::Message::assistant(&final_content));
        }

        // Trim history to avoid exceeding context limits (~32 turns)
        if history.len() > 64 {
            history.drain(0..2);
        }
    }

    println!("Goodbye!");
    Ok(())
}
