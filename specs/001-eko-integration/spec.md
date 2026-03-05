# Feature Specification: Eko Agentic Workflow Integration

**Feature Branch**: `001-eko-integration`
**Created**: 2026-03-05
**Status**: Draft
**Input**: Add https://github.com/FellouAI/eko for the agentic workflow

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Define and Run a Multi-Step Research Workflow (Priority: P1)

A user wants to run a complex, multi-step research task that goes beyond a single
chat message — for example: "Search arXiv for the 3 most cited vision-transformer
papers this week, fetch and parse each PDF, extract equations and architecture
details, generate a spec for each, and add all to the knowledge graph." Today this
requires manually chaining multiple chat prompts. With Eko, the user describes the
workflow once in natural language and the system plans and executes all steps
autonomously with live progress visibility.

**Why this priority**: This is the core value of the integration. Multi-step
research workflows are the primary bottleneck for users today, and autonomous
orchestration is the single biggest productivity gain Eko unlocks.

**Independent Test**: A user submits a natural-language workflow description in the
Workflows view, watches the step-by-step execution plan appear, and sees each step
complete with output — all without typing follow-up prompts.

**Acceptance Scenarios**:

1. **Given** a user types a multi-step research task in the Workflows view, **When**
   they click Run, **Then** the system generates a step-by-step execution plan
   within 5 seconds and begins executing the first step automatically.
2. **Given** a workflow is running, **When** a step completes, **Then** the UI
   updates to show the step's output and advances to the next step without user
   intervention.
3. **Given** a workflow step fails, **When** the failure occurs, **Then** the system
   reports the specific failed step and its error, and offers to retry or skip —
   without silently aborting the whole workflow.
4. **Given** a workflow completes, **Then** all artifacts produced (specs, graph
   entries, downloaded files) are persisted exactly as they would be from running
   each step manually through the main agent.

---

### User Story 2 — Pause, Review, and Approve Workflow Steps (Priority: P2)

A user running an automated workflow wants to stay in control at critical decision
points — for example, before the system writes new spec files to the vault or sends
a digest to an external channel. The user can define a human-approval checkpoint in
the workflow, receive a notification in the UI when execution reaches it, review
what is about to happen, and approve or reject the action before execution continues.

**Why this priority**: Trust and oversight. Users need confidence that autonomous
workflows won't overwrite important files or send unreviewed content to external
channels. Human-in-the-loop is Eko's distinguishing feature and a direct expression
of Constitution Principle IV (Streaming-First) and II (Tool-Centric design).

**Independent Test**: A user defines a workflow with a checkpoint step. When the
workflow reaches that step, execution pauses, a prompt appears in the UI showing
what is pending, and the workflow continues only after the user clicks Approve
(or is cancelled on Reject).

**Acceptance Scenarios**:

1. **Given** a workflow contains a checkpoint, **When** execution reaches that step,
   **Then** the workflow pauses, the step is highlighted as "Awaiting Approval", and
   a UI notification appears within 2 seconds.
2. **Given** a workflow is paused at a checkpoint, **When** the user clicks Approve,
   **Then** execution resumes from the paused step within 3 seconds.
3. **Given** a workflow is paused at a checkpoint, **When** the user clicks Reject,
   **Then** the workflow is cancelled cleanly, no further steps execute, and all
   artifacts produced before the checkpoint are preserved.

---

### User Story 3 — Save and Re-run Workflow Templates (Priority: P3)

