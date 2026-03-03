"""CLI entry point for CV Zero Claw Agent."""

from __future__ import annotations

import asyncio
import logging
import sys

import click
from rich.console import Console
from rich.logging import RichHandler

from cv_agent.config import load_config

console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


@click.group()
@click.option("--config", "-c", default=None, help="Path to agent_config.yaml")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def main(ctx: click.Context, config: str | None, verbose: bool) -> None:
    """CV Zero Claw Agent — Autonomous Computer Vision Research Agent."""
    cfg = load_config(config)
    if verbose:
        cfg.log_level = "DEBUG"
    _setup_logging(cfg.log_level)
    ctx.ensure_object(dict)
    ctx.obj["config"] = cfg


@main.command()
@click.pass_context
def start(ctx: click.Context) -> None:
    """Start the agent in interactive mode."""
    from cv_agent.agent import run_interactive

    cfg = ctx.obj["config"]
    asyncio.run(run_interactive(cfg))


@main.command()
@click.option("--host", "-h", default="127.0.0.1", help="Host to bind to")
@click.option("--port", "-p", default=8420, help="Port to serve on")
@click.pass_context
def ui(ctx: click.Context, host: str, port: int) -> None:
    """Launch the web UI with chat and content viewer."""
    from cv_agent.web import run_server

    cfg = ctx.obj["config"]
    run_server(cfg, host=host, port=port)


@main.command()
@click.pass_context
def chat(ctx: click.Context) -> None:
    """Start interactive chat with the CV agent."""
    from cv_agent.agent import run_interactive

    cfg = ctx.obj["config"]
    asyncio.run(run_interactive(cfg))


@main.command()
@click.argument("url")
@click.option("--spec", is_flag=True, help="Also generate spec.md")
@click.pass_context
def paper(ctx: click.Context, url: str, spec: bool) -> None:
    """Fetch and analyze a paper from ArXiv or URL."""
    from cv_agent.agent import run_agent

    cfg = ctx.obj["config"]
    prompt = f"Fetch and analyze this paper: {url}"
    if spec:
        prompt += "\nAlso generate a spec.md from this paper."
    result = asyncio.run(run_agent(prompt, cfg))
    console.print(result)


@main.command()
@click.argument("query")
@click.option("--max-results", "-n", default=10, help="Max papers to return")
@click.pass_context
def search(ctx: click.Context, query: str, max_results: int) -> None:
    """Search for CV papers matching a query."""
    from cv_agent.agent import run_agent

    cfg = ctx.obj["config"]
    prompt = f"Search ArXiv for papers about: {query}. Return top {max_results} results."
    result = asyncio.run(run_agent(prompt, cfg))
    console.print(result)


@main.command()
@click.option("--week", is_flag=True, default=True, help="Generate weekly digest")
@click.pass_context
def digest(ctx: click.Context, week: bool) -> None:
    """Generate a research digest / magazine."""
    from cv_agent.research.digest import generate_weekly_digest

    cfg = ctx.obj["config"]
    result = asyncio.run(generate_weekly_digest(cfg))
    console.print(result)


@main.group()
def vision() -> None:
    """Vision model commands."""


@vision.command()
@click.argument("image_path")
@click.option("--model", "-m", default=None, help="Vision model to use")
@click.option("--prompt", "-p", default="Describe this image in detail.", help="Analysis prompt")
@click.pass_context
def analyze(ctx: click.Context, image_path: str, model: str | None, prompt: str) -> None:
    """Analyze an image using a vision model."""
    from cv_agent.agent import run_agent

    cfg = ctx.obj["config"]
    msg = f"Analyze the image at '{image_path}' with prompt: {prompt}"
    if model:
        msg += f" Use model: {model}"
    result = asyncio.run(run_agent(msg, cfg))
    console.print(result)


@main.group()
def knowledge() -> None:
    """Knowledge graph commands."""


@knowledge.command()
@click.pass_context
def sync(ctx: click.Context) -> None:
    """Sync and rebuild the knowledge graph from vault."""
    from cv_agent.knowledge.graph import KnowledgeGraph

    cfg = ctx.obj["config"]
    kg = KnowledgeGraph(cfg.knowledge)
    stats = kg.get_stats()
    console.print(f"Knowledge graph: {stats['nodes']} nodes, {stats['edges']} edges")


@knowledge.command()
@click.argument("query")
@click.pass_context
def find(ctx: click.Context, query: str) -> None:
    """Query the knowledge graph."""
    from cv_agent.agent import run_agent

    cfg = ctx.obj["config"]
    result = asyncio.run(run_agent(f"Query the knowledge graph for: {query}", cfg))
    console.print(result)


if __name__ == "__main__":
    main()
