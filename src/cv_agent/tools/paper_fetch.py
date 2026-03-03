"""ArXiv and research paper fetching tools."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import feedparser
import httpx
from zeroclaw_tools import tool

logger = logging.getLogger(__name__)

ARXIV_API_BASE = "http://export.arxiv.org/api/query"
ARXIV_ABS_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})")
ARXIV_PDF_RE = re.compile(r"arxiv\.org/pdf/(\d{4}\.\d{4,5})")


def _extract_arxiv_id(url_or_id: str) -> str:
    """Extract ArXiv paper ID from URL or return as-is if already an ID."""
    for pattern in (ARXIV_ABS_RE, ARXIV_PDF_RE):
        match = pattern.search(url_or_id)
        if match:
            return match.group(1)
    # Assume it's already an ID like "2312.00785"
    return url_or_id.strip()


@tool
def fetch_arxiv_paper(arxiv_url_or_id: str) -> str:
    """Fetch metadata and abstract for a single ArXiv paper.

    Args:
        arxiv_url_or_id: ArXiv URL (https://arxiv.org/abs/XXXX.XXXXX) or paper ID.

    Returns:
        Paper title, authors, abstract, categories, and links.
    """
    paper_id = _extract_arxiv_id(arxiv_url_or_id)

    with httpx.Client(timeout=30) as client:
        resp = client.get(ARXIV_API_BASE, params={"id_list": paper_id})
        resp.raise_for_status()

    feed = feedparser.parse(resp.text)
    if not feed.entries:
        return f"No paper found for ID: {paper_id}"

    entry = feed.entries[0]
    authors = ", ".join(a.get("name", "") for a in entry.get("authors", []))
    categories = ", ".join(t.get("term", "") for t in entry.get("tags", []))
    published = entry.get("published", "Unknown")
    pdf_link = f"https://arxiv.org/pdf/{paper_id}.pdf"

    return (
        f"# {entry.get('title', 'Untitled')}\n\n"
        f"**ArXiv ID:** {paper_id}\n"
        f"**Authors:** {authors}\n"
        f"**Published:** {published}\n"
        f"**Categories:** {categories}\n"
        f"**PDF:** {pdf_link}\n"
        f"**Abstract URL:** https://arxiv.org/abs/{paper_id}\n\n"
        f"## Abstract\n\n{entry.get('summary', 'No abstract available.')}\n"
    )


@tool
def search_arxiv(
    query: str,
    max_results: int = 10,
    categories: str = "cs.CV",
    days_back: int = 30,
) -> str:
    """Search ArXiv for papers matching a query in computer vision categories.

    Args:
        query: Search query (e.g., "object detection transformer").
        max_results: Maximum number of results to return.
        categories: Comma-separated ArXiv categories (default: cs.CV).
        days_back: Only show papers from the last N days.

    Returns:
        Formatted list of matching papers with titles, authors, and abstracts.
    """
    cat_list = [c.strip() for c in categories.split(",")]
    cat_query = " OR ".join(f"cat:{c}" for c in cat_list)
    full_query = f"({query}) AND ({cat_query})"

    params = {
        "search_query": full_query,
        "max_results": min(max_results, 100),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    with httpx.Client(timeout=30) as client:
        resp = client.get(ARXIV_API_BASE, params=params)
        resp.raise_for_status()

    feed = feedparser.parse(resp.text)
    if not feed.entries:
        return f"No papers found for query: {query}"

    cutoff = datetime.now() - timedelta(days=days_back)
    results = []
    for i, entry in enumerate(feed.entries, 1):
        published_str = entry.get("published", "")
        try:
            pub_date = datetime.strptime(published_str[:10], "%Y-%m-%d")
            if pub_date < cutoff:
                continue
        except ValueError:
            pass

        authors = ", ".join(a.get("name", "") for a in entry.get("authors", [])[:5])
        if len(entry.get("authors", [])) > 5:
            authors += " et al."

        # Extract arxiv ID from entry id URL
        entry_id = entry.get("id", "").split("/abs/")[-1].split("v")[0]
        abstract = entry.get("summary", "").replace("\n", " ").strip()
        if len(abstract) > 300:
            abstract = abstract[:297] + "..."

        results.append(
            f"### {i}. {entry.get('title', 'Untitled')}\n"
            f"**ID:** {entry_id} | **Date:** {published_str[:10]}\n"
            f"**Authors:** {authors}\n"
            f"**Abstract:** {abstract}\n"
        )

    if not results:
        return f"No recent papers (last {days_back} days) found for: {query}"

    header = f"# ArXiv Search: \"{query}\"\n**Found {len(results)} papers**\n\n"
    return header + "\n---\n\n".join(results)


@tool
def fetch_paper_pdf(arxiv_url_or_id: str, save_path: str = "") -> str:
    """Download the PDF of an ArXiv paper.

    Args:
        arxiv_url_or_id: ArXiv URL or paper ID.
        save_path: Where to save the PDF. Defaults to ./papers/<id>.pdf.

    Returns:
        Path to the downloaded PDF file.
    """
    from pathlib import Path

    paper_id = _extract_arxiv_id(arxiv_url_or_id)
    pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"

    if not save_path:
        papers_dir = Path("papers")
        papers_dir.mkdir(exist_ok=True)
        save_path = str(papers_dir / f"{paper_id.replace('/', '_')}.pdf")

    save_file = Path(save_path)
    save_file.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(pdf_url)
        resp.raise_for_status()
        save_file.write_bytes(resp.content)

    size_mb = save_file.stat().st_size / (1024 * 1024)
    return f"Downloaded: {save_file} ({size_mb:.1f} MB)"
