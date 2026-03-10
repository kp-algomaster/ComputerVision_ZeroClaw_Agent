"""Unit tests for the CV-Playground DAG runner."""
from __future__ import annotations

import asyncio
import pytest

from cv_agent.pipeline.dag_runner import DAGRunner, has_cycle, topological_sort
from cv_agent.pipeline.models import BlockInstance, BlockStatus, Edge, PipelineGraph, Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node(skill: str, nid: str = None) -> BlockInstance:
    return BlockInstance(
        id=nid or skill,
        skill_name=skill,
        category="Utility",
        position=Position(x=0, y=0),
    )


def _edge(src: str, tgt: str) -> Edge:
    return Edge(source_node_id=src, target_node_id=tgt)


def _pipeline(*nodes: BlockInstance, edges: list[Edge] = None) -> PipelineGraph:
    return PipelineGraph(name="test", nodes=list(nodes), edges=edges or [])


class _Events:
    def __init__(self):
        self.events: list[tuple[str, BlockStatus, str | None]] = []

    async def callback(self, node_id: str, status: BlockStatus, msg: str | None = None):
        self.events.append((node_id, status, msg))


def _make_runner(tools: dict, events: _Events) -> DAGRunner:
    return DAGRunner(tool_map=tools, status_callback=events.callback)


def _sync_tool(return_val: str):
    class _T:
        def __init__(self, val):
            self.val = val
            self.func = lambda **_: val
    return _T(return_val)


# ---------------------------------------------------------------------------
# Topological sort tests
# ---------------------------------------------------------------------------

def test_topo_sort_linear():
    a, b, c = _node("a"), _node("b"), _node("c")
    edges = [_edge("a", "b"), _edge("b", "c")]
    order = topological_sort([a, b, c], edges)
    assert [n.id for n in order] == ["a", "b", "c"]


def test_topo_sort_fan_out():
    a, b, c = _node("a"), _node("b"), _node("c")
    edges = [_edge("a", "b"), _edge("a", "c")]
    order = topological_sort([a, b, c], edges)
    # a must come first; b and c after
    ids = [n.id for n in order]
    assert ids[0] == "a"
    assert set(ids[1:]) == {"b", "c"}


def test_cycle_detection():
    a, b = _node("a"), _node("b")
    edges = [_edge("a", "b"), _edge("b", "a")]
    assert has_cycle([a, b], edges)


def test_no_cycle():
    a, b = _node("a"), _node("b")
    edges = [_edge("a", "b")]
    assert not has_cycle([a, b], edges)


def test_topo_sort_raises_on_cycle():
    a, b = _node("a"), _node("b")
    edges = [_edge("a", "b"), _edge("b", "a")]
    with pytest.raises(ValueError, match="cycle"):
        topological_sort([a, b], edges)


# ---------------------------------------------------------------------------
# DAG runner — linear pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_linear_pipeline():
    inp = _node("__inputs__", "inp")
    inp.config = {"text": "hello"}
    mid = _node("echo", "mid")
    out = _node("__outputs__", "out")
    edges = [_edge("inp", "mid"), _edge("mid", "out")]
    pipeline = _pipeline(inp, mid, out, edges=edges)

    tools = {"echo": _sync_tool("ECHO_RESULT")}
    events = _Events()
    runner = _make_runner(tools, events)
    result = await runner.run(pipeline, inputs={})

    assert result["mid"] == "ECHO_RESULT"
    assert result["out"] == "ECHO_RESULT"

    statuses = [(nid, st) for nid, st, _ in events.events if st in (BlockStatus.DONE, BlockStatus.ERROR)]
    assert ("mid", BlockStatus.DONE) in statuses
    assert ("out", BlockStatus.DONE) in statuses


# ---------------------------------------------------------------------------
# DAG runner — fan-out (two branches from one node)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fan_out():
    inp = _node("__inputs__", "inp")
    inp.config = {"text": "start"}
    branch_a = _node("tool_a", "a")
    branch_b = _node("tool_b", "b")
    out = _node("__outputs__", "out")
    edges = [_edge("inp", "a"), _edge("inp", "b"), _edge("a", "out")]
    pipeline = _pipeline(inp, branch_a, branch_b, out, edges=edges)

    call_order: list[str] = []

    class _TrackedTool:
        def __init__(self, name, ret):
            self.name = name
            self.ret = ret
            def _f(**_): call_order.append(name); return ret
            self.func = _f

    tools = {"tool_a": _TrackedTool("a", "A"), "tool_b": _TrackedTool("b", "B")}
    events = _Events()
    runner = _make_runner(tools, events)
    result = await runner.run(pipeline, inputs={})

    # Both branches ran
    assert result["a"] == "A"
    assert result["b"] == "B"
    assert "a" in call_order and "b" in call_order


# ---------------------------------------------------------------------------
# DAG runner — error isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_isolation():
    """Errored branch halts at failure; sibling branch continues."""
    inp = _node("__inputs__", "inp")
    inp.config = {}
    fail_node = _node("fail_tool", "fail")
    ok_node = _node("ok_tool", "ok")
    out_a = _node("__outputs__", "out_a")
    out_b = _node("__outputs__", "out_b")
    edges = [
        _edge("inp", "fail"), _edge("inp", "ok"),
        _edge("fail", "out_a"), _edge("ok", "out_b"),
    ]
    pipeline = _pipeline(inp, fail_node, ok_node, out_a, out_b, edges=edges)

    def _failing(**_): raise RuntimeError("tool unavailable")

    class _FakeTool:
        func = staticmethod(_failing)
    class _OkTool:
        func = staticmethod(lambda **_: "OK")

    tools = {"fail_tool": _FakeTool(), "ok_tool": _OkTool()}
    events = _Events()
    runner = _make_runner(tools, events)
    result = await runner.run(pipeline, inputs={})

    # ok branch completed
    assert result["ok"] == "OK"
    assert result["out_b"] == "OK"
    # fail branch errored + downstream skipped
    assert result["fail"] is None
    error_statuses = {nid: st for nid, st, _ in events.events if st == BlockStatus.ERROR}
    assert "fail" in error_statuses
    assert "out_a" in error_statuses  # skipped


# ---------------------------------------------------------------------------
# DAG runner — missing Inputs node rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_inputs_node_rejected():
    mid = _node("tool_a", "mid")
    out = _node("__outputs__", "out")
    pipeline = _pipeline(mid, out, edges=[_edge("mid", "out")])
    events = _Events()
    runner = _make_runner({"tool_a": _sync_tool("x")}, events)
    with pytest.raises(ValueError, match="Inputs"):
        await runner.run(pipeline, inputs={})


# ---------------------------------------------------------------------------
# Cycle detection at run time
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cycle_in_pipeline_raises():
    a = _node("__inputs__", "a")
    b = _node("tool_b", "b")
    edges = [_edge("a", "b"), _edge("b", "a")]
    pipeline = _pipeline(a, b, edges=edges)
    events = _Events()
    runner = _make_runner({"tool_b": _sync_tool("x")}, events)
    with pytest.raises(ValueError, match="cycle"):
        await runner.run(pipeline, inputs={})
