# Feature Specification: CV-Playground

**Feature Branch**: `002-cv-playground`
**Created**: 2026-03-10
**Status**: Draft
**Input**: Collapsible right-sidebar panel with graphical block-based workflow builder (Roboflow/n8n-style node graph) that opens alongside the live chat in the existing web UI.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Assemble and Run a Vision Pipeline (Priority: P1)

A researcher wants to process an uploaded image through a chain of CV skills — first OCR to extract text, then vision analysis to describe it — without writing any code or crafting a complex prompt. They open the Playground sidebar, drag an **OCR** block and a **Vision Analysis** block onto the canvas, wire them together, attach an **Inputs** node (image) and an **Outputs** node, then press **Run**. Results appear in the chat window and in the Outputs block in real time.

**Why this priority**: This is the core value proposition. A working linear pipeline with two blocks and visible streaming results proves the entire feature end-to-end and delivers immediate, tangible value to any user.

**Independent Test**: Can be fully tested by opening the Playground, building a two-block pipeline (Inputs → OCR → Outputs), uploading an image, running it, and verifying that OCR text appears in the output — without needing save/load, block configuration, or agent delegation.

**Acceptance Scenarios**:

1. **Given** the chat UI is open and the Playground sidebar is closed, **When** the user clicks the Playground toggle button, **Then** the right sidebar opens without shifting or hiding the chat panel.
2. **Given** the Playground sidebar is open, **When** the user drags the OCR block from the skill panel onto the canvas, **Then** a connected block node appears on the canvas with an output port.
3. **Given** two blocks are on the canvas (Inputs → OCR → Outputs) with edges drawn, **When** the user clicks Run, **Then** each block node cycles through pending → running → done states with a colour indicator, and the output text streams into the chat.
4. **Given** a pipeline run is in progress, **When** a block errors, **Then** that block's node turns red, a short error message appears on the node, and subsequent dependent blocks are skipped.

---

### User Story 2 — Configure a Block's Parameters Inline (Priority: P2)

A researcher wants to control the prompt sent to the Vision Analysis block (e.g., "focus on object boundaries") and set the language for OCR to French. They click a block on the canvas to open an inline configuration panel showing that block's specific parameters, edit the values, and close the panel. The next run uses the updated configuration.

**Why this priority**: Without parameterisation, all blocks run with defaults, limiting the Playground to basic usage. Inline config turns the feature into a no-code research tool.

**Independent Test**: Place a Vision Analysis block on the canvas, click it, edit the prompt field, run a one-block pipeline (Inputs → Vision → Outputs), and verify the custom prompt is reflected in the output.

**Acceptance Scenarios**:

1. **Given** a block is on the canvas, **When** the user clicks the block, **Then** a parameter panel slides open showing the block's configurable fields (name, description, and input parameters specific to that skill).
2. **Given** the parameter panel is open, **When** the user edits a field and closes the panel, **Then** the block label updates to reflect the change and the value is persisted to the pipeline graph state.
3. **Given** a block has a required parameter with no default, **When** the user tries to run without filling it, **Then** the block is highlighted with a validation warning and the run is prevented.

---

### User Story 3 — Save and Reload a Pipeline (Priority: P3)

After building and validating a pipeline, the researcher names it "Paper → Spec → Diagram" and saves it. On a later visit they open the Playground, click **Load**, select the saved pipeline, and the canvas restores exactly as left.

**Why this priority**: Reuse is what turns the Playground from a toy into a research accelerator. Pipelines can encode expert knowledge.

**Independent Test**: Build a three-block pipeline, save with a name, reload the page, open the Playground, load the saved pipeline, and verify all blocks and edges are restored with the same parameters.

**Acceptance Scenarios**:

1. **Given** a pipeline is on the canvas, **When** the user enters a name and clicks Save, **Then** the pipeline is persisted and appears in the Workflows nav section under its name.
2. **Given** a saved pipeline exists, **When** the user selects it from the Load list, **Then** the canvas clears and re-renders the saved graph with all blocks, edges, and parameter values intact.
3. **Given** a saved pipeline is loaded and modified, **When** the user saves using the same name, **Then** a confirmation prompt appears and the previous version is overwritten only after the user confirms.

---

### User Story 4 — Use an Agent Block in a Pipeline (Priority: P4)

A researcher assembles a pipeline that delegates to the **Blog Writer** sub-agent: Inputs (arxiv URL) → ArXiv Fetch → Blog Writer Agent → Outputs (draft post). Running the pipeline streams the agent's ReAct tool calls and final blog draft into the output.

**Why this priority**: Agent delegation is the most powerful use case but depends on P1–P2 being solid. It extends the Playground beyond single-tool chains to full multi-step research automations.

**Independent Test**: Build a two-block pipeline (Inputs → Blog Writer Agent → Outputs), provide an ArXiv URL as input, run, and verify a blog draft appears in the output with tool-call events visible in the chat.

**Acceptance Scenarios**:

