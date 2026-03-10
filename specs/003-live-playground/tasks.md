# Tasks: Live Playground

**Input**: Design documents from `/specs/003-live-playground/`
**Prerequisites**: plan.md ✅ spec.md ✅

**Tests**: No automated tests — this is a pure frontend feature with no new backend code. Verification is manual browser testing per plan.md Verification Plan.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on in-progress tasks)
- **[Story]**: Which user story this task belongs to (US1–US3)

---

## Phase 1: Setup

**Purpose**: Extend `_pg` state and add Live toggle HTML to the Playground toolbar.

- [ ] T001 Add live-mode state fields to `_pg` object in `src/cv_agent/ui/app.js`: `liveMode` (boolean), `liveBlocks` (map), `liveQueue` (array), `liveSeqId` (int), `liveLastId` (int|null), `livePending` (Set), `liveSource` (string: 'manual'|'live' tag on each node)
- [ ] T002 [P] Add **🔗 Live** toggle button HTML to Playground toolbar in `src/cv_agent/ui/index.html`: button `id="pgLiveToggle"` in the Playground toolbar row, alongside Save/Load/Run; styled with existing toolbar button classes
- [ ] T003 [P] Add live-mode CSS to `src/cv_agent/ui/style.css`: `.pg-live-active` (toggle highlight), `.pg-live-block` (distinct visual for auto-placed blocks), `.pg-status-running` (blue pulsing border), `.pg-live-block.pg-status-done` (green), `.pg-live-block.pg-status-error` (red); `@keyframes pg-pulse` animation for running state

---

## Phase 2: User Story 1 — Live Toggle Activates Real-Time DAG Visualisation (Priority: P1) 🎯 MVP

**Goal**: User can click 🔗 Live, and as the agent calls tools, blocks appear on the canvas with edges and live status colours.

**Independent Test**: Open Playground → click 🔗 Live → send a chat message that triggers two or more tool calls → verify blocks appear on canvas in order with edges and correct status colours → send another message → verify canvas clears and new blocks appear.

### Implementation

- [ ] T004 [US1] Implement `pgToggleLive()` in `src/cv_agent/ui/app.js`: toggles `_pg.liveMode`; updates `#pgLiveToggle` visual state (add/remove `pg-live-active` class); if activating and panel is closed, calls `togglePlayground()` (FR-002); FR-001
- [ ] T005 [US1] Implement `_pgLiveToolStart(name, input)` in `src/cv_agent/ui/app.js`: creates a Drawflow node at position `x = 200 + (liveSeqId * 220), y = 200`; applies `pg-live-block pg-status-running` CSS classes; node inner HTML shows tool name and spinning indicator; stores mapping in `_pg.liveBlocks[name + '_' + seqId]`; if `_pg.livePending` is empty (no parallel fan-out) and `_pg.liveLastId` exists, draws edge from last block; pushes name to `_pg.livePending`; increments `_pg.liveSeqId`; FR-003, FR-004, FR-005, FR-013
- [ ] T006 [US1] Implement `_pgLiveToolEnd(name, output)` in `src/cv_agent/ui/app.js`: finds the matching live block by name; updates CSS class to `pg-status-done` (green) or `pg-status-error` (red) if output contains "error"/"Error"; removes from `_pg.livePending`; when `_pg.livePending` becomes empty, updates `_pg.liveLastId` to this block (for next sequential edge); FR-006
- [ ] T007 [US1] Implement unknown-tool placeholder in `_pgLiveToolStart()`: if `tool_name` does not match any skill in `_pg.skills`, render an "Unknown Tool" placeholder block with a grey question-mark icon and the raw tool name; FR-010
- [ ] T008 [US1] Hook live-mode calls into existing `connectWebSocket.onmessage` in `src/cv_agent/ui/app.js`: in the `tool_start` branch add `if (_pg.liveMode) _pgLiveToolStart(data.name, data.input)`; in the `tool_end` branch add `if (_pg.liveMode) _pgLiveToolEnd(data.name, data.output)`
- [ ] T009 [US1] Implement turn-boundary canvas clear in `src/cv_agent/ui/app.js`: on `stream_start` event, if `_pg.liveMode` is true, remove all Drawflow nodes tagged as `liveSource: 'live'` in `_pg.nodeConfigs`; reset `_pg.liveBlocks`, `_pg.liveSeqId`, `_pg.liveLastId`, `_pg.livePending`; FR-007
- [ ] T010 [US1] Implement auto-scroll / zoom-to-fit in `src/cv_agent/ui/app.js`: after adding a live block, if the block x-position exceeds the visible canvas width, call Drawflow's built-in `zoom_out()` or translate the canvas to keep the new block visible (edge case: 10+ tool calls in a single turn)

**Checkpoint**: US1 fully functional — toggle Live, send chat, see live DAG with status colours. MVP demonstrable.

---

## Phase 3: User Story 2 — Non-Destructive Activation (Priority: P2)

**Goal**: If the user has manually placed blocks on the canvas, enabling Live mode presents a choice to clear or keep them.

**Independent Test**: Build a two-block manual pipeline → enable Live mode → verify prompt appears → choose "Keep" → send chat → verify manual blocks remain and live blocks appear to their right; repeat choosing "Clear" → verify canvas is empty before live blocks appear.

### Implementation

