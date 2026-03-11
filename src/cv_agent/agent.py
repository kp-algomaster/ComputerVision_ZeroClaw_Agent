"""Main CV Agent orchestrator — ties ZeroClaw tools into an autonomous CV research agent."""

from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from zeroclaw_tools import create_agent, shell, file_read, file_write, web_search, http_request, tool

from cv_agent._history import trim_history
from cv_agent.config import AgentConfig, OllamaConfig, load_config
from cv_agent.agents import (
    run_blog_writer_agent,
    run_website_maintenance_agent,
    run_model_training_agent,
    run_data_visualization_agent,
    run_paper_to_code_agent,
    run_digest_agent,
)
from cv_agent.tools.vision import analyze_image, describe_image, compare_images
from cv_agent.tools.mlx_vision import mlx_analyze_image
from cv_agent.tools.paper_fetch import fetch_arxiv_paper, search_arxiv, fetch_paper_pdf
from cv_agent.tools.equation_extract import extract_equations, extract_key_info
from cv_agent.tools.knowledge_graph import add_paper_to_graph, query_graph, export_graph
from cv_agent.tools.spec_generator import generate_spec, generate_spec_from_url
from cv_agent.tools.text_to_diagram import text_to_diagram
from cv_agent.tools.segment_anything import segment_with_text, segment_with_box, segment_video
from cv_agent.tools.ocr import run_ocr
from cv_agent.tools.labelling import (
    start_labelling_server,
    create_labelling_project,
    list_labelling_projects,
    export_annotations,
    create_labelling_dag_node,
)
from cv_agent.tools.hardware_probe import (
    check_runnable_models,
    list_available_models,
    pull_vision_model,
    ensure_ollama_model,
    select_best_ollama_model,
    get_runnable_models,
)

logger = logging.getLogger(__name__)


def _make_delegation_tools(config: AgentConfig) -> list:
    """Build @tool wrappers that let the main agent delegate to sub-agents."""
    delegation: list = []

    if config.agents.blog_writer.enabled:
        @tool
        def delegate_blog_writer(task: str) -> str:
            """Delegate a blog writing task to the Blog Writer Agent.

            Use when the user asks to write, draft, or publish a research blog post.
            Args:
                task: The blog writing instruction or topic.
            """
            return asyncio.run(run_blog_writer_agent(task, config))
        delegation.append(delegate_blog_writer)

    if config.agents.website_maintenance.enabled:
        @tool
        def delegate_website_maintenance(task: str) -> str:
            """Delegate a website audit task to the Website Maintenance Agent.

            Use for checking broken links, site health, uptime, or SEO.
            Args:
                task: The website audit instruction, including URL(s) to check.
            """
            return asyncio.run(run_website_maintenance_agent(task, config))
        delegation.append(delegate_website_maintenance)

    if config.agents.model_training.enabled:
        @tool
        def delegate_model_training(task: str) -> str:
            """Delegate a training setup task to the Model Training Agent.

            Use for generating training configs, cost estimates, or training scripts.
            Args:
                task: The training task description (model, dataset, framework).
            """
            return asyncio.run(run_model_training_agent(task, config))
        delegation.append(delegate_model_training)

    if config.agents.data_visualization.enabled:
        @tool
        def delegate_data_visualization(task: str) -> str:
            """Delegate a visualization task to the Data Visualization Agent.

            Use for generating charts, extracting paper result tables, or plotting data.
            Args:
                task: The visualization request or paper to extract metrics from.
            """
            return asyncio.run(run_data_visualization_agent(task, config))
        delegation.append(delegate_data_visualization)

    if config.agents.paper_to_code.enabled:
        @tool
        def delegate_paper_to_code(task: str) -> str:
            """Delegate a paper implementation task to the Paper to Code Agent.

            Use when the user wants to implement a research paper in PyTorch.
            Args:
                task: The paper URL/ID or implementation instruction.
            """
            return asyncio.run(run_paper_to_code_agent(task, config))
        delegation.append(delegate_paper_to_code)

    if config.agents.digest_writer.enabled:
        @tool
        def delegate_digest_writer(task: str) -> str:
            """Delegate a digest generation task to the Digest Writer Agent.

            Use when the user asks to generate, write, or create a weekly CV research digest.
            Args:
                task: The digest instruction (e.g. "generate this week's CV digest").
            """
            return asyncio.run(run_digest_agent(task, config))
        delegation.append(delegate_digest_writer)

    return delegation


