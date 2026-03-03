import { renderMermaidSVG, THEMES } from '../node_modules/beautiful-mermaid/dist/index.js'
import { writeFileSync, mkdirSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = join(__dirname, '..', 'docs', 'diagrams')
mkdirSync(OUT, { recursive: true })

const theme = THEMES['catppuccin-mocha']

function save(name, diagram) {
  const svg = renderMermaidSVG(diagram, { theme })
  const path = join(OUT, `${name}.svg`)
  writeFileSync(path, svg)
  console.log(`  wrote ${path}`)
}

// ── 1. System Architecture ───────────────────────────────────────────────────
// Shows ZeroClaw as the tool execution layer between the Agent and its tools
save('architecture', `
flowchart TB
  subgraph UI["Web UI  •  :8420"]
    direction LR
    CHAT["💬 Chat"]
    VAULT["📚 Vault Viewer"]
    SPECS["📄 Specs"]
    CFG["⚙️ Model Config"]
  end

  subgraph AGENT["CV Zero Claw Agent  (agent.py)"]
    direction TB
    ORCH["Orchestrator\nrun_agent()"]
    HW["🔍 Hardware Probe\nllmfit"]
    ORCH <--> HW
  end

  subgraph ZC["ZeroClaw  (src/zeroclaw_tools/)"]
    direction LR
    CAGENT["create_agent()\nLangGraph ReAct"]
    TDEC["@tool decorator\nLangChain"]
    BUILTIN["shell · file_read\nweb_search · http_request"]
    CAGENT --> TDEC
  end

  subgraph TOOLS["CV Tools  (src/cv_agent/tools/)"]
    direction LR
    VIS["👁️ vision.py\nOllama / MLX"]
    PAPER["📥 paper_fetch.py\nArXiv / PWC"]
    SPEC["📋 spec_generator.py"]
    KG["🕸️ knowledge_graph.py"]
  end

  subgraph MODELS["Model Layer"]
    direction LR
    OLLAMA_VIS["Ollama VLM\nqwen2.5-vl · llava"]
    OLLAMA_LLM["Ollama LLM\nqwen2.5-coder"]
    MLX["MLX\nApple Silicon"]
  end

  UI -- "WebSocket /ws/chat" --> AGENT
  AGENT -- "uses" --> ZC
  ZC -- "@tool decorated" --> TOOLS
  ZC -- "built-in" --> BUILTIN
  TOOLS --> MODELS
  KG --> VAULT_FS[("Obsidian Vault\n.md files")]
  SPEC --> SPECS_FS[("output/specs/\n*.md")]
`)

// ── 2. ZeroClaw Integration Detail ──────────────────────────────────────────
// Explains the shim pattern, tool-calling flow, and upgrade path
save('zeroclaw_integration', `
flowchart TB
  subgraph NOW["Current: Local Shim"]
    direction TB
    SHIM["src/zeroclaw_tools/__init__.py\nCompatibility Shim"]
    SHIM --> LC["LangChain\ntool decorator + ChatOllama"]
    SHIM --> LG["LangGraph\nStateGraph ReAct loop"]
    LG --> REACT["Text-based ReAct\nbalanced-brace JSON extractor"]
    REACT --> EXEC["Tool Execution\nname + arguments → result"]
  end

  subgraph FUTURE["Future: Real Package"]
    direction TB
    PKG["zeroclaw-tools\nRust package on PyPI"]
    PKG --> NATIVE["Native tool_calls\nhigh-performance Rust runtime"]
  end

  subgraph TOOLS["Tools registered with @tool"]
    direction LR
    T1["pull_vision_model"]
    T2["check_runnable_models"]
    T3["search_arxiv"]
    T4["fetch_paper"]
    T5["generate_spec"]
    T6["shell / file_read\nweb_search / http_request"]
  end

  SHIM -- "registers" --> TOOLS
  SHIM -. "pip install zeroclaw-tools\ndelete src/zeroclaw_tools/" .-> PKG
  EXEC --> T1 & T2 & T3 & T4 & T5 & T6
`)

// ── 3. Research → Knowledge Pipeline ────────────────────────────────────────
save('research_pipeline', `
flowchart LR
  A(["🔎 Discover\nArXiv / PWC / S2"]) --> B["📥 Fetch Paper\nPDF + metadata"]
  B --> C["∑ Extract\nEquations + Arch"]
  C --> D["📋 Generate\nspec.md"]
  C --> E["🕸️ Add to\nKnowledge Graph"]
  E --> F(["📚 Obsidian\nVault"])
  D --> G(["output/specs/"])
  B --> H["👁️ Vision Model\nFigure Analysis"]
  H --> C
  E --> I["📰 Weekly\nDigest"]
  I --> J(["output/digests/"])
`)

// ── 4. Hardware-Aware Model Selection ───────────────────────────────────────
save('model_selection', `
flowchart TD
  START(["Agent Startup"]) --> PROBE["🔍 llmfit\nHardware Probe"]
  PROBE --> HW["Detect: RAM · VRAM\nCPU · Acceleration"]
  HW --> SCORE["Score ~200 Models\nperfect / good / marginal"]
  SCORE --> BEST["Select Best Fit\nfor multimodal + general"]
  BEST --> ZC["ZeroClaw create_agent()\nwith optimal model tag"]
  ZC --> PULL["ensure_ollama_model()\nauto-pull if not present"]
  PULL --> READY["Agent Ready"]
  PROBE -- "llmfit not\ninstalled" --> FALLBACK["Use .env /\nconfig defaults"]
  FALLBACK --> ZC
`)

console.log('\nAll diagrams generated in docs/diagrams/')
