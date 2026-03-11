# Feature Specification: Label Studio Integration

**Feature Branch**: `004-labelling-tool`
**Created**: 2026-03-11
**Status**: Draft
**Input**: User description: "Integrate Label Studio as a labelling skill/tool within the CV Zero Claw Agent"

## Clarifications

### Session 2026-03-11

- Q: How does the workflow DAG node signal that human labelling is complete? → A: Manual "Mark Complete" button — the user explicitly clicks a button in the UI to signal the labelling DAG node is finished.
- Q: Should Label Studio bind to localhost only or all network interfaces? → A: All interfaces (0.0.0.0) — Label Studio is accessible from other machines on the network.
- Q: Should large dataset imports block the UI or run in the background? → A: Non-blocking with progress — import runs in the background; the UI shows a live progress bar (files imported / total).
- Q: How should labelling projects be named/identified when created programmatically? → A: Timestamp + dataset name, auto-generated (e.g., `2026-03-11_pothole-dataset`); human-readable and collision-free.
- Q: If Label Studio crashes unexpectedly, how should the agent respond? → A: Auto-restart — agent detects the crash, restarts Label Studio automatically, and all previously saved annotations are recovered from Label Studio's own database.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Launch Labelling Session (Priority: P1)

A CV practitioner opens the agent web UI, clicks "Labelling" in the sidebar, and within seconds has access to a fully functional Label Studio annotation workspace without any manual setup or installation steps.

**Why this priority**: The core value of this feature is zero-friction access to Label Studio. If users cannot start a session, nothing else works.

**Independent Test**: Can be tested by navigating to the labelling section in the sidebar and confirming the annotation workspace loads and is ready for use — this alone delivers MVP value.

**Acceptance Scenarios**:

1. **Given** the agent web UI is open and no labelling session is running, **When** the user selects "Labelling" from the sidebar, **Then** a Label Studio instance starts automatically and the annotation workspace is displayed within 30 seconds.
2. **Given** a labelling session is already running, **When** the user navigates to the labelling section, **Then** the existing session is resumed without data loss.
3. **Given** the labelling session encounters a startup error, **When** the user opens the labelling section, **Then** a clear error message with a retry option is shown.

---

### User Story 2 - Create and Manage Labelling Projects (Priority: P2)

A user creates a new labelling project, specifying the annotation types required (bounding boxes, polygons, keypoints, segmentation masks), and manages multiple projects within the same Label Studio instance.

**Why this priority**: Projects are the organising unit for all annotation work; without them users cannot structure their data.

**Independent Test**: Can be tested by creating a project with each annotation type and confirming the project appears in the project list with the correct configuration.

**Acceptance Scenarios**:

1. **Given** a labelling session is active, **When** the user creates a project with selected annotation types, **Then** the project appears in the project list and the annotation interface reflects the chosen types.
2. **Given** multiple projects exist, **When** the user switches between them, **Then** each project's data and annotations remain isolated and intact.
3. **Given** a project exists, **When** the user deletes it, **Then** the project and all associated annotations are removed and no longer listed.

---

### User Story 3 - Import Datasets and Annotate (Priority: P3)

A user imports a set of images or video frames from the agent's output directory into a labelling project, then performs annotations using the available tools (bounding boxes, polygons, keypoints, segmentation masks).

**Why this priority**: Importing data and annotating it is the primary workflow; it depends on a working project (P2) but delivers the core annotation value.

**Independent Test**: Can be tested end-to-end by importing a small image set, creating annotations of all supported types, and confirming annotations are saved and retrievable.

**Acceptance Scenarios**:

1. **Given** a project is selected, **When** the user imports images or video frames from a local path, **Then** all files appear as tasks in the annotation queue ready to annotate.
2. **Given** an image task is open, **When** the user draws a bounding box, polygon, keypoint, or segmentation mask, **Then** the annotation is saved and visible on re-opening the task.
3. **Given** a video file is imported, **When** the user opens it in the annotation interface, **Then** individual frames are accessible for per-frame annotation.
4. **Given** an import of an unsupported file type, **When** the import is attempted, **Then** the user receives a clear message listing supported formats.

