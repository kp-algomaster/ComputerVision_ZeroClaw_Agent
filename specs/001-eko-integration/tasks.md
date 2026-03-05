# Tasks: Eko Agentic Workflow Integration

**Input**: Design documents from `/specs/001-eko-integration/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)


## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure for the Eko Node.js sidecar

- [X] T001 Create `eko_sidecar` directory at repository root
- [X] T002 Initialize Node.js project in `eko_sidecar` with Eko and Playwright dependencies (`package.json`)
- [X] T003 Configure `cv_agent/server_manager.py` to register and manage the `eko_sidecar` process
- [ ] T003a Update the Models View Server Management UI (`cv_agent/ui/app.js` and `cv_agent/ui/index.html`) to display the new Eko sidecar status (resolves FR-008)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

- [X] T004 Implement basic Express server in `eko_sidecar/index.js` to wrap Eko execution
- [X] T005 Update `cv_agent/config.py` to include Eko and Workflow configuration structures
- [X] T006 Implement `cv_agent/core/workflow_manager.py` to act as the python HTTP client for the Eko sidecar

**Checkpoint**: Foundation ready - Python backend can communicate with the basic Node.js sidecar.

---

## Phase 3: User Story 1 - Define and Run a Multi-Step Research Workflow (Priority: P1) 🎯 MVP

**Goal**: Users can compose and run multi-step agentic workflows from the frontend with execution orchestrated by Eko.

### Implementation for User Story 1

- [X] T007 [US1] Create Workflows view and tab container in `cv_agent/ui/index.html`
- [X] T008 [US1] Implement workflow submission logic and API route in `cv_agent/web.py`
- [X] T008a [US1] Add FastAPI route in `cv_agent/web.py` to proxy the Eko SSE stream to the frontend (Constitution Principle I)
- [X] T009 [US1] Implement workflow execution state streaming in `cv_agent/ui/app.js` to consume the SSE proxy
- [X] T010 [P] [US1] Add CSS styles for workflow steps in `cv_agent/ui/style.css`
- [X] T011 [US1] Map existing Python CV tools to Eko-compatible tool definitions in `eko_sidecar` by wrapping calls to the FastAPI tools endpoint

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Pause, Review, and Approve Workflow Steps (Priority: P2)

**Goal**: Add human-in-the-loop checkpoints allowing users to approve/reject workflow execution steps.

### Implementation for User Story 2

- [X] T012 [US2] Implement checkpoint pause and resume logic in `eko_sidecar/index.js`
- [X] T013 [US2] Add API endpoints in `cv_agent/web.py` for handling user checkpoint responses
- [X] T014 [US2] Update Workflows UI in `cv_agent/ui/index.html` and `app.js` to present pending approvals and accept user input

**Checkpoint**: User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Save and Re-run Workflow Templates (Priority: P3)

**Goal**: Enable users to save completed workflows as templates and re-run or schedule them.

### Implementation for User Story 3

- [X] T015 [US3] Add API route in `cv_agent/web.py` to save workflow JSON templates to `output/.workflows/`
- [X] T016 [US3] Implement template listing and "Run Template" action in `cv_agent/ui/app.js`
- [X] T017 [US3] Integrate saved templates with the existing Jobs view for scheduled execution

**Checkpoint**: All core UI/backend user stories (US1-US3) should now be independently functional

---

## Phase 6: User Story 4 - Browser-Automated Research with BrowserAgent (Priority: P4)

**Goal**: Support headful/headless web automation within workflows using Playwright.

### Implementation for User Story 4

- [X] T018 [US4] Implement `BrowserAgent` logic (Playwright integration) in `eko_sidecar/browser_agent.js`
- [X] T019 [US4] Integrate `BrowserAgent` into the Express server (`eko_sidecar/index.js`) as a tool/step
- [X] T020 [US4] Add sidecar startup check for Playwright Chromium installation in `cv_agent/server_manager.py` or Node.js bootstrap
- [X] T021 [US4] Implement screenshot saving to `output/.workflows/<run-id>/screenshots/`
- [X] T022 [P] [US4] Update UI in `cv_agent/ui/app.js` and `cv_agent/ui/style.css` to render screenshot thumbnails

**Checkpoint**: All user stories should now be independently functional

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [X] T023 Code cleanup, error handling, and timeout enforcement across Python and Node.js
- [X] T024 Write unit tests for `cv_agent/core/workflow_manager.py`
- [X] T025 Documentation updates for the new Eko integration and BrowserAgent
- [X] T026 Configure Eko SDK with Ollama LLM provider (`openai-compatible`, `qwen3.5:latest`)
- [X] T027 Add `Agentic Workflows` skill to `/api/skills` with dynamic sidecar health check
- [X] T028 Fix SSE event buffering race condition in sidecar stream handler

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - Must proceed sequentially in priority order (P1 → P2 → P3 → P4) for core implementation, but specific independent tasks can be parallelized.
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### Parallel Opportunities

- UI styling (T010, T022) can happen in parallel with backend implementation.
