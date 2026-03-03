"""Research source definitions — ArXiv, Papers With Code, Semantic Scholar."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import feedparser
import httpx

logger = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"
PWC_API = "https://paperswithcode.com/api/v1"
S2_API = "https://api.semanticscholar.org/graph/v1"


@dataclass
class Paper:
    """Normalized paper representation across sources."""

    id: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: str = ""
    published: str = ""
    categories: list[str] = field(default_factory=list)
    source: str = "arxiv"
    citation_count: int = 0
    code_url: str = ""
    tasks: list[str] = field(default_factory=list)


def fetch_arxiv_recent(
    categories: list[str],
    queries: list[str],
    max_results: int = 50,
) -> list[Paper]:
    """Fetch recent papers from ArXiv matching categories and queries."""
    papers = []

    for query in queries:
        cat_filter = " OR ".join(f"cat:{c}" for c in categories)
        search_q = f"({query}) AND ({cat_filter})"

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    ARXIV_API,
                    params={
                        "search_query": search_q,
                        "max_results": max_results,
                        "sortBy": "submittedDate",
                        "sortOrder": "descending",
                    },
                )
                resp.raise_for_status()

            feed = feedparser.parse(resp.text)
            for entry in feed.entries:
                arxiv_id = entry.get("id", "").split("/abs/")[-1].split("v")[0]
                p = Paper(
                    id=arxiv_id,
                    title=entry.get("title", "").replace("\n", " ").strip(),
                    authors=[a.get("name", "") for a in entry.get("authors", [])],
                    abstract=entry.get("summary", "").replace("\n", " ").strip(),
                    url=f"https://arxiv.org/abs/{arxiv_id}",
                    pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                    published=entry.get("published", "")[:10],
                    categories=[t.get("term", "") for t in entry.get("tags", [])],
                    source="arxiv",
                )
                papers.append(p)
        except Exception:
            logger.exception(f"ArXiv query failed: {query}")

    # Deduplicate by ID
    seen = set()
    unique = []
    for p in papers:
        if p.id not in seen:
            seen.add(p.id)
            unique.append(p)
    return unique


def fetch_pwc_trending(areas: list[str], limit: int = 20) -> list[Paper]:
    """Fetch trending papers from Papers With Code."""
    papers = []

    for area in areas:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{PWC_API}/papers/",
                    params={"ordering": "-trending_score", "area": area, "items_per_page": limit},
                )
                resp.raise_for_status()
                data = resp.json()

            for item in data.get("results", []):
                p = Paper(
                    id=item.get("id", ""),
                    title=item.get("title", ""),
                    authors=[a.get("name", "") for a in item.get("authors", [])],
                    abstract=item.get("abstract", ""),
                    url=item.get("url_abs", ""),
                    pdf_url=item.get("url_pdf", ""),
                    published=item.get("published", ""),
                    source="papers_with_code",
                    tasks=[t.get("name", "") for t in item.get("tasks", [])],
                )
                if item.get("repository_url"):
                    p.code_url = item["repository_url"]
                papers.append(p)
        except Exception:
            logger.exception(f"Papers With Code fetch failed for area: {area}")

    return papers


def fetch_s2_recent(
    fields_of_study: list[str],
    query: str = "computer vision",
    limit: int = 20,
    api_key: str = "",
) -> list[Paper]:
    """Fetch recent papers from Semantic Scholar."""
    papers = []
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    try:
        params = {
            "query": query,
            "limit": limit,
            "fields": "paperId,title,authors,abstract,url,year,citationCount,externalIds",
            "fieldsOfStudy": ",".join(fields_of_study),
            "sort": "citationCount:desc",
        }

        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{S2_API}/paper/search",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        for item in data.get("data", []):
            arxiv_id = (item.get("externalIds") or {}).get("ArXiv", "")
            p = Paper(
                id=item.get("paperId", ""),
                title=item.get("title", ""),
                authors=[a.get("name", "") for a in (item.get("authors") or [])],
                abstract=item.get("abstract", "") or "",
                url=item.get("url", ""),
                published=str(item.get("year", "")),
                source="semantic_scholar",
                citation_count=item.get("citationCount", 0) or 0,
            )
            if arxiv_id:
                p.pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            papers.append(p)
    except Exception:
        logger.exception("Semantic Scholar fetch failed")

    return papers
