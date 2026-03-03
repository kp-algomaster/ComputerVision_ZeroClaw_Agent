"""Core knowledge graph using NetworkX — Obsidian-compatible with wiki-links."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx

from cv_agent.config import KnowledgeConfig

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """In-memory knowledge graph backed by an Obsidian-compatible vault on disk."""

    def __init__(self, config: KnowledgeConfig):
        self.config = config
        self.vault_path = Path(config.vault_path).expanduser().resolve()
        self.graph = nx.DiGraph()
        self._ensure_vault()
        self._load_from_vault()

    def _ensure_vault(self) -> None:
        """Create vault directory structure if it doesn't exist."""
        for subdir in ("papers", "methods", "datasets", "tasks", "authors", "MOCs"):
            (self.vault_path / subdir).mkdir(parents=True, exist_ok=True)

        # Create .obsidian config for graph view
        obsidian_dir = self.vault_path / ".obsidian"
        obsidian_dir.mkdir(exist_ok=True)

        graph_json = obsidian_dir / "graph.json"
        if not graph_json.exists():
            graph_json.write_text(json.dumps({
                "collapse-filter": False,
                "search": "",
                "showTags": True,
                "showAttachments": False,
                "hideUnresolved": False,
                "showOrphans": True,
                "collapse-color-groups": False,
                "colorGroups": [
                    {"query": "path:papers", "color": {"a": 1, "rgb": 4488191}},
                    {"query": "path:methods", "color": {"a": 1, "rgb": 16744448}},
                    {"query": "path:datasets", "color": {"a": 1, "rgb": 6684672}},
                    {"query": "path:tasks", "color": {"a": 1, "rgb": 16711680}},
                ],
                "collapse-display": False,
                "showArrow": True,
                "textFadeMultiplier": 0,
                "nodeSizeMultiplier": 1,
                "lineSizeMultiplier": 1,
            }, indent=2))

    def _load_from_vault(self) -> None:
        """Load graph from existing Obsidian vault notes by parsing wiki-links."""
        for md_file in self.vault_path.rglob("*.md"):
            rel = md_file.relative_to(self.vault_path)
            parts = rel.parts
            if parts[0] == ".obsidian":
                continue

            node_type = parts[0] if len(parts) > 1 else "unknown"
            node_name = md_file.stem

            # Read frontmatter and content
            content = md_file.read_text(errors="replace")
            metadata = self._parse_frontmatter(content)
            metadata["type"] = node_type
            metadata["file"] = str(rel)

            self.graph.add_node(node_name, **metadata)

            # Parse [[wiki-links]] to create edges
            links = re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]", content)
            for link in links:
                target = link.strip()
                if target and target != node_name:
                    self.graph.add_edge(node_name, target)

    def _parse_frontmatter(self, content: str) -> dict[str, Any]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}
        end = content.find("---", 3)
        if end == -1:
            return {}
        import yaml
        try:
            return yaml.safe_load(content[3:end]) or {}
        except Exception:
            return {}

    def _sanitize_name(self, name: str) -> str:
        """Make a name safe for use as an Obsidian filename."""
        sanitized = re.sub(r'[<>:"/\\|?*]', "", name)
        return sanitized.strip()[:120]

    def add_paper(
        self,
        paper_id: str,
        title: str,
        authors: list[str],
        abstract: str,
    ) -> None:
        """Add a paper node to the graph."""
        safe_title = self._sanitize_name(title)
        self.graph.add_node(
            safe_title,
            type="paper",
            paper_id=paper_id,
            title=title,
            authors=authors,
            abstract=abstract,
            added=datetime.now().isoformat(),
        )

    def add_method(self, name: str, description: str = "") -> None:
        """Add a method/technique node."""
        safe = self._sanitize_name(name)
        if safe not in self.graph:
            self.graph.add_node(safe, type="method", description=description)

    def add_dataset(self, name: str, description: str = "") -> None:
        """Add a dataset node."""
        safe = self._sanitize_name(name)
        if safe not in self.graph:
            self.graph.add_node(safe, type="dataset", description=description)

    def add_link(self, source: str, target: str, relation: str = "related") -> None:
        """Add a directed edge between two nodes."""
        src = self._sanitize_name(source)
        tgt = self._sanitize_name(target)
        # Ensure both nodes exist
        if src not in self.graph:
            self.graph.add_node(src, type="unknown")
        if tgt not in self.graph:
            self.graph.add_node(tgt, type="unknown")
        self.graph.add_edge(src, tgt, relation=relation)

    def write_obsidian_note(self, paper_id_or_title: str) -> str:
        """Write an Obsidian-compatible markdown note for a node."""
        safe = self._sanitize_name(paper_id_or_title)

        # Find the node — try exact match first, then search
        node_name = None
        for n, data in self.graph.nodes(data=True):
            if n == safe or data.get("paper_id") == paper_id_or_title:
                node_name = n
                break

        if node_name is None:
            return ""

        data = self.graph.nodes[node_name]
        node_type = data.get("type", "unknown")

        # Determine output directory
        type_dir = self.vault_path / (node_type + "s" if not node_type.endswith("s") else node_type)
        type_dir.mkdir(parents=True, exist_ok=True)
        note_path = type_dir / f"{node_name}.md"

        # Build frontmatter
        frontmatter = {
            "type": node_type,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "tags": [f"cv/{node_type}"],
        }
        if data.get("paper_id"):
            frontmatter["arxiv_id"] = data["paper_id"]
        if data.get("authors"):
            frontmatter["authors"] = data["authors"]

        import yaml
        fm_str = yaml.dump(frontmatter, default_flow_style=False).strip()

        # Build body with wiki-links
        body_parts = [f"---\n{fm_str}\n---\n\n# {data.get('title', node_name)}\n"]

        if data.get("abstract"):
            body_parts.append(f"\n## Abstract\n\n{data['abstract']}\n")

        # Add connections as wiki-links
        successors = list(self.graph.successors(node_name))
        predecessors = list(self.graph.predecessors(node_name))

        if successors:
            body_parts.append("\n## Related\n")
            for succ in successors:
                edge_data = self.graph.edges[node_name, succ]
                relation = edge_data.get("relation", "related")
                body_parts.append(f"- {relation}: [[{succ}]]\n")

        if predecessors:
            body_parts.append("\n## Referenced By\n")
            for pred in predecessors:
                edge_data = self.graph.edges[pred, node_name]
                relation = edge_data.get("relation", "related")
                body_parts.append(f"- {relation} from: [[{pred}]]\n")

        note_path.write_text("".join(body_parts))
        return str(note_path)

    def search(self, query: str, entity_type: str | None = None) -> list[dict[str, Any]]:
        """Search the graph for nodes matching a query."""
        query_lower = query.lower()
        results = []

        for node, data in self.graph.nodes(data=True):
            if entity_type and data.get("type") != entity_type:
                continue

            # Search in node name, title, abstract
            searchable = f"{node} {data.get('title', '')} {data.get('abstract', '')}".lower()
            if query_lower in searchable:
                connections = []
                for succ in self.graph.successors(node):
                    edge = self.graph.edges[node, succ]
                    connections.append({
                        "target": succ,
                        "relation": edge.get("relation", "related"),
                    })
                results.append({
                    "name": node,
                    "type": data.get("type", "unknown"),
                    "title": data.get("title", node),
                    "connections": connections,
                })

        return results

    def get_stats(self) -> dict[str, int]:
        """Get graph statistics."""
        type_counts: dict[str, int] = {}
        for _, data in self.graph.nodes(data=True):
            t = data.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "types": type_counts,
        }

    def to_dict(self) -> dict[str, Any]:
        """Export graph as a dictionary."""
        nodes = []
        for n, data in self.graph.nodes(data=True):
            nodes.append({"id": n, **data})
        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({"source": u, "target": v, **data})
        return {"nodes": nodes, "edges": edges}

    def to_mermaid(self) -> str:
        """Export graph as a Mermaid diagram."""
        lines = ["graph LR"]
        # Add nodes with styling
        for n, data in self.graph.nodes(data=True):
            safe_id = re.sub(r"[^a-zA-Z0-9]", "_", n)[:40]
            label = n[:50]
            node_type = data.get("type", "unknown")
            if node_type == "paper":
                lines.append(f"    {safe_id}[📄 {label}]")
            elif node_type == "method":
                lines.append(f"    {safe_id}{{{{⚙️ {label}}}}}")
            elif node_type == "dataset":
                lines.append(f"    {safe_id}[({label})]")
            else:
                lines.append(f"    {safe_id}[{label}]")

        # Add edges
        for u, v, data in self.graph.edges(data=True):
            u_id = re.sub(r"[^a-zA-Z0-9]", "_", u)[:40]
            v_id = re.sub(r"[^a-zA-Z0-9]", "_", v)[:40]
            rel = data.get("relation", "")
            if rel:
                lines.append(f"    {u_id} -->|{rel}| {v_id}")
            else:
                lines.append(f"    {u_id} --> {v_id}")

        return "\n".join(lines)

    def to_markdown_index(self) -> str:
        """Generate a Markdown index of all nodes."""
        stats = self.get_stats()
        parts = [
            "# Knowledge Graph Index\n",
            f"**Nodes:** {stats['nodes']} | **Edges:** {stats['edges']}\n",
        ]

        # Group by type
        by_type: dict[str, list[str]] = {}
        for n, data in self.graph.nodes(data=True):
            t = data.get("type", "unknown")
            by_type.setdefault(t, []).append(n)

        for node_type, nodes in sorted(by_type.items()):
            parts.append(f"\n## {node_type.title()} ({len(nodes)})\n")
            for node in sorted(nodes):
                parts.append(f"- [[{node}]]\n")

        return "".join(parts)
