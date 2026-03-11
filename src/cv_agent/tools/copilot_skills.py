"""Adapter: converts LangChain @tool functions to Copilot SDK skills."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, create_model

logger = logging.getLogger(__name__)

try:
    from copilot import define_tool  # type: ignore[import-untyped]
    from copilot.types import ToolInvocation, ToolResult  # type: ignore[import-untyped]

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    define_tool = None  # type: ignore[assignment]
    ToolInvocation = None  # type: ignore[assignment]
    ToolResult = None  # type: ignore[assignment]

# Map JSON schema type strings to Python types used by pydantic.create_model
_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _schema_to_pydantic(tool: BaseTool) -> type[BaseModel]:
    """Build a Pydantic BaseModel from a LangChain tool's args schema.

    If the tool already has a Pydantic args_schema, return it directly.
    Otherwise, parse the JSON schema to build an equivalent model.
    Falls back to a single ``input: str`` field for unstructured tools.
    """
    if tool.args_schema is not None and issubclass(tool.args_schema, BaseModel):
        return tool.args_schema

    try:
        schema = tool.get_input_schema().model_json_schema()
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])

        fields: dict[str, Any] = {}
        for field_name, field_def in props.items():
            py_type = _JSON_TYPE_MAP.get(field_def.get("type", "string"), str)
            default = ... if field_name in required else None
            fields[field_name] = (py_type, default)

        if not fields:
            raise ValueError("no fields")

        return create_model(f"{tool.name.title().replace('_', '')}Params", **fields)

    except Exception:
        # Fallback: single string input field
        return create_model(f"{tool.name.title().replace('_', '')}Params", input=(str, ...))


def build_copilot_skills(tools: list[BaseTool]) -> list[Any]:
    """Wrap a list of LangChain BaseTool objects as Copilot SDK Tool skills.

    Returns an empty list if the SDK is not installed, so callers can always
    safely pass the result to ``create_session(tools=[...])``.
    """
    if not _SDK_AVAILABLE:
        return []

    skills: list[Any] = []
    for tool in tools:
        try:
            ParamsModel = _schema_to_pydantic(tool)
            # Capture tool in closure
            _tool = tool

            async def _handler(
                params: BaseModel,
                invocation: Any,
                _t: BaseTool = _tool,
            ) -> ToolResult:
                try:
                    result = await asyncio.to_thread(_t.invoke, params.model_dump())
                    return ToolResult(
                        text_result_for_llm=str(result)[:4096],
                        result_type="success",
                    )
                except Exception as exc:
                    return ToolResult(
                        text_result_for_llm=f"Tool error: {exc}",
                        result_type="failure",
                        error=str(exc),
                    )

            skill = define_tool(
                name=tool.name,
                description=tool.description or tool.name,
                handler=_handler,
                params_type=ParamsModel,
            )
            skills.append(skill)
        except Exception as exc:
            logger.warning("Could not wrap tool '%s' as Copilot skill: %s", tool.name, exc)

    logger.debug("Registered %d Copilot skills from %d LangChain tools", len(skills), len(tools))
    return skills
