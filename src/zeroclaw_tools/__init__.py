"""zeroclaw_tools compatibility shim.

Provides the same interface as the zeroclaw-tools package using LangChain/LangGraph
so the agent can run locally without the Rust ZeroClaw runtime.
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any

import httpx
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

__all__ = [
    "tool",
    "create_agent",
    "shell",
    "file_read",
    "file_write",
    "web_search",
    "http_request",
]


def create_agent(
    tools: list,
    model: str,
    api_key: str | None = None,
    base_url: str = "http://localhost:11434/v1",
) -> Any:
    """Create a LangGraph ReAct agent backed by an Ollama-compatible OpenAI endpoint."""
    llm = ChatOpenAI(
        model=model,
        api_key=api_key or "ollama",   # Ollama ignores the key; must be non-empty
        base_url=base_url,
        temperature=0,
    )
    return create_react_agent(llm, tools)


@tool
def shell(command: str) -> str:
    """Run a shell command and return combined stdout + stderr (max 4 KB).

    Args:
        command: Shell command to execute.

    Returns:
        Command output (truncated at 4096 chars).
    """
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = (result.stdout + result.stderr).strip()
    return output[:4096]


@tool
def file_read(path: str) -> str:
    """Read a local file and return its text contents.

    Args:
        path: Absolute or home-relative (~) path to the file.

    Returns:
        File contents as a string.
    """
    return pathlib.Path(path).expanduser().read_text(errors="replace")


@tool
def file_write(path: str, content: str) -> str:
    """Write text content to a local file, creating parent directories as needed.

    Args:
        path: Destination file path.
        content: Text to write.

    Returns:
        Confirmation message with byte count.
    """
    p = pathlib.Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content)} chars to {path}"


@tool
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo Instant Answer API.

    Args:
        query: Search query string.

    Returns:
        Top search results as plain text.
    """
    try:
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=10,
        )
        data = resp.json()
        results: list[str] = []
        if data.get("AbstractText"):
            results.append(data["AbstractText"])
        for item in data.get("RelatedTopics", [])[:5]:
            if isinstance(item, dict) and item.get("Text"):
                results.append(item["Text"])
        return "\n\n".join(results) if results else "No results found."
    except Exception as exc:
        return f"Search error: {exc}"


@tool
def http_request(url: str, method: str = "GET", body: str = "") -> str:
    """Make an HTTP request and return the response body.

    Args:
        url:    Target URL.
        method: HTTP method (GET, POST, etc.).
        body:   Optional request body.

    Returns:
        Response text (truncated at 8 KB).
    """
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.request(
            method,
            url,
            content=body.encode() if body else None,
        )
        return resp.text[:8192]
