"""Skill Creator — define, validate, load, and run custom user skills."""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import json
import logging
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILLS_DIR = _PROJECT_ROOT / "output" / ".skills"

# ── Blocked imports ────────────────────────────────────────────────────────────

BLOCKED_IMPORTS: set[str] = {
    "subprocess",
    "shutil",
    "ctypes",
    "multiprocessing",
    "signal",
    "socket",
    "http.server",
    "xmlrpc",
    "code",
    "codeop",
    "compileall",
    "py_compile",
}

BLOCKED_NAMES: set[str] = {
    "eval",
    "exec",
    "__import__",
    "compile",
    "execfile",
    "breakpoint",
}


# ── Pydantic models ───────────────────────────────────────────────────────────

class EnvVarSpec(BaseModel):
    name: str
    description: str = ""
    required: bool = True
    default: str | None = None


class SkillModel(BaseModel):
    source: str  # "huggingface" | "local" | "ollama"
    id: str
    label: str = ""
    size_gb: float | None = None
    path_override: str | None = None


class SkillPower(BaseModel):
    device: str = "auto"
    env_vars: list[EnvVarSpec] = Field(default_factory=list)
    server_id: str | None = None
    timeout_s: int = 120


class SkillManifest(BaseModel):
    id: str
    name: str
    description: str = ""
    icon: str = "🧩"
    category: str = "custom"
    script_file: str = "skill.py"
    entry_point: str = "run"
    parameters: dict[str, Any] = Field(default_factory=dict)
    model: SkillModel | None = None
    power: SkillPower = Field(default_factory=SkillPower)
    created_at: str = ""
    updated_at: str = ""
    version: int = 1


class ValidationError(BaseModel):
    line: int
    message: str


class ValidationResult(BaseModel):
    valid: bool
    entry_points: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    blocked_imports: list[str] = Field(default_factory=list)
    blocked_names: list[str] = Field(default_factory=list)
    errors: list[ValidationError] = Field(default_factory=list)


class CreateSkillRequest(BaseModel):
    name: str
    description: str = ""
    icon: str = "🧩"
    script: str
    entry_point: str = "run"
    model: SkillModel | None = None
    power: SkillPower = Field(default_factory=SkillPower)


class RunSkillRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower().strip())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _skills_dir() -> Path:
    _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return _SKILLS_DIR


# ── Validator ──────────────────────────────────────────────────────────────────

def validate_script(source: str) -> ValidationResult:
    """Parse and validate a Python script for use as a custom skill."""
    errors: list[ValidationError] = []
    imports: list[str] = []
    blocked: list[str] = []
    blocked_names_found: list[str] = []
    entry_points: list[str] = []

    # Syntax check
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ValidationResult(
            valid=False,
            errors=[ValidationError(line=exc.lineno or 1, message=str(exc.msg))],
        )

    for node in ast.walk(tree):
        # Collect imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                imports.append(alias.name)
                if top in BLOCKED_IMPORTS:
                    blocked.append(alias.name)
                    errors.append(ValidationError(
                        line=node.lineno,
                        message=f"Blocked import: {alias.name}",
                    ))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                imports.append(node.module)
                if top in BLOCKED_IMPORTS:
                    blocked.append(node.module)
                    errors.append(ValidationError(
                        line=node.lineno,
                        message=f"Blocked import: {node.module}",
                    ))

        # Check for blocked builtins (eval, exec, __import__, etc.)
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name and name in BLOCKED_NAMES:
                blocked_names_found.append(name)
                errors.append(ValidationError(
                    line=node.lineno,
                    message=f"Blocked builtin call: {name}()",
                ))

        # Detect entry points: functions decorated with @tool, or named 'run'
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            is_tool = any(
                (isinstance(d, ast.Name) and d.id == "tool")
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "tool")
                for d in node.decorator_list
            )
            if is_tool or node.name == "run":
                entry_points.append(node.name)

    return ValidationResult(
        valid=len(errors) == 0,
        entry_points=entry_points,
        imports=imports,
        blocked_imports=blocked,
        blocked_names=blocked_names_found,
        errors=errors,
    )