A user wants to save a workflow they have successfully run (e.g., "Weekly paper
sweep + knowledge graph sync") as a named template so they can re-run it on demand
or schedule it as a recurring job — without retyping the full natural-language
description each time.

**Why this priority**: Reuse multiplies the value of every workflow a user defines.
Templates also bridge Eko workflows into the existing Jobs view, enabling scheduled
autonomous research pipelines.

**Independent Test**: A user completes a workflow, saves it as a named template, and
later finds it in the template list. They click Run Template and the workflow
executes identically to the original.

**Acceptance Scenarios**:

1. **Given** a workflow has completed, **When** the user clicks "Save as Template"
   and provides a name, **Then** the template appears in the Workflow Templates list
   within the same session.
2. **Given** a saved template, **When** the user clicks Run, **Then** a new workflow
   run starts using the saved description with a fresh execution plan.
3. **Given** a saved template, **When** the user schedules it as a recurring job,
   **Then** it appears in the Jobs view and executes automatically on the configured
   schedule.

---

### Edge Cases

- What happens when the Eko service is not running when a workflow is submitted?
  The UI MUST show a clear "Eko service unavailable" error with a Start button;
  it MUST NOT silently queue or retry indefinitely.
- What happens when a workflow runs longer than 30 minutes? The user MUST receive
  a progress heartbeat every 60 seconds; a timeout warning MUST appear at 25 minutes
  with an option to extend or cancel.
- What happens if the user closes the browser mid-workflow? The workflow MUST
  continue running server-side; on reconnect the UI MUST resume showing live
  progress for any in-flight run.
- What happens when two workflows are submitted simultaneously? Both MUST run
  concurrently without interfering — each has its own isolated execution context
  and log stream.
- What happens when a workflow step produces an artifact that already exists
  (e.g., a spec for a paper already in the vault)? The system MUST warn the user
  and skip overwriting by default, with an explicit override option.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a Workflows view in the web UI where users
  can compose, run, and monitor agentic workflows using natural language descriptions.
- **FR-002**: The system MUST use Eko (https://github.com/FellouAI/eko) as the
  workflow orchestration engine, running as a managed Node.js sidecar service.
- **FR-003**: Workflow execution progress MUST be streamed to the browser in real
  time, showing each step's name, status (pending / running / done / failed), and
  output summary.
- **FR-004**: The system MUST support human-in-the-loop checkpoints that pause
  execution until the user explicitly approves or rejects the pending action.
- **FR-005**: Eko MUST be configured to use the same LLM endpoint already set up
  in the CV Agent so that no additional API keys are required by default.
- **FR-006**: Completed workflows MUST be saveable as named templates for re-use.
- **FR-007**: Saved templates MUST be schedulable as recurring jobs via the existing
  Jobs view.
- **FR-008**: The Eko sidecar service status (running / stopped) MUST be visible in
  the Models view Server Management panel alongside other managed local servers.
- **FR-009**: All artifacts produced by a workflow MUST be identical to those
  produced by running each equivalent step manually through the main agent.
- **FR-010**: Workflow runs MUST survive browser disconnection — execution continues
  server-side and full progress is recoverable on reconnect.

### Key Entities

- **Workflow**: A natural-language task description that Eko decomposes into an
  ordered, dependency-aware plan of steps. Attributes: run ID, description, status,
  step list, start time, end time.
- **Step**: A single unit of work within a workflow (e.g., "fetch paper",
  "generate spec"). Attributes: name, status, input, output summary, checkpoint flag.
- **Checkpoint**: A step requiring human approval before execution proceeds.
  Carries a description of the pending action and records an approve/reject outcome.
- **Template**: A saved workflow description with a user-given name, creation date,
  and optional recurring schedule. Instantiates into a new Workflow run on demand
  or by schedule.
- **Eko Sidecar**: The managed Node.js process hosting the Eko engine. Exposes a
  local HTTP API consumed by the Python server. Started and stopped alongside other
  managed local servers.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from typing a multi-step research task to seeing the
  first step begin execution in under 10 seconds.
- **SC-002**: Workflow step progress updates appear in the UI within 2 seconds of
  each step completing on the server.
- **SC-003**: A human-approval checkpoint pauses execution and notifies the user
  within 2 seconds of reaching the checkpoint.
- **SC-004**: 100% of artifacts produced by a completed workflow run are correctly
  persisted and verifiable in the vault, knowledge graph, and output directories.
- **SC-005**: Workflow templates can be created, listed, and re-run entirely within
  the UI without a page reload.
- **SC-006**: A workflow that was in progress at browser close is fully resumable
  on reconnect — correct step count, statuses, and partial outputs are all shown.

## Assumptions

- Eko runs as a Node.js sidecar service (Node 18+) on `localhost:7862`; the Python
  FastAPI server communicates with it via local HTTP. This is the simplest
  integration path given the Python-first codebase.
- The Eko sidecar is configured to use the Ollama OpenAI-compatible endpoint
  (`http://localhost:11434/v1`) by default — no new API keys required for basic use.
- Cloud LLM providers (Anthropic, OpenAI) remain optional for Eko and are
  configured as a Power; the default Ollama path requires zero additional setup.
- Eko workflows orchestrate the CV Agent's existing tools (paper fetch, spec
  generation, knowledge graph, dataset download) — Eko is the orchestrator, not a
  replacement for individual tool implementations.
- Workflow persistence (templates, run history) is stored as JSON files in
  `output/.workflows/` following the project's file-based storage pattern.
- Browser-based Eko agents (BrowserAgent, browser extensions) are out of scope for
  this feature; only the Node.js server-side orchestration layer is integrated.
