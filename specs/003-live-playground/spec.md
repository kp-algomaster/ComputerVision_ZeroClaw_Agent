# Feature Specification: Live Playground

**Feature Branch**: `003-live-playground`
**Created**: 2026-03-10
**Status**: Draft

## Clarifications

### Session 2026-03-10

- Q: Does `/ws/chat` currently emit `type="tool_call"` / `type="tool_result"` events, or does the server need updating? → A: `/ws/chat` already emits these events — this feature is frontend-only; no server-side protocol changes are required.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Live toggle activates real-time DAG visualisation (Priority: P1)

A user is chatting with the CV Assistant and wants to understand what tools the agent is using under the hood. They click the **🔗 Live** button in the chat toolbar. The Playground panel opens beside the chat and, as the agent calls tools, a block appears on the canvas for each tool with a directed edge connecting sequential calls. Status colours update in real time (blue while running, green when done, red on error). The user gains an immediate visual map of the agent's decision chain without leaving the chat.

**Why this priority**: Core value proposition — real-time transparency. Without this story there is nothing to test. All other stories extend this.

**Independent Test**: Open a chat session, enable Live mode, send a message that triggers two or more tool calls. Verify blocks appear on the canvas in call order with edges connecting them, and that status colours update correctly without any manual action.

**Acceptance Scenarios**:

1. **Given** Live mode is off, **When** the user clicks 🔗 Live, **Then** the toggle activates, the Playground panel opens (if closed), and subsequent tool calls begin populating the canvas.
2. **Given** Live mode is on and the agent calls tool A then tool B in sequence, **When** both tool results are received, **Then** canvas shows block A → edge → block B, both green.
3. **Given** Live mode is on and a tool call fails, **When** the tool result arrives with an error, **Then** the corresponding block turns red and displays the error label.
4. **Given** Live mode is on, **When** the user sends a new chat message, **Then** the canvas clears and starts fresh for the new turn's tool calls.

---

### User Story 2 — Non-destructive activation (Priority: P2)

A user has manually assembled a pipeline on the Playground canvas. They then want to enable Live mode. The system detects that the canvas is not empty and presents a choice: clear the existing pipeline and start Live mode, or append incoming live blocks to the existing canvas.

**Why this priority**: Protects work the user has invested in a manual pipeline. Without this safeguard, enabling Live mode could silently destroy the user's pipeline.

**Independent Test**: Build a two-block manual pipeline. Enable Live mode. Verify the confirmation prompt appears and that choosing "keep" preserves the existing blocks while subsequent live tool calls append new blocks; choosing "clear" wipes the canvas before Live mode starts.

**Acceptance Scenarios**:

1. **Given** the canvas has manually placed blocks, **When** the user enables Live mode, **Then** a prompt asks to clear or append with two distinct options.
2. **Given** the user selects "Clear", **When** confirmed, **Then** the canvas is cleared and Live mode starts cleanly.
3. **Given** the user selects "Append", **When** confirmed, **Then** existing blocks remain and new live blocks are placed to the right of existing content.
4. **Given** the canvas is empty, **When** the user enables Live mode, **Then** no prompt appears and Live mode starts immediately.

---

### User Story 3 — Toggle persistence and panel sync (Priority: P3)

A user enables Live mode and then closes the Playground panel to reclaim screen space. The Live toggle remains visually active in the chat toolbar. When the panel is reopened, all blocks collected since Live mode was enabled are still visible on the canvas. The Live toggle state survives open/close cycles within the same browser session.

**Why this priority**: Quality-of-life; users should not have to re-enable Live mode every time they toggle the panel.

**Independent Test**: Enable Live mode, trigger a tool call, close the panel, trigger another tool call, reopen the panel. Verify both tool-call blocks are present and the toggle is still active.

**Acceptance Scenarios**:

1. **Given** Live mode is on, **When** the Playground panel is closed, **Then** the 🔗 Live button in the chat toolbar remains visually active (highlighted).
2. **Given** Live mode is on and the panel is closed, **When** a tool call occurs, **Then** the block is queued and rendered when the panel is next opened.
3. **Given** Live mode is on, **When** the panel is reopened, **Then** all blocks from the current session are visible and the canvas state is intact.
4. **Given** Live mode is on, **When** the user clicks the toggle again, **Then** Live mode turns off and no new blocks are added for subsequent tool calls.

