# CV Zero Claw Agent 🦀👁️

An autonomous Computer Vision research agent that monitors arXiv, processes papers, builds knowledge graphs, and generates spec-driven development files. Powered by [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw).

## Features

- **Vision Model Integration** — Run Ollama models (Qwen2.5-VL, LLaVA, etc.) and MLX-accelerated models for CV tasks
- **Hardware-Aware Model Selection** — Uses [llmfit](https://github.com/AlexsJones/llmfit) at startup to pick the best locally-runnable model for your hardware
- **Research Monitor** — Auto-tracks ArXiv, Papers With Code, and Semantic Scholar for latest CV research
- **Weekly Magazine** — Generates curated weekly digest/blog of new CV breakthroughs
- **Knowledge Graphs** — Builds Obsidian-compatible knowledge vaults linking papers, methods, datasets, and concepts
- **Paper → Spec Pipeline** — Extracts equations, architectures, and key findings from papers into `spec.md` files for spec-driven development
- **Web UI** — FastAPI + WebSocket chat interface at `http://localhost:8420`

## How ZeroClaw is Used

ZeroClaw is the **tool execution layer** between the agent orchestrator and the CV tools. It provides:

| ZeroClaw API | What it does in this project |
|---|---|
| `@tool` decorator | Marks Python functions as agent-callable tools (`pull_vision_model`, `search_arxiv`, `generate_spec`, etc.) |
| `create_agent(tools, model)` | Builds the LangGraph ReAct loop that drives the agent's reasoning and tool dispatch |
| Built-in tools | `shell`, `file_read`, `file_write`, `web_search`, `http_request` — used by the agent during research tasks |

**Current status:** The `zeroclaw-tools` Rust package is not yet on PyPI. A local compatibility shim at `src/zeroclaw_tools/__init__.py` provides the identical API surface using LangChain + LangGraph. When the real package ships:

```bash
pip install zeroclaw-tools
rm -rf src/zeroclaw_tools/   # shim no longer needed — zero other changes required
```

The shim also includes a **text-based ReAct fallback**: models like `qwen2.5-coder` that don't emit native `tool_calls` output JSON as plain text. The shim's balanced-brace scanner extracts and executes those calls transparently.

![ZeroClaw Integration](docs/diagrams/zeroclaw_integration.svg)

## System Architecture

ZeroClaw sits between the agent orchestrator and all tool-decorated functions:

![System Architecture](docs/diagrams/architecture.svg)

## Research → Knowledge Pipeline

![Research Pipeline](docs/diagrams/research_pipeline.svg)

## Hardware-Aware Model Selection

At startup, llmfit probes your hardware and ZeroClaw's `create_agent()` is called with the optimal model:

![Model Selection](docs/diagrams/model_selection.svg)

> Diagrams rendered with [beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid) (catppuccin-mocha theme).
> Regenerate: `node scripts/generate_diagrams.mjs`

## Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) running locally with a vision model
- macOS with Apple Silicon (for MLX acceleration, optional)
- [llmfit](https://github.com/AlexsJones/llmfit) for hardware-aware model selection (optional): `brew install llmfit`

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

# Launch the Web UI (chat + content viewer + model management)
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
│   │   └── app.js            # Frontend logic (chat, viewers, model management)
│   ├── tools/                # ZeroClaw @tool-decorated functions
│   │   ├── vision.py         # Ollama vision model tools
│   │   ├── mlx_vision.py     # MLX-accelerated vision
│   │   ├── paper_fetch.py    # ArXiv/paper fetching
│   │   ├── equation_extract.py  # Equation extraction
│   │   ├── knowledge_graph.py   # Knowledge graph builder
│   │   ├── spec_generator.py    # spec.md generation
│   │   └── hardware_probe.py    # llmfit hardware detection + Ollama model management
│   ├── research/             # Research monitoring
│   │   ├── monitor.py        # Source monitoring
│   │   ├── digest.py         # Weekly digest generator
│   │   └── sources.py        # Research sources config
│   └── knowledge/            # Knowledge management
│       ├── graph.py          # Graph core logic
│       └── obsidian.py       # Obsidian vault integration
├── src/zeroclaw_tools/       # ZeroClaw compatibility shim (delete when pkg ships on PyPI)
│   └── __init__.py           # @tool, create_agent(), shell, file_read, web_search, http_request
├── docs/diagrams/            # Generated SVG diagrams
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
- `LLM_MODEL` — LLM model tag (default: `qwen2.5:7b`)
- `OLLAMA_VISION_MODEL` — Vision model tag (default: `qwen2.5-vl:7b`)
- `ARXIV_CATEGORIES` — ArXiv categories to monitor (default: `cs.CV,cs.AI,cs.LG`)
- `SEMANTIC_SCHOLAR_API_KEY` — Optional Semantic Scholar API key

## License

MIT
