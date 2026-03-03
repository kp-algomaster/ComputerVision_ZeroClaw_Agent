"""Spec.md generator — converts research papers into spec-driven development files."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader
from zeroclaw_tools import tool

from cv_agent.config import load_config

logger = logging.getLogger(__name__)

SPEC_SYSTEM_PROMPT = """\
You are a senior ML engineer converting a research paper into a spec.md for implementation.
The spec must be precise enough for a developer to implement the paper without reading it.

Structure your output EXACTLY as follows:

# <Paper Title> — Implementation Spec

## 1. Overview
- One-paragraph summary of the core contribution
- Why this matters (practical impact)

## 2. Problem Statement
- What problem does this solve?
- What are the limitations of prior work?

## 3. Architecture
- Complete architecture diagram (ASCII or description)
- Input/output tensor shapes at each stage
- Module-by-module breakdown

## 4. Mathematical Formulation
- ALL equations in LaTeX ($$...$$)
- Variable definitions
- Loss function components with weights

## 5. Algorithm
- Step-by-step pseudocode
- Training loop specifics
- Inference pipeline

## 6. Implementation Requirements
### 6.1 Dependencies
- Framework (PyTorch/TensorFlow version)
- Required libraries

### 6.2 Data Pipeline
- Expected input format
- Preprocessing steps
- Augmentations

### 6.3 Model Configuration
- Hyperparameters table
- Default values from paper

### 6.4 Training Configuration
- Optimizer, LR schedule
- Batch size, epochs
- Hardware requirements (GPU memory)

## 7. Evaluation
- Metrics to track
- Benchmark datasets
- Expected performance targets

## 8. Acceptance Criteria
- Numbered list of testable requirements
- Performance thresholds from the paper

## 9. References
- Original paper link
- Related implementations
- Useful resources
"""


@tool
def generate_spec(paper_text: str, paper_title: str = "Untitled Paper") -> str:
    """Generate a spec.md file from paper text for spec-driven development.

    Extracts equations, architecture details, training configs, and formats them
    into a structured specification that developers can implement from directly.

    Args:
        paper_text: Full text or key sections of the paper.
        paper_title: Title of the paper.

    Returns:
        Path to the generated spec.md file and a preview.
    """
    cfg = load_config()
    base_url = cfg.llm.base_url.rstrip("/")

    prompt = (
        f"{SPEC_SYSTEM_PROMPT}\n\n"
        f"Convert this paper into a spec.md:\n\n"
        f"Title: {paper_title}\n\n"
        f"{paper_text[:15000]}"
    )

    payload = {
        "model": cfg.llm.model,
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
        spec_content = resp.json()["choices"][0]["message"]["content"]

    # Save to file
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in paper_title)
    safe_title = safe_title.strip().replace(" ", "_")[:80]
    timestamp = datetime.now().strftime("%Y%m%d")

    output_dir = Path(cfg.spec.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    spec_path = output_dir / f"{timestamp}_{safe_title}_spec.md"
    spec_path.write_text(spec_content)

    return f"Spec generated: {spec_path}\n\n---\n\n{spec_content[:2000]}..."


@tool
def generate_spec_from_url(arxiv_url: str) -> str:
    """Fetch a paper from ArXiv and generate a spec.md in one step.

    Args:
        arxiv_url: ArXiv paper URL or ID (e.g., https://arxiv.org/abs/2312.00785).

    Returns:
        Path to generated spec.md and preview.
    """
    from cv_agent.tools.paper_fetch import fetch_arxiv_paper, _extract_arxiv_id

    # Get paper metadata
    paper_info = fetch_arxiv_paper.invoke(arxiv_url)

    # Extract title from the response
    lines = paper_info.split("\n")
    title = "Untitled"
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Generate spec from the abstract and metadata
    return generate_spec.invoke({"paper_text": paper_info, "paper_title": title})