def _strip_leading_tool_calls(text: str) -> str:
    """Strip JSON tool-call objects prepended to model text output.

    When _MAX_TOOL_ROUNDS is hit the LLM sometimes outputs:
      '{"name": "tool", "arguments": {...}}\n\nSorry, I could not...'
    This strips all leading tool-call JSON objects and returns the trailing text.
    Uses json.JSONDecoder.raw_decode so nested objects are handled correctly.
    """
    text = text.strip()
    decoder = _json.JSONDecoder()
    while text.startswith("{"):
        try:
            obj, end_idx = decoder.raw_decode(text)
            if isinstance(obj, dict) and "name" in obj:
                text = text[end_idx:].strip()
            else:
                break
        except (_json.JSONDecodeError, ValueError):
            break
    return text


SYSTEM_PROMPT = """\
You are an expert Computer Vision research agent with live access to ArXiv, \
Papers With Code, and the web via your tools.

═══════════════════════════════════════════════════════
MANDATORY TOOL-USE POLICY — READ CAREFULLY
═══════════════════════════════════════════════════════
You MUST use tools for every research and paper question. NEVER answer from \
training data or prior knowledge when current information is needed.

• ANY question about "latest", "recent", "last month/week/year", "what's \
  happening", "trending", "new papers", "current state" in CV → call \
  `search_arxiv` FIRST (days_back=30 or 7 as appropriate), then summarise \
  the actual results you received.

• ANY question about a specific paper → call `fetch_arxiv_paper` with the ID \
  or URL before answering anything.

• ANY vision/image task → call `pull_vision_model` then the appropriate \
  vision tool.

• If unsure whether a tool will help — use the tool. Your value comes from \
  real, live results, not memorised facts.

EXAMPLE — user asks "what's new in vision transformers?":
  Step 1: {"name": "search_arxiv", "arguments": {"query": "vision transformer", "days_back": 30, "max_results": 10}}
  Step 2: {"name": "search_arxiv", "arguments": {"query": "ViT efficient self-supervised", "days_back": 30}}
  Step 3: Summarise the papers you actually retrieved.

DO NOT produce a text answer before calling at least one tool for any research \
question. Answering "as an AI I don't have access to current events" is WRONG — \
you have `search_arxiv` and `web_search` and must use them.
═══════════════════════════════════════════════════════

Capabilities:

0. **Hardware-Aware Model Selection**: Use `check_runnable_models` / \
`list_available_models` / `pull_vision_model` to manage Ollama models. \
Always pull the right model before any vision task.

1. **Vision Analysis**: Analyze images via Qwen2.5-VL, LLaVA (Ollama) or \
MLX-accelerated models on Apple Silicon.

2. **Research Monitoring**: Live search of ArXiv, Papers With Code, and the \
web. You understand deep learning architectures, loss functions, training \
strategies, and evaluation metrics.

3. **Paper Processing**: Fetch papers, extract LaTeX equations, architectural \
details, training configurations, and experimental results.

4. **Knowledge Graphs**: Build and maintain an Obsidian-compatible vault \
linking papers, methods, datasets, architectures, and concepts.

5. **Spec Generation**: Convert papers into structured spec.md files for \
spec-driven development — equations, architecture, implementation requirements.

6. **Weekly Digest**: Generate comprehensive weekly magazine posts covering \
the latest CV breakthroughs.

7. **Sub-Agent Delegation**: Delegate specialized tasks to focused agents:
   - `delegate_blog_writer` — write research blog posts
   - `delegate_website_maintenance` — audit sites for broken links, SEO, health
   - `delegate_model_training` — generate training configs, scripts, cost estimates
   - `delegate_data_visualization` — generate charts and extract paper metrics
   - `delegate_paper_to_code` — scaffold PyTorch implementations from ArXiv papers
   - `delegate_digest_writer` — generate magazine-style weekly CV research digests

When synthesising results from tools:
- Lead with the most impactful / novel findings
- Extract core contributions, mathematical formulations, and datasets
- Note comparison baselines and practical implementability
- Link related work where relevant
"""


