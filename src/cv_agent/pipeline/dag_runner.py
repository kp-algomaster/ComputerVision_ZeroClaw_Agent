from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from typing import Any, Callable, Coroutine

from cv_agent.pipeline.models import BlockInstance, BlockStatus, Edge, PipelineGraph, RunStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Topological sort (Kahn's algorithm) + cycle detection
# ---------------------------------------------------------------------------

def topological_sort(nodes: list[BlockInstance], edges: list[Edge]) -> list[BlockInstance]:
    """Return nodes in topological order.  Raises ValueError if graph has cycles."""
    node_map = {n.id: n for n in nodes}
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}
    successors: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        in_degree[edge.target_node_id] += 1
        successors[edge.source_node_id].append(edge.target_node_id)

    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    result: list[BlockInstance] = []

    while queue:
        nid = queue.popleft()
        result.append(node_map[nid])
        for succ in successors[nid]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    if len(result) != len(nodes):
        raise ValueError("Pipeline graph contains a cycle — cannot execute.")

    return result


def has_cycle(nodes: list[BlockInstance], edges: list[Edge]) -> bool:
    try:
        topological_sort(nodes, edges)
        return False
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# FR-024 implicit pass-through data binding
# ---------------------------------------------------------------------------

def _bind_inputs(
    skill_name: str,
    upstream_output: Any,
    block_config: dict[str, Any],
    parameter_schema: dict[str, Any],
) -> dict[str, Any]:
    """Build the kwargs dict for a block call using FR-024 binding rules.

    For the Inputs node: the block's config fields are passed by key-match to
    the downstream block, falling back to first-required-param injection.
    For all other nodes: the upstream output string is injected as the value of
    the downstream block's first required parameter (unless already supplied).
    """
    required: list[str] = parameter_schema.get("required", [])
    merged = {**block_config}  # start with user-supplied config

    if upstream_output is not None and required:
        first_param = required[0]
        # Only inject if the user hasn't already supplied a value
        if first_param not in merged or merged[first_param] in ("", None):
            merged[first_param] = str(upstream_output)

    return merged


def _inputs_node_output(block_config: dict[str, Any]) -> dict[str, Any]:
    """Return the Inputs node's configured values as the first downstream payload."""
    return block_config


# ---------------------------------------------------------------------------
# Status event callback type
# ---------------------------------------------------------------------------

