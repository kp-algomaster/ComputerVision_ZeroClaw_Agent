"""Model training tools — config generation, cost estimation, training script scaffolding."""

from __future__ import annotations

import json
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
    model = cfg.agents.model_training.model_override or cfg.llm.model
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
def generate_training_config(
    model_type: str,
    dataset_path: str,
    task: str = "classification",
) -> str:
    """Generate a training configuration YAML for a CV model.

    Args:
        model_type: Model architecture (e.g. 'resnet50', 'vit_base', 'yolov8').
        dataset_path: Path to dataset directory.
        task: Task type — 'classification', 'detection', 'segmentation'.

    Returns:
        Training config as YAML and save path.
    """
    prompt = f"""\
Generate a complete training configuration YAML for:
- Model: {model_type}
- Task: {task}
- Dataset path: {dataset_path}

Include: epochs, batch_size, learning_rate, optimizer, lr_scheduler, augmentations,
checkpoint_dir, log_dir, mixed_precision, early_stopping, evaluation_interval.
Use sensible defaults from recent literature. Output valid YAML only.
"""
    config_yaml = _call_llm(prompt)

    cfg = load_config()
    output_dir = Path(cfg.output.base_dir) / "training_configs"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = model_type.replace("/", "_").replace(":", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{timestamp}_{safe_name}_{task}_config.yaml"
    path.write_text(config_yaml)
    return f"Config saved: {path}\n\n```yaml\n{config_yaml}\n```"


@tool
def estimate_training_cost(config_json: str) -> str:
    """Estimate GPU hours and cloud cost for a training run.

    Args:
        config_json: JSON string with keys: model, dataset_size_gb, epochs,
                     batch_size, gpu_type (e.g. 'A100', 'RTX4090').

    Returns:
        Cost and time estimate breakdown.
    """
    try:
        cfg_data = json.loads(config_json)
    except json.JSONDecodeError:
        cfg_data = {"raw": config_json}

    prompt = f"""\
Estimate training time and cost for this configuration:
{json.dumps(cfg_data, indent=2)}

Provide:
1. Estimated GPU hours
2. Approximate wall-clock time on the specified GPU
3. Estimated cost on AWS/GCP/RunPod ($/hr rates for {cfg_data.get('gpu_type', 'A100')})
4. Memory requirements (VRAM)
5. Recommended batch size adjustments if needed

Base estimates on typical CV model training benchmarks.
"""
    return _call_llm(prompt)


@tool
def scaffold_training_script(framework: str = "pytorch", task: str = "classification") -> str:
    """Generate a training script skeleton for a given framework and task.

    Args:
        framework: Deep learning framework — 'pytorch', 'pytorch-lightning', 'huggingface'.
        task: CV task — 'classification', 'detection', 'segmentation', 'self-supervised'.

    Returns:
        Training script as Python code and save path.
    """
    prompt = f"""\
Write a complete, runnable Python training script using {framework} for {task}.

Include:
- Dataset loading with augmentations (torchvision.transforms or albumentations)
- Model definition / loading from timm or torchvision
- Training loop with progress bar (tqdm)
- Validation loop with metric tracking
- Checkpoint saving (best model)
- WandB or TensorBoard logging
- argparse for hyperparameters
- Proper __main__ guard

Write production-quality code. No placeholder comments.
"""
    code = _call_llm(prompt)

    cfg = load_config()
    output_dir = Path(cfg.output.base_dir) / "training_scripts"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{timestamp}_{framework}_{task}_train.py"
    path.write_text(code)
    return f"Script saved: {path}\n\n```python\n{code[:3000]}\n```"
