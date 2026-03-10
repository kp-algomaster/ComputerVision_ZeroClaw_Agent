"""Data visualization tools — generate chart code and extract paper metrics."""

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
    model = cfg.agents.data_visualization.model_override or cfg.llm.model
    cache = get_cache(cfg)
    key = cache.make_key(model, prompt)
    if (hit := cache.get(key)) is not None:
        return hit
    base_url = cfg.llm.base_url.rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
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
def generate_plot_code(
    data_description: str,
    chart_type: str = "bar",
    library: str = "matplotlib",
) -> str:
    """Generate Python plotting code for a described dataset.

    Args:
        data_description: Description of the data (columns, values, context).
        chart_type: Plot type — 'bar', 'line', 'scatter', 'heatmap', 'box', 'radar'.
        library: Plotting library — 'matplotlib', 'plotly', 'seaborn'.

    Returns:
        Runnable Python plotting code.
    """
    prompt = f"""\
Write complete, runnable Python code to create a {chart_type} chart using {library}.

Data description:
{data_description}

Requirements:
- Include sample/placeholder data matching the description
- Use proper labels, title, and legend
- Apply a clean, publication-quality style
- Save the figure to a file (output/plots/<descriptive_name>.png or .html)
- Include plt.tight_layout() and proper figure sizing
- No external data files required — embed the data in the script

Return only the Python code, no explanation.
"""
    return _call_llm(prompt)


@tool
def extract_paper_metrics(paper_text: str) -> str:
    """Extract quantitative results and metrics tables from paper text.

    Args:
        paper_text: Paper text containing results sections, tables, or abstracts.

    Returns:
        Structured Markdown table of extracted metrics, baselines, and results.
    """
    prompt = f"""\
Extract all quantitative results from this paper text into structured Markdown tables.

For each experiment or benchmark found:
1. Create a Markdown table with columns: Method | Dataset | Metric | Score
2. Bold the best results per column
3. Add a brief note on what each metric measures

Paper text:
{paper_text[:10000]}

Output only the Markdown tables and brief notes, no preamble.
"""
    return _call_llm(prompt)


@tool
def save_plot_script(filename: str, code: str) -> str:
    """Save a plot script to the output directory.

    Args:
        filename: Script filename without extension (e.g. 'detection_comparison').
        code: Python code to save.

    Returns:
        Path to the saved script.
    """
    cfg = load_config()
    output_dir = Path(cfg.output.base_dir) / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in filename)
    path = output_dir / f"{timestamp}_{safe_name}.py"
    path.write_text(code)
    return f"Plot script saved: {path}"
