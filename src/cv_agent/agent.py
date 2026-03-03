"""Main CV Agent orchestrator — ties ZeroClaw tools into an autonomous CV research agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from zeroclaw_tools import create_agent, shell, file_read, file_write, web_search, http_request

from cv_agent.config import AgentConfig, OllamaConfig, load_config
from cv_agent.tools.vision import analyze_image, describe_image, compare_images
from cv_agent.tools.mlx_vision import mlx_analyze_image
from cv_agent.tools.paper_fetch import fetch_arxiv_paper, search_arxiv, fetch_paper_pdf
from cv_agent.tools.equation_extract import extract_equations, extract_key_info
from cv_agent.tools.knowledge_graph import add_paper_to_graph, query_graph, export_graph
from cv_agent.tools.spec_generator import generate_spec, generate_spec_from_url
from cv_agent.tools.hardware_probe import (
    check_runnable_models,
    list_available_models,
    pull_vision_model,
    ensure_ollama_model,
    select_best_ollama_model,
    get_runnable_models,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert Computer Vision research agent. Your capabilities:

0. **Hardware-Aware Model Selection & Auto-Download**:
   - Use `check_runnable_models` to find which VLMs fit this hardware.
   - Use `list_available_models` to see what is already pulled in Ollama.
   - Use `pull_vision_model` to download the appropriate VLM automatically before \
running any vision task. Always ensure the right model is available BEFORE calling \
vision tools. Call `pull_vision_model` with no arguments to let the system choose \
the best model for the hardware, or pass a specific tag e.g. "qwen2.5-vl:7b".


1. **Vision Analysis**: Analyze images using state-of-the-art vision models (Qwen2.5-VL, LLaVA) \
via Ollama and MLX-accelerated models on Apple Silicon.

2. **Research Monitoring**: Search and track the latest CV research from ArXiv, Papers With Code, \
and Semantic Scholar. You understand deep learning architectures, loss functions, training \
strategies, and evaluation metrics.

3. **Paper Processing**: Fetch papers, extract equations (LaTeX), key architectural details, \
training configurations, and experimental results.

4. **Knowledge Graphs**: Build and maintain an Obsidian-compatible knowledge vault that links \
papers, methods, datasets, architectures, and concepts as an interconnected graph.

5. **Spec Generation**: Convert research papers into structured spec.md files for spec-driven \
development, with extracted equations, architecture details, and implementation requirements.

6. **Weekly Digest**: Generate comprehensive weekly magazines/blogs covering the latest CV \
research breakthroughs.

When analyzing papers or research:
- Always extract the core contribution and novelty
- Identify the mathematical formulations (loss functions, architectures)
- Note datasets used and comparison baselines
- Assess practical implementability
- Link to related work in the knowledge graph

When generating specs:
- Structure for direct implementation
- Include all equations in LaTeX
- Define clear input/output contracts
- Note hardware/compute requirements
- List dependencies and prerequisites
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
    ]

    # Add MLX tools if available on Apple Silicon
    if config.vision.mlx.enabled:
        tools.append(mlx_analyze_image)

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


async def run_agent(
    message: str,
    config: AgentConfig | None = None,
    history: list[Any] | None = None,
) -> str:
    """Run the CV agent with a user message and return the response."""
    if config is None:
        config = load_config()

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
        messages.extend(history)
    messages.append(HumanMessage(content=message))

    result = await agent.ainvoke({"messages": messages})
    return result["messages"][-1].content


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
