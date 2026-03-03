"""Tests for the knowledge graph."""

from pathlib import Path

from cv_agent.config import KnowledgeConfig
from cv_agent.knowledge.graph import KnowledgeGraph


def test_add_paper(tmp_path: Path):
    """Papers can be added to the graph."""
    cfg = KnowledgeConfig(vault_path=str(tmp_path / "vault"))
    kg = KnowledgeGraph(cfg)

    kg.add_paper(
        paper_id="2312.00785",
        title="Test Paper on Object Detection",
        authors=["Alice", "Bob"],
        abstract="A novel approach to object detection.",
    )

    stats = kg.get_stats()
    assert stats["nodes"] == 1


def test_add_relationships(tmp_path: Path):
    """Methods and datasets can be linked to papers."""
    cfg = KnowledgeConfig(vault_path=str(tmp_path / "vault"))
    kg = KnowledgeGraph(cfg)

    kg.add_paper("2312.00785", "Detection Paper", ["Alice"], "Abstract")
    kg.add_method("DETR")
    kg.add_dataset("COCO")
    kg.add_link("Detection Paper", "DETR", "proposes")
    kg.add_link("Detection Paper", "COCO", "evaluates_on")

    stats = kg.get_stats()
    assert stats["nodes"] == 3
    assert stats["edges"] == 2


def test_search(tmp_path: Path):
    """Graph search finds matching entities."""
    cfg = KnowledgeConfig(vault_path=str(tmp_path / "vault"))
    kg = KnowledgeGraph(cfg)

    kg.add_paper("2312.00785", "Attention Is All You Need", ["Vaswani"], "Transformer")
    kg.add_paper("2312.00786", "ViT: Vision Transformer", ["Dosovitskiy"], "Vision")

    results = kg.search("transformer")
    assert len(results) == 2

    results = kg.search("vision", entity_type="paper")
    assert len(results) == 1


def test_obsidian_note_creation(tmp_path: Path):
    """Obsidian notes are created with correct format."""
    cfg = KnowledgeConfig(vault_path=str(tmp_path / "vault"))
    kg = KnowledgeGraph(cfg)

    kg.add_paper("2312.00785", "Test Paper", ["Alice"], "Test abstract")
    kg.add_method("DETR")
    kg.add_link("Test Paper", "DETR", "proposes")

    note_path = kg.write_obsidian_note("2312.00785")
    assert note_path
    content = Path(note_path).read_text()

    assert "---" in content  # Frontmatter
    assert "[[DETR]]" in content  # Wiki-link
    assert "Test abstract" in content


def test_mermaid_export(tmp_path: Path):
    """Graph exports to Mermaid diagram format."""
    cfg = KnowledgeConfig(vault_path=str(tmp_path / "vault"))
    kg = KnowledgeGraph(cfg)

    kg.add_paper("2312.00785", "Paper A", ["Alice"], "Abstract A")
    kg.add_method("Method X")
    kg.add_link("Paper A", "Method X", "proposes")

    mermaid = kg.to_mermaid()
    assert "graph LR" in mermaid
    assert "proposes" in mermaid
