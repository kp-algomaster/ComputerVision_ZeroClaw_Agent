# Implementation Plan: Live Playground

**Branch**: `003-live-playground` | **Date**: 2026-03-10 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/003-live-playground/spec.md`

## Summary

Add a **Live mode** toggle to the existing Playground panel that intercepts `tool_start` / `tool_end` events from the `/ws/chat` WebSocket and renders tool-call blocks on the existing Drawflow canvas in real time. Blocks are placed left-to-right with directed edges connecting sequential calls, and status colours update live (blue → running, green → done, red → error). The canvas clears at the start of each new user turn. This feature is **frontend-only** — no new backend endpoints or server-side protocol changes are required.

## Technical Context

**Language/Version**: ES6 Vanilla JS (frontend — matches existing `app.js`)
**Primary Dependencies**: Drawflow v0.0.59 (already loaded) — no new dependencies required
**Storage**: N/A — Live mode state is ephemeral (in-memory only, resets on page load)
**Testing**: Manual browser testing; no unit tests (pure frontend feature with no testable backend logic)
**Target Platform**: macOS / Linux local dev server (uvicorn on port 8420)
**Project Type**: Feature addition to existing web application frontend
**Performance Goals**: Block appears on canvas ≤ 1 second after WebSocket event; status colour update ≤ 200 ms after tool_end
**Constraints**: No server-side changes; no new Python code; no new dependencies; must coexist with the existing manual-pipeline Playground features (save/load/run/undo-redo)
**Scale/Scope**: Single-user local session; single `/ws/chat` connection; up to ~10 concurrent live blocks per turn

## Constitution Check

*No `constitution.md` file exists in this project. Applying the implicit principles established in the 002-cv-playground spec:*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Async-First** | ✅ PASS | All logic is event-driven via existing WebSocket `onmessage`; no blocking calls; no polling |
| **II. Tool-Centric Agent Design** | ✅ PASS | No changes to tool registry or agent logic; reads existing `tool_start` / `tool_end` events only |
| **III. Config-Driven, Secret-Safe** | ✅ PASS | No config changes; no secrets involved |
| **IV. Streaming-First UI** | ✅ PASS | Live blocks update in real time from streaming WebSocket events; no spinners/polling |

**Gate result: PASS** — all applicable principles satisfied.

## Project Structure

### Documentation (this feature)

```text
specs/003-live-playground/
├── spec.md              # Feature specification (complete)
├── plan.md              # This file
├── checklists/
│   └── requirements.md  # Spec quality checklist (all passed)
└── tasks.md             # Task list (to be created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/cv_agent/ui/
├── index.html           # MODIFY: Add Live toggle button HTML to Playground toolbar
├── style.css            # MODIFY: Add live-mode CSS classes and animations
└── app.js               # MODIFY: Add live-mode state, event interception, block rendering
```

**Structure Decision**: All changes are confined to the three existing UI files. No new files, packages, or backend code. The `_pg` state object in `app.js` is extended with live-mode fields (`_pg.liveMode`, `_pg.liveBlocks`, `_pg.liveQueue`, etc.).

## Technical Design

### 1. Live Toggle State (`_pg` Extension)

New fields added to the existing `_pg` object:

```javascript
_pg.liveMode    = false;       // FR-001: toggle state
_pg.liveBlocks  = {};          // call_id → drawflow_node_id mapping
_pg.liveQueue   = [];          // FR-011: events queued before canvas init
_pg.liveSeqId   = 0;           // counter for left-to-right placement
_pg.liveLastId  = null;        // previous block ID (for edge drawing)
_pg.livePending = new Set();   // call_ids currently running (for parallel detection)
```

### 2. Event Interception

The existing `connectWebSocket.onmessage` handler already processes `tool_start` and `tool_end` events. Live mode adds a call into new handler functions from the existing branches:

```javascript
// In the tool_start branch:
if (_pg.liveMode) _pgLiveToolStart(data.name, data.input);

// In the tool_end branch:
if (_pg.liveMode) _pgLiveToolEnd(data.name, data.output);
```

The backend already emits `tool_start` with `{name, input}` and `tool_end` with `{name, output}`. No `call_id` is currently emitted, so Live mode will use `tool_name` as the block identity key (sufficient for single-agent sequential calls). If two tools share the same name in one turn, a numeric suffix is appended.

### 3. Block Placement Algorithm

- Each `tool_start` event adds a Drawflow node at `x = 200 + (liveSeqId * 220)`, `y = 200`
- If the previous tool call was sequential (received after the prior `tool_end`), an edge is drawn from `liveLastId` to the new node
- If multiple `tool_start` events arrive before any `tool_end` (parallel fan-out), they are rendered as sibling blocks without edges between them (FR-013)
- CSS class `pg-status-running` (blue) is applied on creation
- On `tool_end`: class changes to `pg-status-done` (green) or `pg-status-error` (red)

### 4. Turn Boundary Canvas Clear

On `stream_start` event (beginning of a new agent turn), if `_pg.liveMode` is true, the canvas is cleared of all live blocks (FR-007). Manually placed blocks are preserved (they are tagged differently in `_pg.nodeConfigs`).

### 5. Non-Destructive Activation (US2)

If the canvas has manually placed blocks when Live mode is activated:
- A confirmation prompt is shown: "Canvas has existing blocks. Clear or keep?"
- "Clear": all blocks removed, live mode starts clean
- "Keep": existing blocks remain, live blocks are placed to the right of existing content

### 6. Toggle Persistence (US3)

`_pg.liveMode` persists across panel open/close cycles (it's already in the `_pg` object which survives panel toggles). Events received while the panel is closed are queued in `_pg.liveQueue` and replayed when the panel reopens.

## Complexity Tracking

> No complexity violations requiring justification.

## Verification Plan

### Manual Browser Testing

Since this is a pure frontend feature with no new backend code, verification is manual browser testing only.

**Test 1 — Basic Live DAG (US1, FR-001 through FR-007)**:
1. Start the dev server: `python -m cv_agent.web` (or however the server is started)
2. Open `http://localhost:8420` in the browser
3. Open the Playground panel (click the Playground nav item or press `Cmd+Shift+P`)
4. Click the **🔗 Live** toggle button in the Playground toolbar
5. Send a chat message that triggers multiple tool calls (e.g., asking about a paper or an image analysis)
6. **Verify**: Blocks appear on the canvas in left-to-right order; edges connect sequential calls; blocks show blue while running, green when done
7. Send another message
8. **Verify**: Canvas clears and new blocks appear for the new turn

**Test 2 — Non-Destructive Activation (US2, FR-008)**:
1. With Live mode OFF, manually drag 2 blocks onto the canvas
2. Click the **🔗 Live** toggle
3. **Verify**: A prompt appears asking to "Clear" or "Keep"
4. Choose "Keep", send a chat message
5. **Verify**: Original blocks remain; new live blocks appear to their right

**Test 3 — Toggle Persistence (US3, FR-009, FR-012)**:
1. Enable Live mode and trigger a tool call
2. Close the Playground panel
3. Trigger another tool call via chat
4. Re-open the Playground panel
5. **Verify**: Both blocks are visible on the canvas and the Live toggle is still active
6. Click the toggle again to disable Live mode
7. **Verify**: No new blocks appear for subsequent tool calls