StatusCallback = Callable[[str, BlockStatus, str | None], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# DAG runner
# ---------------------------------------------------------------------------

class DAGRunner:
    """Executes a PipelineGraph by calling @tool functions directly in topological order.

    Fan-out branches run concurrently via asyncio.gather.
    Independent error branch isolation: a failed branch does not cancel siblings.

    For ``delegate_*`` agent blocks the optional ``agent_runner_map`` is used to call
    the underlying ``async run_*_agent()`` function directly (T033 / US4), bypassing the
    synchronous ``@tool`` wrapper so that any intermediate events can be captured.
    """

    def __init__(
        self,
        tool_map: dict[str, Any],
        status_callback: StatusCallback,
        skill_registry: Any = None,
        agent_runner_map: dict[str, Any] | None = None,
    ) -> None:
        self._tool_map = tool_map
        self._status_callback = status_callback
        self._skill_registry = skill_registry
        # Maps delegate_* skill_name → async callable(message: str, config) -> str
        self._agent_runner_map: dict[str, Any] = agent_runner_map or {}

    async def _emit(self, node_id: str, status: BlockStatus, message: str | None = None) -> None:
        try:
            await self._status_callback(node_id, status, message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Status callback error: %s", exc)

    async def _call_tool(
        self,
        block: BlockInstance,
        kwargs: dict[str, Any],
    ) -> str:
        skill_name = block.skill_name

        # T033 / US4: for agent blocks use the async runner directly (not the @tool wrapper)
        if skill_name.startswith("delegate_") and skill_name in self._agent_runner_map:
            runner_fn = self._agent_runner_map[skill_name]
            # All delegate tools accept a single `task` str; map kwargs → message
            task_val = kwargs.get("task") or next(iter(kwargs.values()), "") if kwargs else ""
            result = await runner_fn(str(task_val))
            return str(result) if result is not None else ""

        tool = self._tool_map.get(skill_name)
        if tool is None:
            raise RuntimeError(f"Tool '{skill_name}' not found in registry.")
        # All @tool functions are synchronous — run in thread to honour Constitution I
        result = await asyncio.to_thread(tool.func, **kwargs)
        return str(result) if result is not None else ""

    async def _run_node(
        self,
        block: BlockInstance,
        upstream_output: Any,
        node_outputs: dict[str, Any],
        errors: dict[str, str],
    ) -> None:
        """Execute a single block, update node_outputs / errors in place."""
        await self._emit(block.id, BlockStatus.RUNNING)

        # Special nodes
        if block.skill_name == "__inputs__":
            output = _inputs_node_output(block.config)
            node_outputs[block.id] = output
            await self._emit(block.id, BlockStatus.DONE)
            return

        if block.skill_name == "__outputs__":
            node_outputs[block.id] = upstream_output
            await self._emit(block.id, BlockStatus.DONE)
            return

        # Get parameter schema for binding
        schema: dict[str, Any] = {}
        if self._skill_registry:
            skill = self._skill_registry.get_skill(block.skill_name)
            if skill:
                schema = skill.parameter_schema

        kwargs = _bind_inputs(block.skill_name, upstream_output, block.config, schema)

        try:
            output = await self._call_tool(block, kwargs)
            node_outputs[block.id] = output
            await self._emit(block.id, BlockStatus.DONE)
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            errors[block.id] = error_msg
            node_outputs[block.id] = None
            await self._emit(block.id, BlockStatus.ERROR, error_msg)
            logger.error("Block '%s' failed: %s", block.skill_name, error_msg)

    async def run(self, pipeline: PipelineGraph, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the pipeline DAG.  Returns node_outputs keyed by node_id."""
        nodes = pipeline.nodes
        edges = pipeline.edges

        if not nodes:
            return {}

        # Validate: must have exactly one __inputs__ node
        inputs_nodes = [n for n in nodes if n.skill_name == "__inputs__"]
        if len(inputs_nodes) != 1:
            raise ValueError("Pipeline must contain exactly one Inputs node.")

        # Inject runtime inputs into the Inputs node's config
        inputs_node = inputs_nodes[0]
        merged_config = {**inputs_node.config, **inputs}
        # Create a copy with merged config
        inputs_node_copy = inputs_node.model_copy(update={"config": merged_config})
        node_map = {n.id: (inputs_node_copy if n.id == inputs_node.id else n) for n in nodes}

        topo = topological_sort(list(node_map.values()), edges)

        # Build successors map
        successors: dict[str, list[str]] = defaultdict(list)
        predecessors: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            successors[edge.source_node_id].append(edge.target_node_id)
            predecessors[edge.target_node_id].append(edge.source_node_id)

        node_outputs: dict[str, Any] = {}
        errors: dict[str, str] = {}

        # Emit pending for all nodes upfront
        for node in topo:
            await self._emit(node.id, BlockStatus.PENDING)

        # Execute in topological order — group concurrent fan-out levels
        # Build level sets: nodes at same level can run in parallel
        levels: list[list[BlockInstance]] = []
        scheduled: set[str] = set()
        remaining = list(topo)

        while remaining:
            level = [
                n for n in remaining
                if all(p in scheduled for p in predecessors[n.id])
            ]
            if not level:
                break
            levels.append(level)
            for n in level:
                scheduled.add(n.id)
            remaining = [n for n in remaining if n.id not in scheduled]

        for level in levels:
            tasks = []
            for block in level:
                # Determine upstream output (from direct predecessor, or None)
                preds = predecessors[block.id]
                if preds:
                    # If any predecessor errored, skip this block
                    failed_preds = [p for p in preds if p in errors]
                    if failed_preds:
                        skip_msg = f"Skipped: upstream block failed."
                        errors[block.id] = skip_msg
                        node_outputs[block.id] = None
                        await self._emit(block.id, BlockStatus.ERROR, skip_msg)
                        continue
                    # Use last predecessor's output as upstream value
                    upstream = node_outputs.get(preds[-1])
                else:
                    upstream = None

                tasks.append(
                    self._run_node(node_map[block.id], upstream, node_outputs, errors)
                )

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        return node_outputs