def build_tools(config: AgentConfig) -> list:
    """Assemble the full tool list for the CV agent."""
    tools = [
        # ZeroClaw built-in tools
        shell,
        file_read,
        file_write,
        web_search,
        http_request,
        # Hardware probe + Ollama model management
        check_runnable_models,
        list_available_models,
        pull_vision_model,
        # CV-specific tools
        analyze_image,
        describe_image,
        compare_images,
        fetch_arxiv_paper,
        search_arxiv,
        fetch_paper_pdf,
        extract_equations,
        extract_key_info,
        add_paper_to_graph,
        query_graph,
        export_graph,
        generate_spec,
        generate_spec_from_url,
        text_to_diagram,
        # SAM3 segmentation
        segment_with_text,
        segment_with_box,
        segment_video,
        # PaddleOCR
        run_ocr,
        # Label Studio labelling
        start_labelling_server,
        create_labelling_project,
        list_labelling_projects,
        export_annotations,
        create_labelling_dag_node,
    ]

    # Add MLX tools if available on Apple Silicon
    if config.vision.mlx.enabled:
        tools.append(mlx_analyze_image)

    # Add sub-agent delegation tools
    tools.extend(_make_delegation_tools(config))

    return tools


def apply_hardware_probe(config: AgentConfig) -> AgentConfig:
    """Run llmfit and update config.llm.model / vision model with best local fits.

    Only runs when config.llmfit.enabled and config.llmfit.auto_select_model are True.
    Updates are applied in-place on a copy of the config to avoid mutating the original.
    """
    if not (config.llmfit.enabled and config.llmfit.auto_select_model):
        return config

    logger.info("Running hardware probe via llmfit...")
    try:
        vision_models = get_runnable_models(
            use_case=config.llmfit.vision_use_case,
            min_fit=config.llmfit.min_fit,
            limit=5,
        )
        general_models = get_runnable_models(
            use_case=config.llmfit.general_use_case,
            min_fit=config.llmfit.min_fit,
            limit=5,
        )

        best_vision = select_best_ollama_model(vision_models)
        best_general = select_best_ollama_model(general_models)

        # Use model_copy (Pydantic v2) to avoid mutating the shared config
        updates: dict = {}
        _ollama_default = OllamaConfig.model_fields["default_model"].default
        if best_vision and config.vision.ollama.default_model == _ollama_default:
            logger.info("llmfit recommends vision model: %s", best_vision)
            updates["vision"] = config.vision.model_copy(
                update={"ollama": config.vision.ollama.model_copy(update={"default_model": best_vision})}
            )
            _, pull_msg = ensure_ollama_model(best_vision, config.vision.ollama.host)
            logger.info(pull_msg)
        if best_general:
            logger.info("llmfit recommends LLM model: %s", best_general)
            updates["llm"] = config.llm.model_copy(update={"model": best_general})
            _, pull_msg = ensure_ollama_model(best_general, config.vision.ollama.host)
            logger.info(pull_msg)

        if updates:
            return config.model_copy(update=updates)
    except Exception as exc:
        logger.warning("Hardware probe failed, using config defaults: %s", exc)

    return config


def _prepare_agent(config: AgentConfig, message: str, history: list[Any] | None = None):
    """Shared setup for run_agent and run_agent_stream."""
    config = apply_hardware_probe(config)
    tools = build_tools(config)
    agent = create_agent(
        tools=tools,
        model=config.llm.model,
        api_key=config.llm.api_key or None,
        base_url=config.llm.base_url,
    )
    messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
    if history:
        messages.extend(trim_history(list(history), config.cache.max_history_chars))
    messages.append(HumanMessage(content=message))
    return agent, messages


async def run_agent(
    message: str,
    config: AgentConfig | None = None,
    history: list[Any] | None = None,
) -> str:
    """Run the CV agent with a user message and return the response."""
    if config is None:
        config = load_config()

    agent, messages = _prepare_agent(config, message, history)
    result = await agent.ainvoke({"messages": messages})
    return result["messages"][-1].content


