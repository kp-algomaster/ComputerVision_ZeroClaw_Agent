"""Website maintenance tools — health checks, link auditing, SEO basics."""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

from cv_agent.http_client import httpx
from zeroclaw_tools import tool

from cv_agent.cache import get_cache
from cv_agent.config import load_config

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_USER_AGENT = "CV-Agent/1.0 (site-audit)"


def _head(url: str) -> tuple[int, str]:
    """Return (status_code, redirect_url_or_empty)."""
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
            resp = client.head(url, headers={"User-Agent": _USER_AGENT})
            location = resp.headers.get("location", "")
            return resp.status_code, location
    except Exception as exc:
        return 0, str(exc)


@tool
def check_url_health(url: str) -> str:
    """Check if a URL is reachable and report its status.

    Args:
        url: Full URL to check (e.g. https://example.com).

    Returns:
        Status report with HTTP code, redirect chain, and latency.
    """
    import time

    cfg = load_config()
    cache = get_cache(cfg)
    cache_key = cache.make_key("url_health", url)
    if (hit := cache.get(cache_key)) is not None:
        return hit

    results = []
    current = url
    for _ in range(5):  # follow up to 5 redirects manually for reporting
        t0 = time.monotonic()
        code, location = _head(current)
        latency = (time.monotonic() - t0) * 1000
        if code == 0:
            results.append(f"❌ {current} — ERROR: {location}")
            break
        results.append(f"{'✅' if code < 400 else '❌'} {current} → {code} ({latency:.0f}ms)")
        if code in (301, 302, 307, 308) and location:
            current = urljoin(current, location)
        else:
            break
    output = "\n".join(results)
    cache.set(cache_key, output, ttl=cfg.cache.ttl_search, key_hint=f"url_health:{url}")
    return output


@tool
def audit_links(base_url: str, max_links: int = 50) -> str:
    """Crawl a page and audit all anchor links for broken URLs.

    Args:
        base_url: URL of the page to audit.
        max_links: Maximum number of links to check (default 50).

    Returns:
        Report of broken, redirecting, and healthy links.
    """
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(base_url, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        return f"Failed to fetch page: {exc}"

    import re
    hrefs = re.findall(r'href=["\']([^"\'#?][^"\']*)["\']', html)
    links = []
    seen: set[str] = set()
    for href in hrefs:
        full = urljoin(base_url, href) if not href.startswith("http") else href
        parsed = urlparse(full)
        if parsed.scheme in ("http", "https") and full not in seen:
            seen.add(full)
            links.append(full)
        if len(links) >= max_links:
            break

    broken, redirects, ok = [], [], []
    for link in links:
        code, location = _head(link)
        if code == 0 or code >= 400:
            broken.append(f"❌ {code} {link}")
        elif code in (301, 302, 307, 308):
            redirects.append(f"↪️  {code} {link} → {location}")
        else:
            ok.append(f"✅ {code} {link}")

    lines = [f"Audited {len(links)} links on {base_url}", ""]
    if broken:
        lines += ["### Broken links"] + broken + [""]
    if redirects:
        lines += ["### Redirects"] + redirects + [""]
    lines += [f"### OK ({len(ok)}/{len(links)})"] + ok[:10]
    if len(ok) > 10:
        lines.append(f"... and {len(ok) - 10} more OK links")
    return "\n".join(lines)


@tool
def check_seo_basics(url: str) -> str:
    """Check basic on-page SEO signals for a URL.

    Args:
        url: Page URL to audit.

    Returns:
        SEO report covering title, meta description, headings, and images.
    """
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        return f"Failed to fetch page: {exc}"

    import re

    def first(pattern: str) -> str:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    title = first(r"<title[^>]*>(.*?)</title>")
    meta_desc = first(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)')
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)
    imgs_no_alt = len(re.findall(r"<img(?![^>]+alt=)[^>]+>", html, re.IGNORECASE))
    canonical = first(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)')

    report = [f"## SEO Audit: {url}", ""]
    report.append(f"**Title** ({len(title)} chars): {title or '⚠️ Missing'}")
    report.append(f"**Meta description** ({len(meta_desc)} chars): {meta_desc or '⚠️ Missing'}")
    report.append(f"**H1 tags** ({len(h1s)}): {', '.join(re.sub('<[^>]+>', '', h) for h in h1s[:3]) or '⚠️ None'}")
    report.append(f"**H2 tags**: {len(h2s)}")
    report.append(f"**Images missing alt**: {'⚠️ ' + str(imgs_no_alt) if imgs_no_alt else '✅ None'}")
    report.append(f"**Canonical**: {canonical or '⚠️ Not set'}")

    issues = []
    if not title:
        issues.append("Missing <title> tag")
    elif len(title) > 60:
        issues.append(f"Title too long ({len(title)} chars, recommended ≤60)")
    if not meta_desc:
        issues.append("Missing meta description")
    elif len(meta_desc) > 160:
        issues.append(f"Meta description too long ({len(meta_desc)} chars, recommended ≤160)")
    if len(h1s) == 0:
        issues.append("No H1 tag found")
    elif len(h1s) > 1:
        issues.append(f"Multiple H1 tags ({len(h1s)})")
    if imgs_no_alt:
        issues.append(f"{imgs_no_alt} image(s) missing alt text")

    report.append("")
    if issues:
        report.append("### Issues")
        report.extend(f"- {i}" for i in issues)
    else:
        report.append("✅ No major SEO issues found")

    return "\n".join(report)
