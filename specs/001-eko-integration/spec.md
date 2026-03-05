# Feature Specification: Eko Agentic Workflow Integration

**Feature Branch**: `001-eko-integration`
**Created**: 2026-03-05
**Status**: Draft (amended 2026-03-05 — BrowserAgent added as US4)
**Input**: Add https://github.com/FellouAI/eko for the agentic workflow + BrowserAgent

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

### User Story 4 — Browser-Automated Research with BrowserAgent (Priority: P4)

A user wants to research a topic that has no API — for example, browsing a CVPR
proceedings page to collect all paper titles and links, scraping a benchmark
leaderboard table from Papers With Code, or navigating to a specific GitHub repo
to extract model architecture details. With BrowserAgent, the user describes the
task in natural language ("Collect all CVPR 2025 paper titles tagged with
'segmentation' and add them to the knowledge graph") and the system autonomously
navigates, clicks, reads, and screenshots the target pages — all headlessly on
the server, with live status streamed to the UI.

**Why this priority**: Extends research reach to sites with no public API — the
long tail of academic sources, conference pages, leaderboards, and repositories.
Builds on US1 (workflow orchestration) and adds the browser as a first-class
research tool. Lower priority than US1–3 because it requires Playwright installation
and introduces more surface area for anti-scraping failures.

**Independent Test**: A user submits a workflow that includes a BrowserAgent step
(e.g., "navigate to arxiv.org/search, filter by 'video segmentation', collect
the top 10 paper links"). The step executes headlessly, returns a list of URLs
and titles, and those are passed to subsequent steps (fetch PDF, generate spec)
in the same workflow — all without manual browser interaction.

**Acceptance Scenarios**:

1. **Given** a workflow includes a step requiring browser navigation, **When** that
   step executes, **Then** BrowserAgent opens a headless Chromium instance, performs
   the navigation and extraction, and returns structured results to the next step
   within a reasonable time (no hard timeout for complex pages, but progress
   heartbeats appear every 30 seconds).
2. **Given** a BrowserAgent step captures a screenshot (e.g., a benchmark
   leaderboard), **When** the step completes, **Then** the screenshot is saved to
   `output/.workflows/<run-id>/screenshots/` and a thumbnail is shown in the
   Workflows UI alongside the step output.
3. **Given** a BrowserAgent step requires interacting with a page that blocks
   headless browsers, **When** the blocking is detected, **Then** the step reports
   a clear failure message ("Page blocked automated access") and the workflow
   offers to retry in headed mode or skip the step.
4. **Given** the user has stored site credentials as a Power (username/password or
   cookies), **When** a BrowserAgent step navigates to that site, **Then**
   BrowserAgent auto-loads the stored credentials so the session is authenticated
   without user intervention.

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
- What happens when a BrowserAgent step navigates to a page that requires
  JavaScript-heavy rendering? BrowserAgent MUST wait for the page's load state
  before extracting content; a configurable wait timeout applies.
- What happens when Playwright (Chromium) is not installed on the host? The system
  MUST detect this at Eko sidecar startup and show an actionable error ("Run
  `playwright install chromium` to enable BrowserAgent") rather than failing
  silently at runtime.

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
- **FR-011**: The system MUST support BrowserAgent as a workflow step type, enabling
  headless Chromium-based navigation, content extraction, and screenshot capture
  within any workflow.
- **FR-012**: Screenshots captured by BrowserAgent MUST be saved to
  `output/.workflows/<run-id>/screenshots/` and displayed as thumbnails in the
  Workflows UI alongside the step that produced them.
- **FR-013**: The system MUST detect whether Playwright Chromium is installed at
  Eko sidecar startup and surface a clear, actionable error if it is missing.
- **FR-014**: Site credentials (cookies or username/password) stored as a Power
  MUST be automatically loaded by BrowserAgent when navigating to the matching
  site, enabling authenticated scraping without per-run manual login.

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
- **BrowserSession**: A headless Chromium instance managed by BrowserAgent for the
  duration of a workflow step. Attributes: active page, open tabs, stored cookies,
  screenshots captured.
- **Screenshot**: A JPEG image captured by BrowserAgent during a step. Stored at
  `output/.workflows/<run-id>/screenshots/<step-name>.jpg`. Displayed as a
  thumbnail in the Workflows UI.

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
- **SC-007**: A BrowserAgent step that navigates, extracts content, and captures a
  screenshot completes and returns structured results to the next workflow step
  without any manual user interaction.
- **SC-008**: Screenshots produced by BrowserAgent steps are visible as thumbnails
  in the Workflows UI within 3 seconds of the step completing.

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
- BrowserAgent runs headlessly in the same Node.js sidecar via Playwright Chromium.
  Headed mode is available as a fallback for sites that block headless automation
  but is not the default.
- Browser extensions and client-side (in-browser) Eko agents are out of scope;
  only the server-side Node.js BrowserAgent is integrated.
- Anti-detection features (stealth plugin, randomised mouse, disabled automation
  flags) are enabled by default to maximise compatibility with research sites.
- Site credential storage (cookies / username-password) reuses the existing Powers
  infrastructure — a new "Browser Credentials" Power type is added, storing
  credentials in `.env` encrypted at rest.
- Playwright Chromium is installed separately via `playwright install chromium`;
  the sidecar startup check enforces this before accepting workflow requests.
