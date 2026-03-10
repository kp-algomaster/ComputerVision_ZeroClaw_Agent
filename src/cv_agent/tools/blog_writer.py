"""Blog writing tools — draft, format, and save research blog posts."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from cv_agent.http_client import httpx
from zeroclaw_tools import tool

from cv_agent.cache import get_cache
from cv_agent.config import load_config

logger = logging.getLogger(__name__)


def _call_llm(prompt: str, ttl: int | None = None) -> str:
    cfg = load_config()
    model = cfg.agents.blog_writer.model_override or cfg.llm.model
    cache = get_cache(cfg)
    key = cache.make_key(model, prompt)
    if (hit := cache.get(key)) is not None:
        return hit
    base_url = cfg.llm.base_url.rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": cfg.llm.max_tokens,
    }
    headers = {}
    if cfg.llm.api_key:
        headers["Authorization"] = f"Bearer {cfg.llm.api_key}"
    with httpx.Client(timeout=180) as client:
        resp = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"]
    cache.set(key, result, ttl=ttl or cfg.cache.ttl_llm, key_hint=prompt[:80])
    return result


@tool
def draft_blog_post(title: str, summary: str, tone: str = "technical") -> str:
    """Draft a research blog post from a title and summary.

    Args:
        title: Blog post title or paper title.
        summary: Key points, abstract, or bullet notes to expand.
        tone: Writing tone — 'technical', 'accessible', or 'newsletter'.

    Returns:
        Full blog post in Markdown.
    """
    prompt = f"""\
You are a technical writer for a computer vision research blog.
Write a {tone} blog post with the following:

Title: {title}

Source material:
{summary[:8000]}

Structure the post as:
- Engaging introduction (why this matters)
- Core contribution / method (with intuition)
- Key results and what they mean
- Limitations and future work
- Takeaway for practitioners

Use Markdown formatting. Include a TL;DR at the top.
"""
    return _call_llm(prompt)


@tool
def format_blog_markdown(content: str) -> str:
    """Clean and reformat a blog post draft into polished Markdown.

    Args:
        content: Raw blog draft text.

    Returns:
        Polished Markdown blog post.
    """
    prompt = f"""\
Reformat the following blog content into clean, polished Markdown suitable for publication.
Fix structure, improve readability, ensure consistent heading levels, and add a tags line at the end.

Content:
{content[:12000]}
"""
    return _call_llm(prompt)


@tool
def save_blog_post(title: str, content: str) -> str:
    """Save a blog post to the output directory.

    Args:
        title: Blog post title (used for filename).
        content: Markdown content to save.

    Returns:
        Path to saved file.
    """
    cfg = load_config()
    output_dir = Path(cfg.output.base_dir) / "blog"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    safe_title = safe_title.strip().replace(" ", "_")[:80]
    timestamp = datetime.now().strftime("%Y%m%d")
    path = output_dir / f"{timestamp}_{safe_title}.md"
    path.write_text(content)
    return f"Blog post saved: {path}"