1. **Given** an Agent block (e.g., Blog Writer) is placed on the canvas, **When** the pipeline runs, **Then** the agent's tool-start and tool-end events appear in the chat stream, attributed to that block.
2. **Given** an Agent block output is wired to a second block input (e.g., Outputs), **Then** the second block receives the agent's final text output as its input value.

---

### Edge Cases

- What happens when the user draws an edge that would create a cycle? The connection is rejected and a tooltip explains that cycles are not supported.
- What happens when the user removes a block that has existing edges? All connected edges are removed automatically.
- What happens when a required Inputs node is missing but the user clicks Run? The run is prevented; the missing Inputs node is highlighted.
- What happens when the Playground is open and the user submits a chat message simultaneously? Both execute independently — the chat stream and the pipeline stream are separate.
- What happens when the page is refreshed mid-run? The run terminates; on reload the canvas restores the last saved state (not the unsaved in-progress state).
- What happens when a block's backing tool is unavailable (e.g., OCR server not running)? The block errors immediately with a "tool unavailable" message; concurrent branches that do not depend on the failed block continue executing.
- What happens when a fan-out block feeds two downstream blocks and one of them errors? The errored branch halts at that block; the sibling branch continues independently.

---

## Requirements *(mandatory)*

### Functional Requirements

**Playground Panel**

- **FR-001**: The Playground sidebar MUST be togglable open and closed via a dedicated toolbar button and via keyboard shortcut (`Ctrl+Shift+P` / `Cmd+Shift+P`) without closing or interrupting the active chat.
- **FR-002**: The Playground sidebar MUST render alongside the chat panel (not replace it); both MUST be visible and interactive simultaneously on screen widths ≥ 1280 px.
- **FR-003**: On screen widths < 1280 px, the Playground MAY occupy full width and the user MUST be able to switch between chat and playground views.

**Skill Block Library**

- **FR-004**: The sidebar MUST display a searchable, categorised library of all available skill blocks derived from the live registered tool list at runtime — no hardcoded block catalogue.
- **FR-005**: Blocks MUST be organised into the following categories: Vision, Research, Content, Agents, Utility. Each category MUST be collapsible.
- **FR-006**: Each block in the library MUST show its display name, a one-line description, and a colour-coded category badge.
- **FR-007**: Users MUST be able to drag a block from the library onto the canvas to instantiate it.

**Canvas & Graph**

- **FR-008**: The canvas MUST support placing multiple block instances, each visually distinct with an input port (left side) and one or more output ports (right side).
- **FR-009**: Users MUST be able to draw directed edges between an output port of one block and an input port of another by clicking and dragging.
- **FR-010**: The canvas MUST prevent cyclic edges; an attempted cycle MUST be rejected with an inline tooltip.
- **FR-011**: Every valid pipeline MUST include exactly one **Inputs** node and at least one **Outputs** node; the Run button MUST be disabled otherwise.
- **FR-012**: Users MUST be able to delete a block (keyboard Delete / right-click menu) or an edge (click to select, then Delete).
- **FR-012a**: The canvas MUST support full multi-step undo (Ctrl+Z / Cmd+Z) and redo (Ctrl+Y / Cmd+Shift+Z) for all canvas mutations: add block, move block, delete block, add edge, delete edge, edit block parameters, clear canvas.
- **FR-013**: The canvas MUST support pan (click-drag on empty canvas) and zoom (scroll wheel).

**Block Configuration**

- **FR-014**: Clicking a block on the canvas MUST open an inline parameter panel listing all configurable fields for that skill, derived from the tool's parameter schema.
- **FR-015**: Required fields MUST be visually distinguished from optional fields. Attempting to run with an empty required field MUST surface a validation warning on that block.
- **FR-016**: Parameter values MUST be persisted within the pipeline graph state; they MUST survive toggling the sidebar closed and reopening it.

**Execution**

- **FR-017**: Pressing **Run** MUST execute the pipeline DAG in topological order. When a block's output fans out to multiple downstream blocks, those independent branches MUST run concurrently. Each downstream block receives the same output value from the shared upstream block.
- **FR-018**: During execution, each block node MUST display a status indicator: `pending` (grey), `running` (blue pulse), `done` (green), `error` (red).
- **FR-019**: Execution events (tool starts, outputs, errors) MUST stream to the main chat panel in real time, clearly labelled with the originating block name.
- **FR-020**: Pipeline execution MUST be handled by a new Python DAG runner that calls `@tool` functions directly in topological order. The existing `/ws/workflows/{run_id}` WebSocket stream protocol MUST be reused to deliver per-node status events and outputs to the frontend; no new streaming protocol is introduced.

**Save & Load**

