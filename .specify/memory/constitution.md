<!--
SYNC IMPACT REPORT
==================
Version change: (none) → 1.0.0 (initial ratification)

Modified principles: N/A (initial)

Added sections:
  - Core Principles (I–V)
  - Technology Standards
  - Development Standards
  - Governance

Removed sections: N/A

Templates requiring updates:
  - .specify/templates/plan-template.md  ✅ Constitution Check gate aligned to these principles
  - .specify/templates/spec-template.md  ✅ No changes required; requirements format compatible
  - .specify/templates/tasks-template.md ✅ No changes required; task format compatible

Follow-up TODOs:
  - None; all fields resolved from repo context (CLAUDE.md, README.md, web.py)
-->

# CV Zero Claw Agent Constitution

## Core Principles

### I. Async-First Architecture

All I/O-bound operations MUST use `async/await`. Blocking calls inside an async
context are forbidden. CPU-bound or legacy synchronous code MUST be offloaded via
`asyncio.to_thread()`. Long-running backend operations (model downloads, dataset
fetches, fine-tuning runs, server health checks) MUST stream incremental progress
to the frontend via SSE (`text/event-stream`); polling is not an acceptable
substitute.

**Rationale**: The web server handles concurrent WebSocket sessions, SSE streams,
and agent tool calls simultaneously. A single blocking call stalls all of them.

### II. Tool-Centric Agent Design

Every agent capability MUST be implemented as a `@tool`-decorated function and
registered explicitly in `agent.py:build_tools()`. Implementations live in
`src/cv_agent/tools/`. No capability logic belongs in `agent.py` itself.
Auto-discovery of tools is forbidden — registration MUST be explicit.

**Rationale**: Explicit registration makes the agent's capability surface auditable
and testable. Implicit discovery hides what the agent can do.

### III. Config-Driven, Secret-Safe

Configuration MUST be loaded via `load_config()`. Secrets MUST live exclusively
in `.env` (gitignored). Paths and API keys MUST NOT be hardcoded in source.
Powers (external integrations) are configured through the UI and written to `.env`
at runtime. `.env` MUST NEVER be committed.

**Rationale**: Hardcoded values break portability and create accidental secret
leakage. A single configuration source prevents config drift between environments.

### IV. Streaming-First UI Contracts

Downloads (models, datasets) MUST use a `.complete` sentinel file to track
completion, enabling reliable resume after interruption. Stale `.lock` files
from interrupted HuggingFace downloads MUST be cleaned up before retrying.
The UI MUST surface live progress (percentage, speed, file name) for all
long-running operations; no blocking spinners with no feedback.

**Rationale**: Large model and dataset downloads (4–16 GB) fail frequently on
consumer hardware. Reliable resume and live feedback are non-negotiable for
usability.

### V. Spec-Driven Research Output

Every processed paper MUST produce a `spec.md` artifact stored in `vault/`.
The research pipeline flows: Paper → Extract (equations, architecture, datasets,
metrics) → Spec → Knowledge Graph → Digest. Research without a documented
artifact is a pipeline failure. Weekly digests MUST synthesize the knowledge
graph, not repeat raw paper content.

**Rationale**: The agent's value is accumulated structured knowledge, not
ephemeral chat history. Specs and the knowledge graph are the persistent outputs.

## Technology Standards

- **Language**: Python 3.12+ exclusively; no support for older versions
- **Config/Validation**: Pydantic V2; no raw dict passing across module boundaries
- **Linting**: ruff, line-length 100; CI MUST pass before merge
- **Web layer**: FastAPI; LangGraph ReAct for agent orchestration
- **Agent tooling**: ZeroClaw shim at `src/zeroclaw_tools/`; replace with
  `pip install zeroclaw-tools` and delete the shim when the PyPI package ships
- **LLM inference**: Ollama (`localhost:11434`); MLX for Apple Silicon acceleration
- **Model/dataset downloads**: HuggingFace Hub `snapshot_download` with
  `local_dir_use_symlinks=False`; stale lock cleanup before every download
- **Local model storage**: `output/.models/<model-id>/`
- **Local dataset storage**: `output/.datasets/<dataset-id>/`

## Development Standards

- **Commits**: Present tense imperative subject line ("add", "fix", "update");
  one-line subject + optional bullet body. NEVER add `Co-Authored-By` trailers
  or any AI attribution.
- **Staging**: Stage specific files by name. `git add -A` and `git add .` are
  forbidden.
- **Docstrings**: Only where logic is non-obvious. Trivial functions MUST NOT
  have docstrings.
- **Validation**: Validate only at system boundaries (user input, external APIs).
  Trust internal code and framework guarantees.
- **Complexity**: Minimum complexity for the current task. No speculative
  abstractions, no backwards-compatibility shims for unused code.
- **Error handling**: Add only for failure modes that can actually occur.
  Do not add fallbacks for scenarios that cannot happen.

## Governance

This constitution supersedes all prior ad-hoc conventions. When a coding
decision conflicts with this document, this document wins.

**Amendment procedure**:
1. Update `.specify/memory/constitution.md` with the change and bump the version.
2. Propagate the change to `.specify/templates/` files if they reference the
   amended principle.
3. Commit with message: `docs: amend constitution to vX.Y.Z (<summary>)`
4. Record the amendment in the Sync Impact Report comment at the top of this file.

**Versioning policy**:
- MAJOR: Principle removals or redefinitions that break prior guidance.
- MINOR: New principle or section added, or material expansion of existing guidance.
- PATCH: Clarifications, wording fixes, typo corrections, non-semantic refinements.

**Compliance**:
- All feature plans MUST include a Constitution Check gate (Phase 0 research
  blocked until check passes).
- Pre-commit: ruff MUST pass (line-length 100).
- `HF_TOKEN` required in `.env` for gated model downloads (SAM 3, DeepGen 1.0).
- No `.env` file in git history — verify with `git log --all -- .env` before push.

**Version**: 1.0.0 | **Ratified**: 2026-03-05 | **Last Amended**: 2026-03-05