---

### User Story 4 - Export Annotations (Priority: P4)

A user exports completed annotations from a project in their chosen format (COCO, YOLO, Pascal VOC) to a local output directory for use by downstream CV tools.

**Why this priority**: Annotations have no value to the CV pipeline until they are exported in a usable format; this closes the labelling loop.

**Independent Test**: Can be tested by annotating a small dataset, exporting in each format, and validating the output files are correctly structured and parseable by reference tools.

**Acceptance Scenarios**:

1. **Given** a project with completed annotations, **When** the user selects an export format and triggers export, **Then** a valid annotation file in the chosen format is written to the agent output directory.
2. **Given** a COCO export, **When** the file is opened, **Then** it conforms to the COCO JSON schema with correct image IDs, category mappings, and annotation coordinates.
3. **Given** a YOLO export, **When** the files are examined, **Then** each image has a corresponding `.txt` label file with normalised coordinates.
4. **Given** a Pascal VOC export, **When** the files are examined, **Then** each image has a corresponding `.xml` file following VOC format conventions.
5. **Given** a project with no completed annotations, **When** export is triggered, **Then** the user is warned that no annotations exist before proceeding.

---

### User Story 5 - Labelling as a Workflow DAG Node (Priority: P5)

A user includes a labelling task as a node in a workflow DAG, so that annotation of a dataset can be triggered programmatically and the exported annotations flow automatically to the next pipeline stage.

**Why this priority**: Workflow integration enables automated pipelines (e.g., auto-label → human review → train), but it requires all previous capabilities to work first.

**Independent Test**: Can be tested by constructing a minimal DAG with a single labelling node, running it, and verifying the node completes and produces an annotation output file accessible to subsequent nodes.

**Acceptance Scenarios**:

1. **Given** a workflow DAG with a labelling node configured with a dataset path and export format, **When** the DAG is executed, **Then** the labelling node opens the dataset for annotation and displays a "Mark Complete" button; the node signals done only when the user clicks that button.
2. **Given** a completed labelling node, **When** the next DAG node runs, **Then** it can access the exported annotation file via the node's output reference.
3. **Given** the labelling node is cancelled mid-session, **When** the DAG is resumed, **Then** partial annotations are preserved and the node continues from where it left off.

---

### Edge Cases

- What happens when Label Studio fails to start (port conflict, missing dependency)?
- How does the system handle importing a dataset folder with thousands of images? → Import runs in the background with a live progress bar; tasks become annotatable as they are indexed.
- What happens if the user closes the browser tab mid-annotation — are in-progress annotations auto-saved?
- How does the system behave when two users attempt to annotate the same project simultaneously?
- What happens when an export is requested for a partially annotated dataset (some tasks complete, some not)?
- How does the system handle video files too large to load in the browser?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow users to start a Label Studio instance from the agent web UI without manual installation or configuration; the instance MUST bind to all network interfaces so team members on the same network can access it.
- **FR-001a**: System MUST display the active Label Studio host:port to the user so remote team members can connect directly.
- **FR-002**: System MUST display the Label Studio annotation workspace within the agent's existing web interface (sidebar navigation + embedded view).
- **FR-003**: System MUST allow users to create labelling projects with any combination of annotation types: bounding box, polygon, keypoint, and segmentation mask.
- **FR-004**: System MUST allow users to import image files (JPEG, PNG, BMP, TIFF) and video frames from local paths visible to the agent; imports MUST run in the background with a live progress indicator (files imported / total) so the UI remains responsive.
- **FR-005**: System MUST provide an annotation interface supporting all four annotation types within a single project.
- **FR-006**: System MUST persist annotations across browser sessions so that work is not lost on page reload or reconnect.
- **FR-007**: System MUST allow users to export completed annotations in COCO JSON, YOLO TXT, and Pascal VOC XML formats.
- **FR-008**: System MUST write exported annotation files to the agent's output directory with a predictable, user-visible path.
- **FR-009**: System MUST expose a "labelling" tool callable by the agent that can start a session, create a project, import a dataset, and trigger an export programmatically; projects created without a user-supplied name MUST receive an auto-generated name in `YYYY-MM-DD_<dataset-name>` format.
- **FR-010**: System MUST support labelling tasks as nodes in the existing workflow DAG runner, with defined inputs (dataset path, annotation config) and outputs (annotation file path, format); the node MUST remain in a waiting state until the user clicks the "Mark Complete" button in the labelling UI.
- **FR-011**: System MUST allow users to list, pause, and stop running Label Studio instances from the agent UI.
- **FR-012**: System MUST provide clear status feedback (starting, ready, error, restarting) when launching or managing a Label Studio instance.
- **FR-013**: System MUST monitor the Label Studio subprocess and automatically restart it on unexpected crash; all annotations saved prior to the crash MUST be recoverable from Label Studio's persistent database upon restart.