---

### Edge Cases

- What happens when the agent calls ten or more tools in a single turn — do blocks overflow the visible canvas? Auto-scroll or zoom-to-fit must prevent clipping.
- What if a tool name from the agent does not match any skill registered in the Playground? An "Unknown Tool" placeholder block must be shown rather than silently skipping the event.
- What if the Playground canvas is not yet initialised when the first tool-call event arrives? Events must be queued and replayed once the canvas becomes ready.
- What if the user enables Live mode mid-turn while the agent is already calling tools? Only events received after activation are rendered; earlier ones are skipped.
- What if two tool calls arrive simultaneously as parallel agent steps? Both blocks are rendered without an edge between them — edges only connect sequentially ordered calls.
- What if the user disables Live mode and re-enables it within the same turn? Canvas is cleared and only events after re-activation are rendered.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The chat toolbar MUST include a persistently visible "🔗 Live" toggle button that switches Live Playground mode on or off.
- **FR-002**: Activating the toggle MUST open the Playground panel if it is currently closed.
- **FR-003**: When Live mode is active and the agent begins a tool call, the system MUST add a visual block for that tool to the canvas within one second of the event being received.
- **FR-004**: Blocks MUST be placed in left-to-right order reflecting call sequence, with automatic spacing so blocks do not overlap.
- **FR-005**: When sequential tool calls occur within the same agent step, the system MUST draw a directed edge from the first block to the second block.
- **FR-006**: When a tool result is received, the system MUST update the block's status — green for success, red for failure — without any user action.
- **FR-007**: At the start of each new user message (new turn), the system MUST clear the canvas before rendering blocks for the new turn's tool calls.
- **FR-008**: If the canvas contains manually placed blocks when Live mode is activated, the system MUST present a choice — clear the canvas or append — before proceeding.
- **FR-009**: The Live toggle state MUST persist within the same browser session across Playground panel open/close cycles.
- **FR-010**: If a tool name has no matching registered skill block, the system MUST render an "Unknown Tool" placeholder block.
- **FR-011**: If the Playground canvas is not yet initialised when a tool-call event arrives, the system MUST queue the event and replay it once the canvas is ready.
- **FR-012**: Disabling Live mode MUST NOT close the Playground panel.
- **FR-013**: Parallel tool calls (no sequential dependency) MUST be rendered as sibling blocks without an edge between them.

### Key Entities

- **Live Turn**: The set of tool-call blocks and edges generated for a single user message; cleared at the start of each new turn.
- **Tool-Call Event**: A signal from the agent identifying which tool is being invoked, carrying a tool name and unique call identifier.
- **Tool-Result Event**: A follow-up signal confirming the outcome (success or failure) of a specific tool call, linked by call identifier.
- **Live Block**: A canvas node created automatically by a tool-call event; shares the same visual and status vocabulary as manually placed blocks.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A tool-call block appears on the canvas within 1 second of the corresponding event being received by the browser.
- **SC-002**: 100% of tool calls in a single agent turn are represented as blocks with no silent drops when Live mode is active.
- **SC-003**: Status colours update correctly (green / red) for every tool-result received, with zero manual interaction required.
- **SC-004**: Enabling Live mode on a non-empty canvas triggers the confirmation prompt 100% of the time — no silent data loss occurs.
- **SC-005**: The Live toggle state survives at least 10 consecutive Playground panel open/close cycles within a session.
- **SC-006**: An "Unknown Tool" placeholder block is rendered for every unrecognised tool name — no events are silently dropped.

## Assumptions

- The existing `/ws/chat` WebSocket stream already emits structured events with `type`, `tool_name`, and `call_id` fields for tool calls and tool results; no server-side protocol changes are required.
- Tool names emitted by the agent exactly match the skill names registered in the Playground block library.
- Sequential tool calls within the same agent step are identified by call order within the same WebSocket message batch or a temporal window under 500 ms.
- Parallel tool calls (fan-out) arrive in the same batch without an implied order — no edge is drawn between them.
- This feature applies to the main chat session only; per-agent sub-chats are out of scope for this iteration.
- Live mode does not persist across browser page reloads; it resets to off on each page load.
