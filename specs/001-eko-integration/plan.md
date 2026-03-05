# Implementation Plan: Eko Agentic Workflow Integration

**Branch**: `001-eko-integration` | **Date**: 2026-03-05 | **Spec**: [specs/001-eko-integration/spec.md](file:///Users/tyretitans/CV_Robotiscs_Lab/CV_Zero_Claw_Agent/specs/001-eko-integration/spec.md)
**Input**: Feature specification from `/specs/001-eko-integration/spec.md`

## Summary

Integrate the Eko orchestration engine (Node.js sidecar) to enable multi-step, autonomous agentic workflows with human-in-the-loop checkpoints. Add a `BrowserAgent` utilizing Playwright for headless web automation and integrate workflows deeply into the existing UI (Workflows tab) and backend (FastAPI communication with Eko).

## Technical Context

**Language/Version**: Python 3.11+ (Backend), Node.js 18+ (Eko Sidecar), JavaScript (Frontend)
**Primary Dependencies**: FastAPI, Eko (github.com/FellouAI/eko), Playwright Chromium (BrowserAgent)
**Storage**: File-based JSON in `output/.workflows/`
**Testing**: Unit tests for workflow state parsing, integration tests for Python-to-Node.js Eko communication
**Target Platform**: Local runtime (macOS/Linux/Windows)
**Project Type**: Agentic Web Interface + Python Backend + Node.js Sidecar
**Performance Goals**: Sub-5s workflow planning, sub-2s UI synchronization
**Constraints**: Requires local Playwright Chromium installation. Local fallback via Ollama for zero-config ML endpoints.
**Scale/Scope**: Local single-user agent system.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle II (Tool-Centric Design)**: Eko orchestrates existing Python CV tools.
- **Principle IV (Streaming-First)**: Workflow execution state and BrowserAgent screenshots stream real-time to the UI.
- Human-in-the-loop validation checkpoints guarantee user oversight over automated workflows.

## Project Structure

### Documentation (this feature)

```text
specs/001-eko-integration/
├── plan.md              # This file
└── spec.md              # Feature specification
```

### Source Code (repository root)

```text
src/
├── cv_agent/
│   ├── server_manager.py           # [MODIFY] Register Eko sidecar on port 7862
│   ├── config.py                   # [MODIFY] Add Eko / Workflow config structures
│   ├── core/
│   │   └── workflow_manager.py     # [NEW] Client to interact with local Eko HTTP API
│   ├── web.py                      # [MODIFY] Add workflow routes + explicitly proxy Eko SSE streams (Constitution Principle I)
│   └── ui/
│       ├── app.js                  # [MODIFY] Add Workflows view, proxy SSE consumer, and update Models Server Management UI (resolves FR-008)
│       ├── index.html              # [MODIFY] Add Workflows tab container and checkpoint UI
│       └── style.css               # [MODIFY] Styles for workflow steps and thumbnails
eko_sidecar/                        # [NEW] Node.js project for Eko orchestration
├── package.json                    # Eko and Playwright dependencies
├── index.js                        # Express server wrapping Eko execution
└── browser_agent.js                # Playwright headless automation logic
```

**Structure Decision**: A new top-level `eko_sidecar/` directory will contain the Node.js application wrapping Eko. The existing Python `cv_agent` will communicate with it via HTTP and manage its lifecycle via `cv_agent/server_manager.py`. The sidecar will invoke existing Python tools by making HTTP requests back to the FastAPI `/tools` endpoints rather than reimplementing them in Node.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Multi-language runtime (Python + Node.js) | Eko is a Node.js library | Porting Eko to Python is too large a scope. Running Eko as a sidecar is the simplest path. |

## Verification Plan

### Automated Tests
- Create Python unit tests for `workflow_manager.py` mocking the HTTP calls to Eko.
- Verify configuration parsing behavior in `config.py`.

### Manual Verification
- Start the application and verify that `eko_sidecar` node process launches via `server_manager.py`.
- Open UI and test saving, loading, and running a dummy workflow.
- Execute a BrowserAgent step requiring navigation and confirm screenshot generation in `output/.workflows/`.
