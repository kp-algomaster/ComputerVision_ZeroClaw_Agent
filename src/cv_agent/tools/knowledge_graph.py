"""Knowledge graph tools — build Obsidian-compatible knowledge graphs from CV research."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from zeroclaw_tools import tool

from cv_agent.config import load_config
from cv_agent.knowledge.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


def _get_kg() -> KnowledgeGraph:
    cfg = load_config()
    return KnowledgeGraph(cfg.knowledge)


@tool
def add_paper_to_graph(
    paper_id: str,
    title: str,
    authors: str,
    abstract: str,
    methods: str = "",
    datasets: str = "",
    related_papers: str = "",
) -> str:
    """Add a paper and its relationships to the knowledge graph.

    Creates an Obsidian-compatible note with wiki-links to methods, datasets, and related work.

    Args:
        paper_id: ArXiv ID or unique identifier.
        title: Paper title.
        authors: Comma-separated author names.
        abstract: Paper abstract.
        methods: Comma-separated methods/techniques used.
        datasets: Comma-separated datasets used.
        related_papers: Comma-separated related paper IDs or titles.

    Returns:
        Confirmation with the created note path and graph stats.
    """
    kg = _get_kg()

    # Add the paper node
    kg.add_paper(
        paper_id=paper_id,
        title=title,
        authors=[a.strip() for a in authors.split(",") if a.strip()],
        abstract=abstract,
    )

    # Add method relationships
    if methods:
        for method in methods.split(","):
            method = method.strip()
            if method:
                kg.add_method(method)
                kg.add_link(paper_id, method, "proposes")

    # Add dataset relationships
    if datasets:
        for dataset in datasets.split(","):
            dataset = dataset.strip()
            if dataset:
                kg.add_dataset(dataset)
                kg.add_link(paper_id, dataset, "evaluates_on")

    # Add related paper links
    if related_papers:
        for related in related_papers.split(","):
            related = related.strip()
            if related:
                kg.add_link(paper_id, related, "cites")

    # Write Obsidian note
    note_path = kg.write_obsidian_note(paper_id)
    stats = kg.get_stats()

    return (
        f"Added paper '{title}' to knowledge graph.\n"
        f"Note: {note_path}\n"
        f"Graph: {stats['nodes']} nodes, {stats['edges']} edges"
    )


@tool
def query_graph(query: str, entity_type: str = "") -> str:
    """Query the knowledge graph for papers, methods, datasets, or connections.

    Args:
        query: Search query (entity name, paper ID, or keyword).
        entity_type: Filter by type: paper, method, dataset, author (empty for all).

    Returns:
        Matching entities and their connections in the graph.
    """
    kg = _get_kg()
    results = kg.search(query, entity_type=entity_type or None)

    if not results:
        return f"No results found for '{query}'"

    output = [f"# Knowledge Graph Query: \"{query}\"\n"]
    for node in results:
        output.append(f"## {node['name']} ({node['type']})\n")
        if node.get("connections"):
            output.append("**Connections:**\n")
            for conn in node["connections"]:
                output.append(f"- {conn['relation']} → [[{conn['target']}]]\n")
        output.append("")

    return "\n".join(output)


@tool
def export_graph(format: str = "json") -> str:
    """Export the knowledge graph in the specified format.

    Args:
        format: Export format — 'json', 'markdown', or 'mermaid'.

    Returns:
        The exported graph data or path to the export file.
    """
    kg = _get_kg()

    if format == "json":
        data = kg.to_dict()
        output_path = Path(load_config().output.base_dir) / "knowledge_graph.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(data, indent=2))
        return f"Exported graph to {output_path} ({len(data.get('nodes', []))} nodes)"

    elif format == "mermaid":
        mermaid = kg.to_mermaid()
        return f"```mermaid\n{mermaid}\n```"

    elif format == "markdown":
        return kg.to_markdown_index()

    return f"Unknown format: {format}. Use 'json', 'markdown', or 'mermaid'."