async def run_agent_stream(
    message: str,
    config: AgentConfig | None = None,
    history: list[Any] | None = None,
):
    """Async generator that yields streaming events from the agent.

    Yields dicts with 'type' key:
      - {"type": "token", "content": "..."}
      - {"type": "tool_start", "name": "...", "input": "..."}
      - {"type": "tool_end", "name": "...", "output": "..."}
      - {"type": "done", "content": "..."}
    """
    if config is None:
        config = load_config()

    agent, messages = _prepare_agent(config, message, history)
    full_content = ""
    last_tool_name = ""
    final_answer = ""
    _in_tool_phase = False  # True while tools are being called
    _token_buffer = ""

    async for event in agent.astream_events(
        {"messages": messages}, version="v2"
    ):
        kind = event.get("event", "")

        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                token = chunk.content
                if not isinstance(token, str):
                    continue

                # Buffer tokens to detect if the model is starting a JSON tool call
                # (e.g., '{"name": "..."}'). We don't want to stream this raw JSON to the UI.
                _token_buffer += token

                # If the buffer strictly starts with something that looks like the beginning
                # of our tool call format, wait for more tokens.
                if '{"name"'.startswith(_token_buffer.strip()) or _token_buffer.strip().startswith('{"name"'):
                    # It's a tool call (or we're still waiting to find out)
                    continue
                else:
                    # It's normal text. Flush the buffer and append.
                    text_to_yield = _token_buffer
                    _token_buffer = ""
                
                # If this is the first real text after the tool phase, clear old output
                if _in_tool_phase:
                    full_content = ""
                    _in_tool_phase = False
                
                full_content += text_to_yield
                yield {"type": "token", "content": text_to_yield}

        elif kind == "on_chat_model_end":
            # Capture the full model response at the end of each LLM call.
            # This is the reliable fallback when streaming tokens are missed.
            data_output = event.get("data", {}).get("output")
            if data_output and hasattr(data_output, "content"):
                content = data_output.content
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    )
                if isinstance(content, str) and content.strip():
                    clean_text = _strip_leading_tool_calls(content)
                    if clean_text:
                        final_answer = clean_text

        elif kind == "on_tool_start":
            name = event.get("name", "")
            last_tool_name = name
            _in_tool_phase = True
            # Discard any buffered JSON from this model round — it's a tool call,
            # not text the user should see. This prevents cross-round accumulation.
            _token_buffer = ""
            tool_input = str(event.get("data", {}).get("input", ""))[:200]
            yield {"type": "tool_start", "name": name, "input": tool_input}

        elif kind == "on_tool_end":
            name = event.get("name", last_tool_name)
            output = str(event.get("data", {}).get("output", ""))[:500]
            yield {"type": "tool_end", "name": name, "output": output}

    # Flush any remaining buffer text, stripping tool-call JSON that was suppressed
    # during streaming but never properly discarded.
    if _token_buffer.strip():
        clean = _strip_leading_tool_calls(_token_buffer)
        if clean:
            full_content += clean
            yield {"type": "token", "content": clean}

    # Strip any tool-call JSON that leaked into full_content (last-resort safety net).
    full_content = _strip_leading_tool_calls(full_content)

    # Use streamed content if available, otherwise fall back to the model's
    # complete response captured via on_chat_model_end.
    if not full_content.strip():
        if final_answer:
            full_content = final_answer
            yield {"type": "token", "content": final_answer}
        else:
            # Both paths empty — max tool rounds hit with no trailing text.
            full_content = (
                "I reached my tool call limit without completing the research. "
                "Please try a more specific question."
            )
            yield {"type": "token", "content": full_content}

    yield {"type": "done", "content": full_content}


async def run_interactive(config: AgentConfig | None = None) -> None:
    """Run the CV agent in interactive chat mode."""
    if config is None:
        config = load_config()

    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    console.print("[bold green]CV Zero Claw Agent[/bold green] — Interactive Mode")
    console.print("Type 'quit' to exit, 'help' for commands.\n")

    history: list[Any] = []

    while True:
        try:
            user_input = console.input("[bold cyan]you>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if user_input.lower() == "help":
            console.print(Markdown(_HELP_TEXT))
            continue

        try:
            response = await run_agent(user_input, config, history)
            history.append(HumanMessage(content=user_input))
            history.append({"role": "assistant", "content": response})
            console.print()
            console.print(Markdown(response))
            console.print()
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            logger.exception("Agent error")


_HELP_TEXT = """\
## Commands

- **paper <url>** — Fetch and analyze a paper
- **spec <url>** — Generate spec.md from a paper
- **vision <path>** — Analyze an image with vision model
- **digest** — Generate weekly research digest
- **graph** — Show knowledge graph stats
- **quit** — Exit interactive mode
"""
