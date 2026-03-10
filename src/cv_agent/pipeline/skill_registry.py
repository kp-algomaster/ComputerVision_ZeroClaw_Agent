from __future__ import annotations

import re
from typing import Any

from cv_agent.pipeline.models import SkillDefinition, SkillCategory

# Map from tool function module suffix → display category
_MODULE_CATEGORY: dict[str, str] = {
    "vision": SkillCategory.VISION,
    "mlx_vision": SkillCategory.VISION,
    "segment_anything": SkillCategory.VISION,
    "ocr": SkillCategory.VISION,
    "paper_fetch": SkillCategory.RESEARCH,
    "equation_extract": SkillCategory.RESEARCH,
    "knowledge_graph": SkillCategory.RESEARCH,
    "spec_generator": SkillCategory.RESEARCH,
    "text_to_diagram": SkillCategory.CONTENT,
    "blog_writer": SkillCategory.CONTENT,
    "data_visualization": SkillCategory.CONTENT,
    "hardware_probe": SkillCategory.UTILITY,
    "remote": SkillCategory.UTILITY,
    "model_training": SkillCategory.UTILITY,
    "website_maintenance": SkillCategory.UTILITY,
    "topic_cluster": SkillCategory.RESEARCH,
}

_SPECIAL_SKILLS: list[SkillDefinition] = [
    SkillDefinition(
        name="__inputs__",
        display_name="Inputs",
        description="Pipeline entry point. Defines the data passed to the first block.",
        category=SkillCategory.SPECIAL,
        parameter_schema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to an image file."},
                "text": {"type": "string", "description": "Plain text input."},
                "url": {"type": "string", "description": "URL input."},
            },
        },
    ),
    SkillDefinition(
        name="__outputs__",
        display_name="Outputs",
        description="Pipeline exit point. Captures and displays the final result.",
        category=SkillCategory.SPECIAL,
        parameter_schema={"type": "object", "properties": {}},
    ),
]


def _tool_category(tool: Any) -> str:
    if tool.name.startswith("delegate_"):
        return SkillCategory.AGENTS
    func = getattr(tool, "func", None)
    if func is None:
        return SkillCategory.UTILITY
    module: str = getattr(func, "__module__", "") or ""
    # zeroclaw_tools built-ins → Utility
    if "zeroclaw_tools" in module:
        return SkillCategory.UTILITY
    # cv_agent.tools.<module_suffix>
    parts = module.rsplit(".", 1)
    suffix = parts[-1] if len(parts) > 1 else module
    return _MODULE_CATEGORY.get(suffix, SkillCategory.UTILITY)


def _display_name(tool_name: str) -> str:
    if tool_name.startswith("delegate_"):
        bare = tool_name[len("delegate_"):]
        # blog_writer → "Blog Writer Agent"
        return " ".join(w.capitalize() for w in bare.split("_")) + " Agent"
    return " ".join(w.capitalize() for w in re.split(r"[_\-]", tool_name))


def _tool_to_skill(tool: Any) -> SkillDefinition:
    schema: dict[str, Any] = {}
    if tool.args_schema is not None:
        try:
            schema = tool.args_schema.model_json_schema()
        except Exception:
            schema = {}
    return SkillDefinition(
        name=tool.name,
        display_name=_display_name(tool.name),
        description=tool.description or "",
        category=_tool_category(tool),
        parameter_schema=schema,
    )


class SkillRegistryAdapter:
    """Converts the live build_tools() list into SkillDefinition objects for the Playground."""

    def __init__(self, tools: list[Any]) -> None:
        self._skills: list[SkillDefinition] = [_tool_to_skill(t) for t in tools]

    def list_skills(self) -> list[SkillDefinition]:
        return _SPECIAL_SKILLS + self._skills

    def get_skill(self, name: str) -> SkillDefinition | None:
        if name in ("__inputs__", "__outputs__"):
            return next((s for s in _SPECIAL_SKILLS if s.name == name), None)
        return next((s for s in self._skills if s.name == name), None)
