"""Hardware probe via llmfit — identifies which LLM/vision models can run locally.

Uses https://github.com/AlexsJones/llmfit to analyse RAM, VRAM, and CPU resources
then scores ~200 models for fit. The agent calls ``check_runnable_models`` to decide
which Ollama or MLX model to load, and ``probe_hardware_summary`` at startup to
auto-configure the best available local model.

Install llmfit:
    brew install llmfit
    # or: curl -fsSL https://raw.githubusercontent.com/AlexsJones/llmfit/main/install.sh | sh
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from zeroclaw_tools import tool

logger = logging.getLogger(__name__)


@dataclass
class ModelFit:
    name: str
    provider: str
    fit: str          # perfect | good | marginal | too_tight
    quantization: str
    params_b: float
    vram_gb: float
    composite_score: float
    use_cases: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ModelFit:
        return cls(
            name=d.get("name", ""),
            provider=d.get("provider", ""),
            fit=d.get("fit", "unknown"),
            quantization=d.get("quantization", ""),
            params_b=float(d.get("params_b", 0)),
            vram_gb=float(d.get("vram_gb", 0)),
            composite_score=float(d.get("composite_score", 0)),
            use_cases=d.get("use_cases", []),
        )


@dataclass
class HardwareInfo:
    ram_gb: float = 0.0
    cpu_cores: int = 0
    gpu_vram_gb: float = 0.0
    acceleration: str = "cpu"   # metal | cuda | rocm | cpu

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HardwareInfo:
        gpus = d.get("gpus", [])
        total_vram = sum(float(g.get("vram_gb", 0)) for g in gpus)
        acceleration = d.get("acceleration", "cpu")
        if isinstance(acceleration, list):
            acceleration = acceleration[0] if acceleration else "cpu"
        return cls(
            ram_gb=float(d.get("ram_gb", 0)),
            cpu_cores=int(d.get("cpu_cores", 0)),
            gpu_vram_gb=total_vram,
            acceleration=str(acceleration),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def is_llmfit_available() -> bool:
    """Return True if llmfit binary is on PATH."""
    return shutil.which("llmfit") is not None


def _run_llmfit_json(*args: str, timeout: int = 30) -> dict | list | None:
    """Run an llmfit sub-command and return parsed JSON, or None on failure."""
    if not is_llmfit_available():
        logger.warning("llmfit not found — install: brew install llmfit")
        return None
    try:
        result = subprocess.run(
            ["llmfit", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning("llmfit error: %s", result.stderr.strip())
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logger.warning("llmfit call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_hardware_info() -> HardwareInfo | None:
    """Return detected hardware via ``llmfit system --json``."""
    data = _run_llmfit_json("system", "--json")
    if not isinstance(data, dict):
        return None
    return HardwareInfo.from_dict(data)


def get_runnable_models(
    use_case: str = "multimodal",
    min_fit: str = "good",
    limit: int = 10,
) -> list[ModelFit]:
    """Return models that fit this hardware via ``llmfit recommend --json``.

    Args:
        use_case: multimodal | general | coding | reasoning | chat | embedding
        min_fit:  perfect | good | marginal
        limit:    maximum number of models to return
    """
    data = _run_llmfit_json(
        "recommend",
        "--json",
        f"--limit={limit}",
        f"--use-case={use_case}",
        f"--min-fit={min_fit}",
    )
    if not isinstance(data, list):
        return []
    return [ModelFit.from_dict(m) for m in data]


def select_best_ollama_model(models: list[ModelFit]) -> str | None:
    """Return the highest-scoring perfect/good model as an Ollama tag (name:quant)."""
    for m in sorted(models, key=lambda x: x.composite_score, reverse=True):
        if m.fit in ("perfect", "good") and m.name:
            quant = m.quantization.lower() if m.quantization else "q4_k_m"
            return f"{m.name.lower()}:{quant}"
    return None


def probe_hardware_summary() -> dict[str, Any]:
    """Run a full hardware probe and return a structured summary.

    Returns a dict with keys:
        llmfit_available, hardware, vision_models, general_models,
        recommended_ollama_model
    """
    hw = get_hardware_info()
    vision_models = get_runnable_models(use_case="multimodal", min_fit="good", limit=5)
    general_models = get_runnable_models(use_case="general", min_fit="good", limit=5)
    best = select_best_ollama_model(vision_models) or select_best_ollama_model(general_models)

    return {
        "llmfit_available": is_llmfit_available(),
        "hardware": {
            "ram_gb": hw.ram_gb if hw else 0,
            "cpu_cores": hw.cpu_cores if hw else 0,
            "gpu_vram_gb": hw.gpu_vram_gb if hw else 0,
            "acceleration": hw.acceleration if hw else "unknown",
        },
        "vision_models": [
            {
                "name": m.name,
                "provider": m.provider,
                "fit": m.fit,
                "quantization": m.quantization,
                "score": round(m.composite_score, 1),
            }
            for m in vision_models
        ],
        "general_models": [
            {
                "name": m.name,
                "provider": m.provider,
                "fit": m.fit,
                "quantization": m.quantization,
                "score": round(m.composite_score, 1),
            }
            for m in general_models
        ],
        "recommended_ollama_model": best,
    }


# ---------------------------------------------------------------------------
# ZeroClaw tool (callable by the agent)
# ---------------------------------------------------------------------------

@tool
def check_runnable_models(use_case: str = "multimodal") -> str:
    """Probe local hardware with llmfit to identify which LLM/vision models can run on this machine.

    Analyses RAM, VRAM, CPU cores, and acceleration backend (Metal/CUDA/ROCm/CPU),
    then scores ~200 HuggingFace models and returns ranked recommendations.

    Args:
        use_case: Optimise recommendations for — multimodal, general, coding,
                  reasoning, chat, or embedding. Default: multimodal.

    Returns:
        Formatted table of hardware specs and runnable model recommendations with
        the suggested Ollama pull tag for the best fitting model.
    """
    if not is_llmfit_available():
        return (
            "llmfit is not installed.\n\n"
            "Install with:  brew install llmfit\n"
            "Or visit:      https://github.com/AlexsJones/llmfit"
        )

    hw = get_hardware_info()
    models = get_runnable_models(use_case=use_case, min_fit="marginal", limit=20)

    lines: list[str] = []

    if hw:
        lines += [
            f"## Hardware",
            f"RAM: {hw.ram_gb:.0f} GB  |  VRAM: {hw.gpu_vram_gb:.0f} GB  "
            f"|  Acceleration: {hw.acceleration}  |  CPU cores: {hw.cpu_cores}",
            "",
        ]

    if not models:
        lines.append(f"No runnable models found for use_case='{use_case}'.")
        return "\n".join(lines)

    lines += [f"## Models for use_case='{use_case}'", ""]
    lines.append(f"{'Model':<36} {'Provider':<12} {'Fit':<10} {'Quant':<10} {'Score':>6}")
    lines.append("-" * 78)
    for m in sorted(models, key=lambda x: x.composite_score, reverse=True):
        lines.append(
            f"{m.name:<36} {m.provider:<12} {m.fit:<10} {m.quantization:<10} "
            f"{m.composite_score:>6.1f}"
        )

    best = select_best_ollama_model(models)
    if best:
        lines += ["", f"**Recommended Ollama pull tag:** `{best}`", f"  ollama pull {best}"]

    return "\n".join(lines)
