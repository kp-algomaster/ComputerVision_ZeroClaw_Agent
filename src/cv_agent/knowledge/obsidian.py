"""Obsidian vault management — MOCs, daily notes, and vault maintenance."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from cv_agent.config import KnowledgeConfig

logger = logging.getLogger(__name__)


class ObsidianVault:
    """Manages an Obsidian-compatible vault for CV research knowledge."""

    def __init__(self, config: KnowledgeConfig):
        self.config = config
        self.vault_path = Path(config.vault_path).expanduser().resolve()

    def create_moc(self, topic: str, papers: list[dict]) -> Path:
        """Create a Map of Content (MOC) note for a topic.

        MOCs are hub notes in Obsidian that link to related content.
        """
        moc_dir = self.vault_path / "MOCs"
        moc_dir.mkdir(parents=True, exist_ok=True)
        moc_path = moc_dir / f"{topic}.md"

        lines = [
            "---",
            f"type: moc",
            f"topic: {topic}",
            f"created: {datetime.now().strftime('%Y-%m-%d')}",
            f"tags: [cv/moc, cv/{topic.lower().replace(' ', '-')}]",
            "---",
            "",
            f"# {topic}",
            "",
            "## Papers",
            "",
        ]

        for paper in papers:
            title = paper.get("title", "Untitled")
            lines.append(f"- [[{title}]]")

        lines.extend([
            "",
            "## Key Methods",
            "",
            "*Add links to method notes here*",
            "",
            "## Datasets",
            "",
            "*Add links to dataset notes here*",
            "",
            "## Notes",
            "",
            "*Add your notes and observations here*",
        ])

        moc_path.write_text("\n".join(lines))
        return moc_path

    def create_daily_note(self, papers: list[dict]) -> Path:
        """Create a daily research note with today's findings."""
        today = datetime.now().strftime("%Y-%m-%d")
        daily_dir = self.vault_path / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_path = daily_dir / f"{today}.md"

        lines = [
            "---",
            f"type: daily",
            f"date: {today}",
            "tags: [cv/daily]",
            "---",
            "",
            f"# Research Log — {today}",
            "",
            "## New Papers",
            "",
        ]

        for paper in papers:
            title = paper.get("title", "Untitled")
            arxiv_id = paper.get("id", "")
            lines.append(f"- [[{title}]] ({arxiv_id})")

        lines.extend([
            "",
            "## Notes",
            "",
            "",
            "## TODO",
            "",
            "- [ ] Review papers above",
            "- [ ] Update knowledge graph",
        ])

        daily_path.write_text("\n".join(lines))
        return daily_path

    def generate_vault_index(self) -> Path:
        """Generate a top-level index note for the vault."""
        index_path = self.vault_path / "README.md"

        # Count files by type
        counts: dict[str, int] = {}
        for subdir in self.vault_path.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("."):
                md_count = len(list(subdir.glob("*.md")))
                if md_count > 0:
                    counts[subdir.name] = md_count

        lines = [
            f"# {self.config.vault_name}",
            "",
            "Computer Vision Research Knowledge Vault",
            "",
            "## Contents",
            "",
        ]

        for folder, count in sorted(counts.items()):
            lines.append(f"- **{folder.title()}** ({count} notes)")

        lines.extend([
            "",
            "## Maps of Content",
            "",
        ])

        moc_dir = self.vault_path / "MOCs"
        if moc_dir.exists():
            for moc in sorted(moc_dir.glob("*.md")):
                lines.append(f"- [[{moc.stem}]]")

        lines.extend([
            "",
            f"*Last updated: {datetime.now().strftime('%Y-%m-%d')}*",
        ])

        index_path.write_text("\n".join(lines))
        return index_path
