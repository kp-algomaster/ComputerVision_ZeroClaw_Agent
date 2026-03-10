"""Equation and key information extraction from research papers."""

from __future__ import annotations

import logging
import re

from cv_agent.http_client import httpx
from zeroclaw_tools import tool

from cv_agent.cache import get_cache
from cv_agent.config import load_config

logger = logging.getLogger(__name__)

# Patterns for LaTeX equation extraction from paper text
EQUATION_PATTERNS = [
    # Display math: $$ ... $$ or \[ ... \]
    re.compile(r"\$\$(.*?)\$\$", re.DOTALL),
    re.compile(r"\\\[(.*?)\\\]", re.DOTALL),
    # \begin{equation} ... \end{equation}
    re.compile(r"\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}", re.DOTALL),
    re.compile(r"\\begin\{align\*?\}(.*?)\\end\{align\*?\}", re.DOTALL),
    re.compile(r"\\begin\{gather\*?\}(.*?)\\end\{gather\*?\}", re.DOTALL),
    # Inline math with common CV formulas
    re.compile(r"\$([^$]{10,}?)\$"),
]

# Key information patterns
SECTION_KEYWORDS = {
    "loss_function": [
        r"loss\s+function", r"objective\s+function", r"training\s+loss",
        r"\\mathcal\{L\}", r"L_\{", r"\\ell",
    ],
    "architecture": [
        r"architecture", r"network\s+structure", r"model\s+design",
        r"encoder", r"decoder", r"backbone", r"head",
    ],
    "training": [
        r"training\s+detail", r"implementation\s+detail", r"hyperparameter",
        r"learning\s+rate", r"batch\s+size", r"optimizer", r"epoch",
    ],
    "dataset": [
        r"dataset", r"benchmark", r"evaluation\s+set", r"training\s+set",
        r"COCO", r"ImageNet", r"VOC", r"ADE20K", r"Cityscapes",
    ],
    "metric": [
        r"mAP", r"IoU", r"F1", r"precision", r"recall", r"accuracy",
        r"FPS", r"FLOP", r"parameter", r"latency",
    ],
}


def _call_llm(prompt: str, ttl: int | None = None) -> str:
    cfg = load_config()
    model = cfg.llm.model
    cache = get_cache(cfg)
    key = cache.make_key(model, prompt)
    if (hit := cache.get(key)) is not None:
        return hit
    base_url = cfg.llm.base_url.rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": cfg.llm.max_tokens,
    }
    headers = {}
    if cfg.llm.api_key:
        headers["Authorization"] = f"Bearer {cfg.llm.api_key}"
    with httpx.Client(timeout=120) as client:
        resp = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"]
    cache.set(key, result, ttl=ttl or cfg.cache.ttl_tools, key_hint=prompt[:80])
    return result


@tool
def extract_equations(paper_text: str) -> str:
    """Extract mathematical equations from paper text using pattern matching and LLM.

    Args:
        paper_text: The raw text content of a research paper (or relevant sections).

    Returns:
        Extracted equations formatted in LaTeX with labels and context.
    """
    # Phase 1: Regex extraction
    found_equations: list[str] = []
    for pattern in EQUATION_PATTERNS:
        for match in pattern.finditer(paper_text):
            eq = match.group(1).strip()
            if eq and len(eq) > 5:
                found_equations.append(eq)

    # Phase 2: LLM-based extraction for equations regex couldn't catch
    extraction_prompt = (
        "Extract ALL mathematical equations from the following research paper text. "
        "For each equation:\n"
        "1. Write it in LaTeX format\n"
        "2. Add a brief label (e.g., 'Cross-Entropy Loss', 'Attention Score')\n"
        "3. Note which section it appears in\n\n"
        "Format each as:\n"
        "**[Label]** (Section: ...)\n"
        "```latex\n<equation>\n```\n\n"
        f"Paper text:\n\n{paper_text[:8000]}"
    )
    llm_equations = _call_llm(extraction_prompt)

    # Combine results
    output_parts = ["# Extracted Equations\n"]

    if found_equations:
        output_parts.append("## Pattern-Matched Equations\n")
        for i, eq in enumerate(found_equations, 1):
            output_parts.append(f"### Equation {i}\n```latex\n{eq}\n```\n")

    output_parts.append("## LLM-Extracted Equations\n")
    output_parts.append(llm_equations)

    return "\n".join(output_parts)


@tool
def extract_key_info(paper_text: str, focus: str = "all") -> str:
    """Extract key information from a paper: architecture, losses, training details, results.

    Args:
        paper_text: The raw text content of a research paper.
        focus: What to focus on — 'all', 'architecture', 'loss', 'training', 'results'.

    Returns:
        Structured extraction of key information.
    """
    # Build focus-specific prompt
    if focus == "all":
        focus_instruction = (
            "Extract ALL of the following:\n"
            "1. **Core Contribution**: What is new/novel?\n"
            "2. **Architecture**: Network design, modules, components\n"
            "3. **Loss Functions**: All loss terms with equations in LaTeX\n"
            "4. **Training Details**: LR, optimizer, batch size, schedule, augmentations\n"
            "5. **Datasets**: What datasets are used for training/evaluation\n"
            "6. **Metrics & Results**: Key quantitative results and comparisons\n"
            "7. **Ablation Studies**: What was ablated and key findings\n"
            "8. **Limitations**: Stated or apparent limitations\n"
            "9. **Code/Data Availability**: Links to code repositories or datasets\n"
        )
    elif focus == "architecture":
        focus_instruction = (
            "Extract the network architecture details:\n"
            "- Backbone/encoder type and configuration\n"
            "- Novel modules or layers introduced\n"
            "- Input/output dimensions and formats\n"
            "- Number of parameters\n"
            "- FLOPs if mentioned\n"
            "- Connections/skip connections\n"
            "Include any architecture diagrams described in text."
        )
    elif focus == "loss":
        focus_instruction = (
            "Extract ALL loss functions:\n"
            "- Full equation in LaTeX\n"
            "- Component breakdown\n"
            "- Weighting factors/hyperparameters\n"
            "- What each term optimizes for\n"
        )
    elif focus == "training":
        focus_instruction = (
            "Extract training configuration:\n"
            "- Optimizer and learning rate (schedule)\n"
            "- Batch size, epochs, hardware\n"
            "- Data augmentations\n"
            "- Regularization (dropout, weight decay)\n"
            "- Pre-training details if any\n"
        )
    else:
        focus_instruction = (
            "Extract experimental results:\n"
            "- Main comparison tables\n"
            "- State-of-the-art comparisons\n"
            "- Ablation study results\n"
            "- Key takeaways\n"
        )

    prompt = (
        f"You are a computer vision research expert. {focus_instruction}\n\n"
        "Format your response in clean Markdown with headers and bullet points.\n"
        "Include LaTeX equations wrapped in $...$ or $$...$$ where appropriate.\n\n"
        f"Paper text:\n\n{paper_text[:12000]}"
    )

    return _call_llm(prompt)