### Key Entities

- **LabellingProject**: A container for annotation work; has an auto-generated name in `YYYY-MM-DD_<dataset-name>` format, one or more annotation types, associated dataset, and completion status. Names are unique within a session.
- **AnnotationTask**: A single item (image or video frame) within a project awaiting or having received annotations.
- **Annotation**: A single label on a task; has type (bounding box / polygon / keypoint / mask), label class, coordinates, and author.
- **AnnotationExport**: The output of an export operation; references a project, format, output file path, and timestamp.
- **LabellingSession**: A running Label Studio instance; has a host/port, status (starting / ready / restarting / stopped / error), restart count, and association to the agent runtime.
- **WorkflowLabellingNode**: A DAG node that wraps a labelling session; has input dataset path, annotation config, export format, and output annotation path.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can start a labelling session and reach an annotation-ready workspace within 30 seconds of triggering the skill.
- **SC-002**: Users can complete a full annotation cycle — import dataset, annotate, export — without leaving the agent web interface.
- **SC-003**: Exported annotation files in all three formats (COCO, YOLO, Pascal VOC) are valid and immediately usable by standard CV training tools without manual post-processing.
- **SC-004**: Labelling workflow nodes integrate with existing DAG workflows without requiring configuration beyond dataset path and export format.
- **SC-005**: Annotation operations succeed for datasets of up to 10,000 images with no data loss.
- **SC-006**: All four annotation types (bounding box, polygon, keypoint, segmentation mask) are available in every created project.
- **SC-007**: Annotations are automatically saved; zero annotations are lost due to browser navigation, accidental page close, or Label Studio process crash — the agent auto-restarts Label Studio and all persisted annotations are recovered.
- **SC-008**: The labelling agent tool can be invoked programmatically and returns an export file path upon completion, enabling downstream workflow steps.

## Assumptions

- Label Studio will be installed into the project's virtual environment (Apache 2.0 license); no separate system-level installation is required.
- Label Studio will run as a local subprocess on a configurable port (default 8080), binding to all network interfaces (0.0.0.0) to allow access from other machines on the same network; separate from the agent's main web server (port 8420).
- The agent output directory (`output/`) is accessible to both the agent backend and the Label Studio instance for dataset import and annotation export.
- A single Label Studio instance serves all projects for a given agent session; multi-user/multi-instance scenarios are out of scope for this feature.
- Video annotation is limited to frame-by-frame annotation of extracted frames; real-time video playback with timeline annotation is out of scope.
- Authentication to Label Studio uses the existing Label Studio local token mechanism; no external SSO or multi-user auth is required.
- The frontend embedding uses an iframe pointing to the local Label Studio port; deep UI integration (custom components) is deferred to a future feature.

## Dependencies

- Label Studio ≥ 1.10 (Apache 2.0) — annotation backend
- Existing agent workflow DAG runner (`output/.workflows/`) — for workflow node integration
- Existing agent web server (uvicorn on port 8420) — for sidebar integration and REST proxy
- Agent output directory structure — for dataset import paths and annotation export paths
