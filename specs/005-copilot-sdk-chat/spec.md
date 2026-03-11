# Feature Specification: GitHub Copilot SDK Chat Integration

**Feature Branch**: `005-copilot-sdk-chat`
**Created**: 2026-03-11
**Status**: Draft
**Input**: User description: "005-copilot-sdk: Integrate GitHub Copilot SDK (https://github.com/github/copilot-sdk) into the chat window for better chat experience and agentic behaviour."

## Overview

Integrate the GitHub Copilot SDK into the CV Zero Claw Agent chat window to replace or augment the current LLM backend with Copilot's production-tested agent runtime. This enables multi-step agentic workflows, stateful multi-turn conversations, real-time streaming responses, and access to Copilot's model fleet — delivering a significantly richer chat experience without building custom orchestration from scratch.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agentic Chat with Multi-Step Reasoning (Priority: P1)

A user types a complex computer vision task into the chat window (e.g., "label all potholes in the uploaded dataset and export to COCO format"). Instead of a single one-shot response, the chat window shows the agent breaking the task into steps, invoking CV tools (SAM3, Label Studio, etc.), and streaming progress back turn by turn until the task is complete.

**Why this priority**: This is the core value of the integration — replacing single-shot responses with an agentic loop that can plan, use tools, and complete multi-step CV workflows autonomously. Everything else builds on this.

**Independent Test**: Can be fully tested by submitting a multi-step task in chat and verifying the agent produces streamed intermediate steps and a final result, even with only a stub CV tool registered.

**Acceptance Scenarios**:

1. **Given** a user has the chat window open, **When** they submit a prompt requiring more than one action (e.g., "detect objects and then label them"), **Then** the chat shows multiple agent turns with progress updates before the final answer.
2. **Given** the agent is mid-task, **When** a registered tool (e.g., SAM3 segmenter) is invoked, **Then** the chat displays a tool-invocation indicator and the result inline.
3. **Given** the agent completes all steps, **When** the workflow finishes, **Then** the chat shows a clear completion state with a summary and any output artefacts linked.

---

### User Story 2 - Stateful Multi-Turn Conversation (Priority: P2)

A user asks a follow-up question in the same chat session (e.g., "now increase the confidence threshold to 0.8 and re-run") and the agent understands the previous context without the user repeating themselves.

**Why this priority**: Context retention is essential for a natural chat experience. Without it, every message is isolated, forcing users to repeat context — a major usability regression.

**Independent Test**: Can be fully tested by sending two related messages in sequence and verifying the second response references artefacts or decisions from the first, without re-stating the full context.

**Acceptance Scenarios**:

1. **Given** a completed first turn (e.g., an inference run), **When** the user sends a follow-up referencing "the previous result", **Then** the agent correctly identifies and acts on the prior output without asking for clarification.
2. **Given** a long conversation session, **When** the user references something from several turns ago, **Then** the agent retrieves and uses that context correctly.
3. **Given** a user starts a fresh session, **When** they reference something from a previous session, **Then** the agent responds that no prior context is available for the new session.

---

### User Story 3 - Model Selection in Chat (Priority: P3)

A user can select which Copilot-available model to use for the chat session (e.g., switch between a fast model for quick queries and a more capable model for complex reasoning tasks).

**Why this priority**: Model flexibility lets users trade off speed vs. capability per task. It is a UX enhancement that builds on the core agent integration being live.

**Independent Test**: Can be fully tested by rendering a model selector in the chat UI, choosing a model, submitting a prompt, and confirming the correct model ID is used in the session.

**Acceptance Scenarios**:

1. **Given** the chat window is open, **When** the user opens the model selector, **Then** a list of available Copilot models is shown, enumerated at runtime.
2. **Given** a model is selected, **When** the user submits a prompt, **Then** the session uses the chosen model for that response and all subsequent turns.
3. **Given** no model is explicitly selected, **When** the user submits a prompt, **Then** a sensible default model is used automatically.

---

### User Story 4 - Custom CV Tool Registration (Priority: P4)

A developer registers a custom CV tool (e.g., SAM3 segmenter, Label Studio exporter) as a Copilot SDK skill so the agentic runtime can invoke it automatically during workflows without manual orchestration.

**Why this priority**: Without custom tool registration, the agent cannot interact with the project's CV pipeline. This is a developer-facing capability that unlocks the full value of Stories 1–3.

**Independent Test**: Can be fully tested by registering a mock tool, instructing the agent to use it via chat, and verifying the tool is invoked with the correct parameters and the result appears in the chat.

**Acceptance Scenarios**:

1. **Given** a CV tool is registered as a Copilot SDK skill, **When** the agent determines the tool is needed, **Then** the tool is invoked with the correct input and the result is used in subsequent steps.
2. **Given** a tool returns an error, **When** the agent receives the error, **Then** the chat surfaces a meaningful message and the agent either retries or asks the user how to proceed.
3. **Given** a tool is not registered, **When** the agent would need it, **Then** the agent explains it cannot complete the step and suggests an alternative action.

---

### Edge Cases

- What happens when the Copilot CLI server is unavailable or the GitHub auth token is expired — does the chat degrade gracefully to the previous LLM backend or show a clear error?
- How does the system handle a very long agentic run that exceeds a reasonable timeout — is there a cancel/interrupt mechanism in the chat?
- What happens if the user sends a new message while the agent is still processing a previous turn — is the new message queued, rejected, or does it interrupt the current run?
- How are large tool outputs (e.g., full label files, model artefacts) surfaced in chat without flooding the message thread?
- What happens when the Copilot SDK is in Technical Preview and a breaking API change occurs — can the integration fall back without a full outage?

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The chat window MUST stream agent responses token-by-token so users see progress in real time rather than waiting for the full response.
- **FR-002**: The system MUST maintain stateful conversation sessions across multiple turns within a single chat session.
- **FR-003**: The system MUST support registering existing CV tools (SAM3, Label Studio export, dataset download) as Copilot SDK skills invocable by the agent.
- **FR-004**: The chat window MUST display tool-invocation events inline (tool name, status, and abbreviated output) so users can follow the agent's reasoning.
- **FR-005**: The system MUST enumerate available Copilot models at runtime and expose them for selection in the chat UI.
- **FR-006**: The system MUST authenticate with GitHub Copilot using GitHub OAuth or an environment-variable token, loaded from `.env` via `load_config()`.
- **FR-007**: The system MUST fall back gracefully — displaying a clear error and optionally re-routing to the existing LLM backend — when the Copilot SDK or CLI server is unreachable.
- **FR-008**: Users MUST be able to cancel a running agentic task from the chat window without requiring a page reload.
- **FR-009**: The system MUST NOT expose the GitHub auth token in any client-side rendered content or API response.
- **FR-010**: New Copilot SDK skills MUST be registerable without modifying core agent orchestration code — registration follows the existing `build_tools()` pattern in `agent.py`.

### Key Entities

- **CopilotSession**: Represents a single stateful chat session with the Copilot agent runtime; holds session ID, model selection, conversation history, and active tool list.
- **CopilotSkill**: A registered custom tool/skill exposed to the Copilot agent runtime; maps to an existing `@tool`-decorated function in `src/cv_agent/tools/`.
- **AgentTurn**: A single exchange in a multi-step agentic workflow; includes role (user/agent/tool), content, tool invocations, and streaming state.
- **ModelOption**: A Copilot-available model enumerated at runtime; includes model ID, display name, and capability tier.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can submit a multi-step CV task and receive a complete streamed agentic response — with tool invocations visible — within a single chat session and no page reload required.
- **SC-002**: Follow-up questions in the same session correctly reference prior context across at least 5 sequential turns, with no context loss observed.
- **SC-003**: All existing registered CV tools (SAM3, Label Studio, dataset tools) are invocable by the agent without any changes to their existing tool implementation files.
- **SC-004**: The chat window remains responsive during a running agentic task, and a cancel action halts the task and clears the in-progress indicator within 3 seconds.
- **SC-005**: A GitHub auth failure or SDK unavailability results in a user-visible error message within 5 seconds — not a silent hang or unformatted stack trace.
- **SC-006**: Zero GitHub credentials or internal session tokens are exposed in browser network traffic or rendered HTML.

---

## Assumptions

- The GitHub Copilot SDK is licensed under **MIT** (verified 2026-03-11, copyright GitHub Inc.) — fully permissive and compliant with project policy. No alternative integration path required.
- The existing chat WebSocket/SSE channel in the web server can be extended for streaming Copilot turns without a full rewrite.
- The developer running the agent has a valid GitHub Copilot licence and can generate an OAuth token or PAT for local development.
- The Copilot SDK "Technical Preview" status means the integration should be feature-flagged so it can be disabled without affecting the rest of the agent if a breaking change occurs.
- Model selection UI will be a lightweight addition to the existing chat input bar, consistent with the `⚡ Live` toggle pattern already present.

---

## Dependencies

- GitHub Copilot SDK (Python or Node.js) — **MIT License** (verified 2026-03-11, copyright GitHub Inc.)
- Existing `src/cv_agent/tools/` CV tool implementations (SAM3, Label Studio, dataset tools)
- Existing FastAPI + WebSocket/SSE web server (`web.py`)
- `load_config()` / `.env` for GitHub auth token management
- GitHub OAuth app or PAT for local and CI authentication
