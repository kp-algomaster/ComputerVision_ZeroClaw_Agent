# CV Zero Claw Agent 🦀👁️

An autonomous Computer Vision research agent powered by [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw). Stays current with CV research, processes papers, builds knowledge graphs, and generates spec-driven development files.

## Features

- **Vision Model Integration** — Run Ollama models (Qwen2.5-VL, LLaVA, etc.) and MLX-accelerated models for CV tasks
- **Research Monitor** — Auto-tracks ArXiv, Papers With Code, and Semantic Scholar for latest CV research
- **Weekly Magazine** — Generates curated weekly digest/blog of new CV breakthroughs
- **Knowledge Graphs** — Builds Obsidian-compatible knowledge vaults linking papers, methods, datasets, and concepts
- **Paper → Spec Pipeline** — Extracts equations, architectures, and key findings from papers into `spec.md` files for spec-driven development
- **Secure Local Access** — Uses ZeroClaw for sandboxed file system and internet access

## Architecture

```
┌─────────────────────────────────────────────────────┐
│               CV Zero Claw Agent                    │
├─────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Research  │  │Knowledge │  │   Spec Generator │  │
│  │ Monitor   │  │  Graph   │  │   (paper→spec)   │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │              │                 │             │
│  ┌────┴──────────────┴─────────────────┴─────────┐  │
│  │            Tool Layer (ZeroClaw)               │  │
│  │  vision │ paper_fetch │ equation │ kg │ spec   │  │
│  └────────────────────┬──────────────────────────┘  │
│                       │                             │
│  ┌────────────────────┴──────────────────────────┐  │
│  │         Model Layer                           │  │
│  │  Ollama (Qwen2.5-VL) │ MLX (Apple Silicon)   │  │
│  └───────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│         ZeroClaw Runtime (Rust + LangGraph)         │
└─────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw) installed (`brew install zeroclaw`)
- [Ollama](https://ollama.ai) running locally with a vision model
- macOS with Apple Silicon (for MLX acceleration, optional)

### Setup

```bash
# Clone and install
cd CV_Zero_Claw_Agent
./scripts/setup.sh

# Or manual install
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Pull a vision model
ollama pull qwen2.5-vl:7b

# Configure
cp .env.example .env
# Edit .env with your API keys
```

### Usage

```bash
# Activate environment
source .venv/bin/activate

# Launch the Web UI (chat + content viewer)
cv-agent ui
# Opens at http://127.0.0.1:8420

# Or start terminal interactive mode
cv-agent start

# Process a specific paper
cv-agent paper https://arxiv.org/abs/2312.00785 --spec

# Generate weekly digest
cv-agent digest --week

# Analyze an image with vision model
cv-agent vision analyze path/to/image.png

# Build/update knowledge graph
cv-agent knowledge sync

# Interactive mode
cv-agent chat
```

## Project Structure

```
├── src/cv_agent/
│   ├── agent.py              # Main agent orchestrator
│   ├── cli.py                # Click CLI entry point
│   ├── web.py                # FastAPI web server
│   ├── config.py             # Pydantic config loader
│   ├── ui/                   # Web UI frontend
│   │   ├── index.html        # Single-page app shell
│   │   ├── style.css         # Dark-theme styles
│   │   └── app.js            # Frontend logic (chat, viewers)
│   ├── tools/                # ZeroClaw custom tools
│   │   ├── vision.py         # Ollama vision model tools
│   │   ├── mlx_vision.py     # MLX-accelerated vision
│   │   ├── paper_fetch.py    # ArXiv/paper fetching
│   │   ├── equation_extract.py  # Equation extraction
│   │   ├── knowledge_graph.py   # Knowledge graph builder
│   │   └── spec_generator.py    # spec.md generation
│   ├── research/             # Research monitoring
│   │   ├── monitor.py        # Source monitoring
│   │   ├── digest.py         # Weekly digest generator
│   │   └── sources.py        # Research sources config
│   └── knowledge/            # Knowledge management
│       ├── graph.py          # Graph core logic
│       └── obsidian.py       # Obsidian vault integration
├── templates/                # Jinja2 templates
├── vault/                    # Obsidian knowledge vault
├── output/                   # Generated outputs
├── config/                   # Configuration files
└── scripts/                  # Utility scripts
```

## Configuration

See [config/agent_config.yaml](config/agent_config.yaml) for full configuration options.

Key environment variables in `.env`:
- `OLLAMA_HOST` — Ollama server URL (default: `http://localhost:11434`)
- `OLLAMA_VISION_MODEL` — Default vision model (default: `qwen2.5-vl:7b`)
- `ARXIV_CATEGORIES` — ArXiv categories to monitor (default: `cs.CV,cs.AI,cs.LG`)
- `SEMANTIC_SCHOLAR_API_KEY` — Optional Semantic Scholar API key
- `BRAVE_API_KEY` — For web search via ZeroClaw

## License

MIT
