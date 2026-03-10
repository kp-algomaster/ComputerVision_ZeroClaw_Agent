"""Paper-to-code tools — scaffold implementation from ArXiv papers."""

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
    model = cfg.agents.paper_to_code.model_override or cfg.llm.model
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
    cache.set(key, result, ttl=ttl or cfg.cache.ttl_tools, key_hint=prompt[:80])
    return result


@tool
def scaffold_paper_implementation(arxiv_id_or_url: str) -> str:
    """Fetch a paper from ArXiv and scaffold a Python implementation.

    Args:
        arxiv_id_or_url: ArXiv paper ID or URL (e.g. 2312.00785 or full URL).

    Returns:
        Scaffolded implementation code and save path.
    """
    from cv_agent.tools.paper_fetch import fetch_arxiv_paper

    paper_info = fetch_arxiv_paper.invoke(arxiv_id_or_url)

    prompt = f"""\
You are an expert ML engineer. Based on this paper, write a complete PyTorch implementation scaffold.

Paper information:
{paper_info[:8000]}

Produce:
1. `model.py` — Full model architecture with all components, using proper nn.Module subclasses.
   Include type annotations, forward() with input/output shape comments.
2. `train.py` — Training loop with the paper's loss function(s), optimizer, and schedule.
3. `dataset.py` — Dataset class skeleton with __getitem__ and __len__.
4. `README.md` — Quick start instructions.

Separate each file with `## FILE: <filename>` headers.
Write real, runnable code — no placeholders or TODO stubs for core logic.
"""
    code = _call_llm(prompt)

    cfg = load_config()
    lines = paper_info.split("\n")
    title = next((l[2:].strip() for l in lines if l.startswith("# ")), "paper")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    safe_title = safe_title.strip().replace(" ", "_")[:60]
    timestamp = datetime.now().strftime("%Y%m%d")

    output_dir = Path(cfg.output.base_dir) / "implementations" / f"{timestamp}_{safe_title}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse and save individual files
    import re
    parts = re.split(r"^## FILE: (.+)$", code, flags=re.MULTILINE)
    saved: list[str] = []
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            fname = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            # Strip code fences if present
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            (output_dir / fname).write_text(content)
            saved.append(str(output_dir / fname))
    else:
        (output_dir / "implementation.py").write_text(code)
        saved.append(str(output_dir / "implementation.py"))

    return f"Implementation scaffolded in: {output_dir}\nFiles: {', '.join(saved)}\n\n{code[:2000]}..."


@tool
def generate_model_skeleton(architecture_description: str) -> str:
    """Generate a PyTorch model skeleton from an architecture description.

    Args:
        architecture_description: Text description of the model architecture
            (e.g. 'transformer encoder with 12 heads, patch embedding 16x16').

    Returns:
        PyTorch model code.
    """
    prompt = f"""\
Write a complete PyTorch nn.Module implementation for this architecture:

{architecture_description}

Requirements:
- All layers defined in __init__ with correct dimensions
- Full forward() with tensor shape comments at each stage
- Type annotations (torch.Tensor)
- Include a quick test in if __name__ == '__main__'
- No placeholder code — implement all components fully

Return only Python code.
"""
    return _call_llm(prompt)


@tool
def generate_training_loop(loss_fn: str, optimizer: str = "AdamW") -> str:
    """Generate a PyTorch training loop for a given loss function and optimizer.

    Args:
        loss_fn: Loss function description or name (e.g. 'InfoNCE contrastive loss',
                 'focal loss with alpha=0.25 gamma=2').
        optimizer: Optimizer name (e.g. 'AdamW', 'SGD with momentum').

    Returns:
        Complete training loop Python code.
    """
    prompt = f"""\
Write a complete PyTorch training loop using:
- Loss: {loss_fn}
- Optimizer: {optimizer}

Include:
- Loss function implementation (full, not a library call unless standard)
- Training step function
- Validation step function
- Mixed precision training (torch.cuda.amp)
- Gradient clipping
- Learning rate scheduling
- Metric logging (loss, primary metric)
- Early stopping

Return only Python code, production-quality, no stubs.
"""
    return _call_llm(prompt)