- [ ] T011 [US2] Add non-empty canvas detection to `pgToggleLive()` in `src/cv_agent/ui/app.js`: on activation, check if Drawflow has any manually placed nodes (nodes where `_pg.nodeConfigs[id].liveSource !== 'live'`); if yes, show a confirmation dialog (FR-008)
- [ ] T012 [US2] Implement confirmation prompt in `src/cv_agent/ui/app.js`: inline overlay or `confirm()` dialog with two options: "Clear Canvas" (removes all blocks, starts clean) and "Keep & Append" (preserves existing blocks); if "Keep & Append", set `_pg.liveSeqId` so new blocks are placed to the right of the rightmost existing block (FR-008 acceptance scenarios 1–4)
- [ ] T013 [P] [US2] Add empty-canvas shortcut: if canvas has zero nodes when Live is toggled on, skip the prompt and activate immediately (acceptance scenario 4)

**Checkpoint**: US1 + US2 both functional — Live mode respects existing manual pipeline work.

---

## Phase 4: User Story 3 — Toggle Persistence and Panel Sync (Priority: P3)

**Goal**: Live toggle state survives Playground panel open/close cycles. Events received while the panel is closed are queued and rendered when the panel reopens.

**Independent Test**: Enable Live → trigger tool call → close panel → trigger another tool call → reopen panel → verify both blocks visible and toggle still active → click toggle again → verify Live mode off.

### Implementation

- [ ] T014 [US3] Persist Live toggle visual across panel cycles in `src/cv_agent/ui/app.js`: in `togglePlayground()`, when re-opening the panel, check `_pg.liveMode` and set `pg-live-active` class on `#pgLiveToggle` accordingly; FR-009 acceptance scenario 1
- [ ] T015 [US3] Implement event queueing in `_pgLiveToolStart()` / `_pgLiveToolEnd()` in `src/cv_agent/ui/app.js`: if `_pg.df` is null (Drawflow not initialised because panel is closed), push events to `_pg.liveQueue`; FR-011
- [ ] T016 [US3] Implement queue replay in `togglePlayground()` in `src/cv_agent/ui/app.js`: after Drawflow init, if `_pg.liveQueue` is non-empty, replay all queued events in order; FR-011 acceptance scenario 3
- [ ] T017 [US3] Implement Live-off behaviour in `src/cv_agent/ui/app.js`: clicking the toggle when Live is ON turns it off; subsequent tool calls are NOT rendered as blocks; existing live blocks remain on canvas until next turn or manual deletion; FR-012

**Checkpoint**: All three user stories functional — complete Live Playground feature.

---

## Phase 5: Polish & Edge Cases

**Purpose**: Handle edge cases identified in the spec.

- [ ] T018 [P] Handle mid-turn activation: if user enables Live mode while the agent is already calling tools, only events received AFTER activation are rendered; earlier events are skipped (edge case from spec)
- [ ] T019 [P] Handle re-enable within same turn: if user disables Live mode and re-enables within the same turn, canvas is cleared and only events after re-activation are rendered (edge case from spec)
- [ ] T020 [P] Handle parallel tool calls: when two `tool_start` events arrive before any `tool_end` (parallel agent steps), render both blocks at the same y-position without an edge between them; only draw edges for sequential calls (FR-013)
- [ ] T021 Run all manual verification tests from plan.md Verification Plan (Test 1, Test 2, Test 3)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (US1)**: Depends on Phase 1 — primary MVP deliverable
- **Phase 3 (US2)**: Depends on Phase 1 — can start alongside US1 after T001/T002/T003
- **Phase 4 (US3)**: Depends on T004 (live toggle function) — start after US1 checkpoint
- **Phase 5 (Polish)**: Depends on US1 at minimum; can start after US1 checkpoint

### User Story Dependencies

- **US1 (P1)**: Starts after Phase 1 — no dependency on other stories
- **US2 (P2)**: Starts after Phase 1 — logically depends on T004's `pgToggleLive()` function
- **US3 (P3)**: Extends T004 toggle and T005/T006 event handlers — start after US1

### Parallel Opportunities

- T002, T003 (HTML + CSS) → parallel with each other and with T001
- T013 (empty canvas shortcut) → parallel with T011/T012
- T018, T019, T020 (edge case handlers) → all parallel in Phase 5

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: US1 (T004–T010)
3. **STOP and VALIDATE**: Enable Live mode, send a multi-tool chat message, verify live blocks + edges + status colours
4. Demo/validate with user — core feature value delivered

### Incremental Delivery

1. Setup → state and HTML ready
2. US1 → live DAG rendering from tool events (MVP!)
3. US2 → non-destructive activation prompt
4. US3 → toggle persistence across panel cycles
5. Polish → edge case handling

---

## Summary

| Phase | Tasks | Story | Parallelisable |
|-------|-------|-------|----------------|
| 1 Setup | T001–T003 | — | T002, T003 |
| 2 US1 (P1 MVP) | T004–T010 | US1 | — |
| 3 US2 (P2) | T011–T013 | US2 | T013 |
| 4 US3 (P3) | T014–T017 | US3 | — |
| 5 Polish | T018–T021 | — | T018, T019, T020 |
| **Total** | **21 tasks** | | |

**Suggested MVP scope**: Phase 1 + Phase 2 (US1) — 10 tasks to a fully working live DAG visualisation.

---

## Notes

- All changes are confined to three existing files: `index.html`, `style.css`, `app.js`
- No server-side changes — `/ws/chat` already emits `tool_start` and `tool_end` events
- `_pg.liveMode` is ephemeral — does not persist across page reloads (per spec assumptions)
- Live blocks are distinguished from manual blocks by `_pg.nodeConfigs[id].liveSource === 'live'`
- The existing undo/redo stack (`_pg.undoStack`) should be suppressed during live mode to avoid polluting the stack with auto-generated blocks