# ── Skill CRUD ─────────────────────────────────────────────────────────────────

def save_skill(req: CreateSkillRequest, skill_id: str | None = None) -> SkillManifest:
    """Create or update a skill on disk. Returns the manifest."""
    sid = skill_id or _slugify(req.name)
    if not sid:
        raise ValueError("Skill name produces an empty ID")

    skill_dir = _skills_dir() / sid
    skill_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = skill_dir / "manifest.json"
    now = _now_iso()

    # If updating, preserve created_at and bump version
    version = 1
    created_at = now
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        version = existing.get("version", 1) + 1
        created_at = existing.get("created_at", now)

    manifest = SkillManifest(
        id=sid,
        name=req.name,
        description=req.description,
        icon=req.icon,
        entry_point=req.entry_point,
        model=req.model,
        power=req.power,
        created_at=created_at,
        updated_at=now,
        version=version,
    )

    # Write script
    script_path = skill_dir / manifest.script_file
    script_path.write_text(req.script, encoding="utf-8")

    # Write manifest
    manifest_path.write_text(
        json.dumps(manifest.model_dump(), indent=2, default=str),
        encoding="utf-8",
    )

    # Evict from module cache if reloading
    _evict_skill(sid)

    return manifest


def get_skill(skill_id: str) -> tuple[SkillManifest, str] | None:
    """Return (manifest, script_source) or None if not found."""
    skill_dir = _skills_dir() / skill_id
    manifest_path = skill_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = SkillManifest(**json.loads(manifest_path.read_text()))
    script_path = skill_dir / manifest.script_file
    script_source = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
    return manifest, script_source


def list_skills() -> list[dict[str, Any]]:
    """List all custom skills with computed status."""
    results = []
    skills_dir = _skills_dir()
    for manifest_path in sorted(skills_dir.glob("*/manifest.json")):
        try:
            manifest = SkillManifest(**json.loads(manifest_path.read_text()))
            status = _compute_status(manifest)
            results.append({**manifest.model_dump(), "status": status})
        except Exception as exc:
            logger.warning("Skipping bad skill manifest %s: %s", manifest_path, exc)
    return results


def delete_skill(skill_id: str) -> bool:
    """Delete a skill directory. Returns True if deleted."""
    skill_dir = _skills_dir() / skill_id
    if not skill_dir.exists():
        return False
    _evict_skill(skill_id)
    shutil.rmtree(skill_dir)
    return True


# ── Status computation ─────────────────────────────────────────────────────────

def _compute_status(manifest: SkillManifest) -> str:
    if manifest.model:
        from cv_agent.local_model_manager import is_model_downloaded
        # Only check for huggingface/local models (not ollama)
        if manifest.model.source in ("huggingface", "local"):
            if not is_model_downloaded(manifest.model.id):
                return "needs-model"

    if manifest.power.env_vars:
        for var in manifest.power.env_vars:
            if var.required and not os.environ.get(var.name) and not var.default:
                return "needs-power"

    return "ready"


# ── Module loader & cache ──────────────────────────────────────────────────────

_SKILL_CACHE: dict[str, ModuleType] = {}
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="skill-runner")


def _module_name(skill_id: str) -> str:
    return f"_cv_skill_{skill_id.replace('-', '_')}"


def _evict_skill(skill_id: str) -> None:
    mod_name = _module_name(skill_id)
    _SKILL_CACHE.pop(skill_id, None)
    sys.modules.pop(mod_name, None)


