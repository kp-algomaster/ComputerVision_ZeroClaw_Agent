"""zeroclaw_tools compatibility shim.

Provides the same interface as the zeroclaw-tools package using LangChain/LangGraph.
Includes a text-based ReAct loop that works even when the local model does NOT emit
native tool_calls (e.g. qwen2.5-coder outputs tool calls as JSON text content).
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import uuid
from typing import Any

from cv_agent.http_client import httpx, httpx_verify, create_async_httpx_client, create_httpx_client
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

__all__ = [
    "tool",
    "create_agent",
    "shell",
    "file_read",
    "file_write",
    "web_search",
    "http_request",
]

_OLLAMA_HOSTS = ("localhost:11434", "127.0.0.1:11434", "0.0.0.0:11434")

_MAX_TOOL_ROUNDS = 10   # safety cap on agent loop iterations


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_ollama(base_url: str) -> bool:
    return any(h in base_url for h in _OLLAMA_HOSTS)


def _extract_text_tool_call(content: str) -> tuple[str, dict] | None:
    """Parse a JSON tool-call emitted as plain text by models that don't support
    native function calling.

    Handles both:
      {"name": "tool_name", "arguments": {...}}
      {"name": "tool_name", "args": {...}}
    and JSON embedded inside a larger text response (e.g. with trailing reasoning).
    Uses a balanced-brace scanner so nested objects are handled correctly.
    """
    # Try whole content first (fast path for clean JSON responses)
    try:
        data = json.loads(content.strip())
        if isinstance(data, dict) and "name" in data:
            args = data.get("arguments") or data.get("args") or {}
            if isinstance(args, dict):
                return data["name"], args
    except (json.JSONDecodeError, ValueError):
        pass

    # Balanced-brace scanner — correctly handles nested {"arguments": {...}}
    for start, ch in enumerate(content):
        if ch != "{":
            continue
        depth = 0
        for end in range(start, len(content)):
            if content[end] == "{":
                depth += 1
            elif content[end] == "}":
                depth -= 1
                if depth == 0:
                    candidate = content[start : end + 1]
                    try:
                        data = json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        break
                    if isinstance(data, dict) and "name" in data:
                        args = data.get("arguments") or data.get("args") or {}
                        if isinstance(args, dict):
                            return data["name"], args
                    break  # valid JSON but not a tool call — keep scanning

    return None


def _build_tool_prompt(tools: list) -> str:
    """Return the tools section injected into the system prompt for text-mode agents."""
    lines = [
        "── TOOL INSTRUCTIONS ──────────────────────────────────────────────\n"
        "You MUST use a tool whenever the user asks about papers, research, images, "
        "files, or anything requiring live data. DO NOT answer research or current-events "
        "questions from memory — call a tool first.\n\n"
        "To call a tool respond with ONLY a raw JSON object — no markdown, no explanation:\n"
        '{"name": "<tool_name>", "arguments": {<key>: <value>, ...}}\n\n'
        "You may call tools multiple times in sequence. After ALL necessary tool calls "
        "are done, provide your final answer as plain text (not JSON).\n"
        "────────────────────────────────────────────────────────────────────\n"
        "Available tools:",
    ]
    for t in tools:
        schema = getattr(t, "args_schema", None)
        args_desc = ""
        if schema:
            try:
                props = schema.model_json_schema().get("properties", {})
                args_desc = ", ".join(
                    f'{k}: {v.get("type", "any")}' for k, v in props.items()
                )
            except Exception:
                pass
        # Include first line of docstring as hint
        doc = (getattr(t, "description", "") or "").split("\n")[0].strip()
        lines.append(f"  {t.name}({args_desc}) — {doc}")
    lines.append("────────────────────────────────────────────────────────────────────")
    return "\n".join(lines)


# ── Custom ReAct graph that handles text-based tool calls ────────────────────

class _AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def _make_text_react_graph(llm: Any, tools: list) -> Any:
    """Build a LangGraph StateGraph that handles text-based tool calls."""
    tool_map = {t.name: t for t in tools}
    tool_prompt = _build_tool_prompt(tools)

    def _inject_tool_prompt(messages: list) -> list:
        """Prepend tool instructions to the first SystemMessage, or insert one."""
        from langchain_core.messages import SystemMessage
        out = list(messages)
        for i, msg in enumerate(out):
            if isinstance(msg, SystemMessage):
                out[i] = SystemMessage(content=msg.content + "\n\n" + tool_prompt)
                return out
        out.insert(0, SystemMessage(content=tool_prompt))
        return out

    async def call_model(state: _AgentState) -> dict:
        msgs = _inject_tool_prompt(state["messages"])
        response = await llm.ainvoke(msgs)
        return {"messages": [response]}

    async def call_tools(state: _AgentState) -> dict:
        last = state["messages"][-1]
        new_msgs: list = []

        # ── Native tool_calls (models that do support function calling) ──────
        if hasattr(last, "tool_calls") and last.tool_calls:
            for tc in last.tool_calls:
                fn = tool_map.get(tc["name"])
                result = fn.invoke(tc["args"]) if fn else f"Unknown tool: {tc['name']}"
                new_msgs.append(
                    ToolMessage(content=str(result), tool_call_id=tc["id"])
                )
            return {"messages": new_msgs}

        # ── Text-based tool call fallback ────────────────────────────────────
        parsed = _extract_text_tool_call(str(last.content))
        if parsed:
            name, args = parsed
            fn = tool_map.get(name)
            result = fn.invoke(args) if fn else f"Unknown tool: {name}"
            # Feed result back as a human turn so the model can produce a final answer
            new_msgs.append(
                HumanMessage(
                    content=f"Tool '{name}' returned:\n{result}\n\n"
                            "IMPORTANT: Now write your final answer as plain text. "
                            "Do NOT call any more tools — synthesise the results you have and respond directly."
                )
            )

        return {"messages": new_msgs}

    def should_continue(state: _AgentState) -> str:
        last = state["messages"][-1]
        # Safety: never loop more than _MAX_TOOL_ROUNDS times
        ai_msgs = [m for m in state["messages"] if isinstance(m, AIMessage)]
        if len(ai_msgs) >= _MAX_TOOL_ROUNDS:
            return END

        # Early-exit if the last 3 AI messages all called the same tool —
        # the model is stuck in a loop and getting the same results.
        if len(ai_msgs) >= 3:
            recent_tools: list[str] = []
            for m in ai_msgs[-3:]:
                if hasattr(m, "tool_calls") and m.tool_calls:
                    recent_tools.append(m.tool_calls[0]["name"])
                else:
                    parsed = _extract_text_tool_call(str(m.content))
                    if parsed:
                        recent_tools.append(parsed[0])
            if len(recent_tools) == 3 and len(set(recent_tools)) == 1:
                return END  # stuck calling the same tool repeatedly

        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        if isinstance(last, AIMessage) and _extract_text_tool_call(str(last.content)):
            return "tools"
        return END

    graph = StateGraph(_AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", call_tools)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


# ── Public create_agent ───────────────────────────────────────────────────────

def create_agent(
    tools: list,
    model: str,
    api_key: str | None = None,
    base_url: str = "http://localhost:11434/v1",
) -> Any:
    """Create a ReAct agent that works with both native and text-based tool calling.

    Uses ChatOllama for local Ollama endpoints.  If the model emits tool calls as
    plain JSON text (no native function-calling support) the custom graph intercepts
    and executes them before asking the model for its final answer.
    """
    if _is_ollama(base_url):
        from langchain_ollama import ChatOllama
        host = base_url.rstrip("/")
        if host.endswith("/v1"):
            host = host[:-3]
        verify = httpx_verify()
        llm = ChatOllama(
            model=model,
            base_url=host,
            temperature=0,
            client_kwargs={"verify": verify},
            async_client_kwargs={"verify": verify},
            sync_client_kwargs={"verify": verify},
        )
    else:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model,
            api_key=api_key or "ollama",
            base_url=base_url,
            temperature=0,
            http_client=create_httpx_client(timeout=None),
            http_async_client=create_async_httpx_client(timeout=None),
        )

    return _make_text_react_graph(llm, tools)


# ── Built-in tools ────────────────────────────────────────────────────────────

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
def web_search(query: str, max_results: int = 8) -> str:
    """Search the web for current information, news, and recent research.

    Uses DuckDuckGo full-text search (ddgs) for live results. Falls back to
    the Brave Search API if BRAVE_API_KEY is set in the environment.

    Args:
        query:       Search query (be specific — include year for recency).
        max_results: Number of results to return (default 8).

    Returns:
        Formatted search results with titles, URLs, and snippets.
    """
    import os as _os

    # ── Brave Search API (higher quality, needs API key) ─────────────────────
    brave_key = _os.environ.get("BRAVE_API_KEY", "").strip()
    if brave_key:
        try:
            resp = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": brave_key},
                params={"q": query, "count": max_results, "freshness": "pm"},
                timeout=10,
            )
            if resp.status_code == 200:
                items = resp.json().get("web", {}).get("results", [])
                if items:
                    lines = [f"# Web Search: \"{query}\"\n"]
                    for i, r in enumerate(items, 1):
                        lines.append(
                            f"### {i}. {r.get('title', '')}\n"
                            f"**URL:** {r.get('url', '')}\n"
                            f"{r.get('description', '')}\n"
                        )
                    return "\n".join(lines)
        except Exception:
            pass  # fall through to ddgs

    # ── DuckDuckGo full-text search (ddgs) ───────────────────────────────────
    try:
        from ddgs import DDGS
        results = list(DDGS(verify=httpx_verify()).text(query, max_results=max_results))
        if results:
            lines = [f"# Web Search: \"{query}\"\n"]
            for i, r in enumerate(results, 1):
                lines.append(
                    f"### {i}. {r.get('title', '')}\n"
                    f"**URL:** {r.get('href', '')}\n"
                    f"{r.get('body', '')}\n"
                )
            return "\n".join(lines)
        return f"No results found for: {query}"
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