- **FR-021**: Users MUST be able to name and save the current canvas state as a **pipeline** via a **Save** button. The saved pipeline is stored as a workflow in the `output/.workflows` layer.
- **FR-021a**: When saving with a name that already exists, the system MUST display a confirmation prompt ("A pipeline named '[X]' already exists. Overwrite?") with **Overwrite** and **Cancel** actions. The existing pipeline MUST only be replaced if the user confirms.
- **FR-022**: Saved pipelines MUST persist to the existing `output/.workflows` storage directory and MUST appear in the existing **Workflows** section of the navigation sidebar.
- **FR-023**: Users MUST be able to load any saved pipeline from a **Load** dropdown on the Playground toolbar, restoring all blocks, edges, and parameter values.

### Key Entities

- **Pipeline Graph**: A directed acyclic graph consisting of nodes (block instances) and edges (data connections). Attributes: name, created_at, nodes[], edges[].
- **Block Instance**: An instantiated copy of a skill placed on the canvas. Attributes: id, skill_name, category, position (x, y), config (parameter key-value map), status.
- **Edge**: A directed connection from one block's output port to another block's input port. Attributes: source_block_id, source_port, target_block_id, target_port.
- **Inputs Node**: A special block that defines the pipeline's entry data (image path, text string, URL). Always the topological start of the graph.
- **Outputs Node**: A special block that captures and displays the pipeline's final results.
- **Skill Block Definition**: A read-only descriptor derived from a registered `@tool` function. Attributes: name, description, category, parameter_schema.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with no prior Playground experience can assemble, configure, and run a two-block pipeline in under 3 minutes from opening the sidebar.
- **SC-002**: The Playground sidebar opens and renders all skill blocks within 500 ms of the toggle action on a standard local dev machine.
- **SC-003**: A pipeline run with up to 5 sequential blocks completes with streaming output visible in the chat — no silent failures or blank outputs.
- **SC-004**: 100% of currently registered tools and agents appear as draggable blocks in the library with no manual registration step beyond the existing `build_tools()` call.
- **SC-005**: A saved pipeline reloads its full graph (all blocks, edges, and parameter values) without loss on page refresh.
- **SC-006**: The chat remains fully responsive (accepts input, displays streaming responses) while a pipeline is running in the Playground.
- **SC-007**: Block-level execution status updates (pending → running → done / error) appear within 200 ms of the corresponding backend event reaching the frontend.

---

## Terminology

| Term | Definition | Avoid |
|------|-----------|-------|
| **Pipeline** | The visual directed acyclic graph the user assembles on the canvas — blocks wired together to process data. Used in all user-facing labels, FR text, and code identifiers for the canvas layer. | "Workflow" when referring to the canvas construct |
| **Workflow** | The persisted representation of a pipeline stored in `output/.workflows` and listed in the **Workflows** navigation section. This is the storage/nav layer term inherited from the existing UI. | "Pipeline" when referring to the storage layer |
| **Block** | A single node on the canvas representing one instantiated skill or agent. | "Node", "Step", "Tool" in user-facing text |
| **Skill** | A registered `@tool` function available as a draggable block in the library. | "Tool" in user-facing labels (reserved for internal/code usage) |
| **Canvas** | The interactive drawing surface where blocks and edges are placed. | "Board", "Graph area" |
| **Edge** | A directed connection between an output port of one block and an input port of another. | "Link", "Arrow", "Connection" |

---

## Assumptions

- Pipeline execution does **not** route through the Eko sidecar. A new lightweight Python DAG runner in the backend executes `@tool` functions directly in topological order. The existing `/ws/workflows/{run_id}` WebSocket protocol is reused for streaming per-node status events to the frontend.
- Block definitions (name, description, parameter schema) are served by a new lightweight REST endpoint (`/api/skills`) that reads from the live `build_tools()` registry — no static config file required.
- No authentication or per-user isolation is required; the Playground shares the session context of the current chat.
- The visual graph library used for the canvas is a pure-JS, MIT/BSD-licensed library (e.g., Drawflow or a custom SVG/Canvas implementation) requiring no new Python server dependencies.
- Mobile support (< 1280 px) is out of scope for the initial release.

## Clarifications

### Session 2026-03-10

- Q: Should pipeline execution route through the Eko sidecar or should the Python backend directly orchestrate tools in topological order? → A: Direct Python orchestration — a new lightweight DAG runner executes `@tool` functions in topological order without involving the Eko sidecar.
- Q: Should the DAG runner support parallel fan-out (multiple blocks receiving the same output and running concurrently)? → A: Full DAG — fan-out supported; independent branches run concurrently.
- Q: Should the canvas support undo/redo for the initial release? → A: Full multi-step undo/redo (Ctrl+Z / Ctrl+Y) for all canvas mutations.
- Q: When saving a pipeline with a name that already exists, what should happen? → A: Confirmation prompt — "A pipeline named X already exists. Overwrite?" with Overwrite / Cancel.
- Q: Which term should be canonical for the visual construct the user builds in the Playground? → A: "Pipeline" — canonical for the visual construct and all user-facing canvas labels; "Workflow" retained only for the storage layer (`output/.workflows`) and existing Workflows nav section.