def load_skill_module(skill_id: str) -> ModuleType:
    """Load (or return cached) skill module."""
    if skill_id in _SKILL_CACHE:
        return _SKILL_CACHE[skill_id]

    skill_dir = _skills_dir() / skill_id
    manifest_path = skill_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Skill '{skill_id}' not found")

    manifest = SkillManifest(**json.loads(manifest_path.read_text()))
    script_path = skill_dir / manifest.script_file
    if not script_path.exists():
        raise FileNotFoundError(f"Script for skill '{skill_id}' not found")

    mod_name = _module_name(skill_id)

    # Inject environment variables before loading
    _inject_env(manifest)

    spec = importlib.util.spec_from_file_location(mod_name, str(script_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)

    _SKILL_CACHE[skill_id] = module
    return module


def _inject_env(manifest: SkillManifest) -> None:
    """Set env vars for a skill before execution."""
    # Device
    if manifest.power.device and manifest.power.device != "auto":
        os.environ["DEVICE"] = manifest.power.device

    # Model path
    if manifest.model:
        os.environ["MODEL_ID"] = manifest.model.id
        if manifest.model.path_override:
            os.environ["MODEL_PATH"] = manifest.model.path_override
        elif manifest.model.source in ("huggingface", "local"):
            from cv_agent.local_model_manager import get_model_local_path
            os.environ["MODEL_PATH"] = str(get_model_local_path(manifest.model.id))

    # Custom env vars (only set defaults for unset vars)
    for var in manifest.power.env_vars:
        if var.default and not os.environ.get(var.name):
            os.environ[var.name] = var.default

    # Server URL
    if manifest.power.server_id:
        from cv_agent.server_manager import SERVER_REGISTRY
        for srv in SERVER_REGISTRY:
            if srv.id == manifest.power.server_id:
                os.environ["SERVER_URL"] = srv.url
                break


# ── Runner ─────────────────────────────────────────────────────────────────────

async def run_skill(skill_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a custom skill's entry point with timeout enforcement."""
    skill_dir = _skills_dir() / skill_id
    manifest_path = skill_dir / "manifest.json"
    if not manifest_path.exists():
        return {"error": f"Skill '{skill_id}' not found"}

    manifest = SkillManifest(**json.loads(manifest_path.read_text()))
    status = _compute_status(manifest)
    if status != "ready":
        return {"error": f"Skill is not ready (status: {status})"}

    timeout = manifest.power.timeout_s or 120

    def _exec():
        module = load_skill_module(skill_id)
        fn = getattr(module, manifest.entry_point, None)
        if fn is None:
            return {"error": f"Entry point '{manifest.entry_point}' not found in skill"}
        t0 = time.monotonic()
        result = fn(**(params or {}))
        duration = round(time.monotonic() - t0, 3)
        return {"result": result, "duration_s": duration}

    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_executor, _exec),
            timeout=timeout,
        )
        return result
    except asyncio.TimeoutError:
        _evict_skill(skill_id)
        return {"error": f"Skill execution timed out after {timeout}s"}
    except Exception as exc:
        _evict_skill(skill_id)
        return {"error": f"Skill execution failed: {exc}"}


def reload_skill(skill_id: str) -> None:
    """Force-evict a skill from the cache so the next call reloads it."""
    _evict_skill(skill_id)


# ── Name collision check ──────────────────────────────────────────────────────

_BUILTIN_SKILL_IDS: set[str] = {
    "research_blog", "weekly_digest", "email_reports", "2d_image_processing",
    "3d_image_processing", "video_understanding", "image_stitching",
    "object_detection", "object_tracking", "segment_anything",
    "text_to_image", "super_resolution", "image_denoising",
    "document_extraction", "paper_to_spec", "knowledge_graph",
    "equation_extraction", "text_to_diagram", "kaggle_competition",
    "model_fine_tuning", "dataset_analysis", "dataset_visualization",
    "agentic_workflows",
}


def check_name_collision(name: str) -> str | None:
    """Return an error message if the name collides with a built-in skill."""
    slug = _slugify(name)
    if slug in _BUILTIN_SKILL_IDS:
        return f"Name '{name}' conflicts with built-in skill '{slug}'. Choose a different name."
    return None
