# ROADMAP

## Project Vision
JPLlamA becomes a practical digital employee for knowledge work: email intelligence, RFQ review, Obsidian memory capture, and executive response generation.

## Milestones

### Milestone 16 - Workflow Redesign (Version 2.0)
Status: Completed
- Reframed the product as an AI Operations Assistant with archive-first knowledge capture and answer-from-notes retrieval.
- Added explicit knowledge find/answer modes with source labeling for vault, internet, Ollama, and mixed answers.
- Hardened presentation delivery so generated PPTX files are copied into the output folder, verified, and surfaced with path actions.
- Redefined RFQ review output into an executive benchmark-style report with recommendation and customer/product/legal questions.
- Preserved backend routing and storage architecture while modernizing behavior and operator visibility.
- Expanded regression tests and rebuilt the macOS bundle for the 2.0 release line.

### Milestone 1 - Core Routing
Status: Completed
- Prompt planning and route selection.
- Ollama chat integration.
- Initial Obsidian search injection.

### Milestone 2 - Presentation Engine
Status: Completed
- Presenton API integration.
- 3-slide executive generation workflow.
- Output persistence to output/.

### Milestone 3 - Obsidian Organization
Status: Completed
- Vault organizer command flow.
- Category movement, metadata enrichment, duplicate/archive handling.
- Report generation for dry-run and full-run review.

### Milestone 4 - Digital Employee
Status: Completed
- End-to-end email workflow for .eml, optional .msg, copied text, and uploaded file paths.
- Automatic parse, summary, tags, entity detection, action extraction.
- Dual retrieval context from Obsidian + memory summaries.
- RFQ review mode with multi-source context assembly.
- Email memory persistence with markdown note generation, related links, index updates, and backlinks.

### Milestone 5 - Operational Hardening
Status: In Progress
- Expand observability and structured logging.
- Add regression tests for command-level integration flows.
- Add retry/backoff for local service dependencies.

### Milestone 6 - Automation Surfaces
Status: Completed
- Open WebUI upload watcher implemented.
- Background vault indexing implemented.
- Action export (JSON/CSV) implemented as first task-system handoff.

### Milestone 10 - Version 1.0 Final Polish
Status: Completed
- Added polished startup banner and command status rendering.
- Added professional dynamic help/capabilities surface grouped by domain.
- Added health command with connectivity, tests, and knowledge statistics.
- Added version command with modules, capabilities, test status, and git revision.
- Added backup commands for knowledge, vault, and configuration.
- Added export commands for lessons, RFQs, emails, presentations, and full knowledge.
- Improved configuration loading from environment and runtime validation.
- Completed full regression suite for Version 1.0 release readiness.

### Milestone 11 - Desktop Experience (Version 1.1)
Status: Completed
- Redesigned GUI into primary desktop interface with retro-futuristic command console style.
- Added natural-language command bar and large drag-and-drop workspace for mixed content ingestion.
- Added smart action suggestions based on detected dropped content type (RFQ, email, presentation, knowledge, image, document).
- Replaced plain text output with rich scrolling results panel supporting markdown rendering, status highlighting, links, and artifact actions.
- Added left sidebar for recent activity/files/searches and favorite commands.
- Added right sidebar for knowledge summary, related notes, current vault, current customer, and current project.
- Added persistent status bar details for vault, Ollama, Presenton, knowledge size, and current task.
- Added task progress surface with current step, ETA, and processed-file count.
- Added settings dialog, interactive searchable help dialog, and professional about dialog.
- Added scalable in-app logo/icon rendering for application icon, window icon, and about view.
- Preserved backend architecture, storage model, and folder ownership philosophy.

### Milestone 12 - Desktop Polish & Integration (Version 1.2)
Status: Completed
- Audited and fixed desktop integration bugs from real usage: legacy vault path, folder detection, knowledge count, related notes surface, and customer/project state.
- Removed deprecated hardcoded legacy vault references and aligned modules to configuration-driven vault selection.
- Upgraded command routing so explicit knowledge prompts use vault retrieval and general AI prompts route to Ollama chat.
- Expanded desktop drop analysis to show type, customer, project, confidence, recommended workflow, and recommendation rationale.
- Converted results panel into persistent conversation history with user/assistant turns, status markers, markdown, links, and image rendering.
- Added real related-note retrieval in the right sidebar with explicit empty-state messaging.
- Added customer/project auto-detection updates across drop, email, RFQ, presentation, and document command flows.
- Extended About surface with logo, version, modules, knowledge stats, app path, vault path, and git revision.
- Prepared packaging pipeline for macOS app generation with PyInstaller spec, metadata, icon bundle, and build script.
- Generated and wired logo assets in PNG, SVG, and ICNS formats.

### Milestone 13 - Desktop Experience Polish (Version 1.3)
Status: Completed
- Rebuilt desktop shell for high-fidelity command-center interaction while preserving backend routing and storage architecture.
- Added persistent theme system (Modern, Retro Futuristic, Classic Console) with runtime switching and stored preference.
- Added multiline command composer with keyboard-first execution and history navigation ergonomics.
- Added non-blocking worker execution for command processing with explicit progress phases and responsive UI.
- Improved conversation rendering with styled turns, status markers, markdown output handling, and controlled autoscroll behavior.
- Improved smart drop workflow with clearer type detection rationale, recommended actions, and success feedback.
- Hardened presentation error messaging with explicit reason, retry, and settings guidance.
- Added knowledge fallback behavior so explicit vault misses can continue with Ollama general AI response.
- Completed regression validation for Version 1.3 release readiness.

### Milestone 14 - Production Readiness (Version 1.4)
Status: Completed
- Added strict non-blocking execution UX with live staged progress and observable long-running operations.
- Added Run/Stop control with safe cancellation behavior and immediate UI idle recovery.
- Added live Presenton and Ollama stage feedback in the desktop conversation stream.
- Added live vault-search feedback stages (vault, Obsidian, memory, related notes, ranking, context, hit/miss).
- Added expanded progress telemetry panel and service monitor panel for operational transparency.
- Added timeout watchdog and user decision handling (continue, retry, cancel) for stalled operations.
- Added optional developer mode logs and lightweight CPU/RAM diagnostics.
- Preserved existing backend architecture, routing contracts, knowledge ownership rules, and workflow modules.

### Milestone 7 - RFQ Review Workflow
Status: Completed
- Permanent RFQ/tender/contract/bid review workflow added.
- Multi-format staged processing for email, PDF, DOCX, XLSX, PPTX, ZIP, and mixed bundles.
- Compact retrieval context from Obsidian, memory, prior RFQs, contracts, presentations, and action history.
- DP World baseline comparison with explicit outside-baseline and no-go detection.
- JP-format dual outputs: Markdown + DOCX tables and sign-off gate.
- RFQ knowledge capture persisted to Obsidian with index and backlinks.

### Milestone 8 - Obsidian Reliability
Status: Completed
- Added explicit organizer safety modes: dry-run, analyze, organize, repair.
- Added import lock protection so organize/repair exits safely while import is active.
- Enforced markdown-only organization and stricter ignored attachment/resource trees.
- Preserved original filename/path as metadata aliases to keep renamed notes searchable.
- Improved search scoring coverage across title, aliases, tags, summary, body, filename, folder, backlinks, and related links.
- Expanded index coverage to include RFQ and Emails and ensured index links point to current note paths.
- Added regression tests for visibility after move/rename, lock behavior, mode behavior, and attachment safety.

### Milestone 8 - Knowledge Management
Status: Completed
- Added permanent user folder ownership rule enforcement for memory storage flows.
- Added knowledge read/search route with ranked vault retrieval, summaries, links, and related note surfacing.
- Added domain-specific storage targets:
	- eMails to Remember
	- Presentation Powerpoint Knowledge Base
	- RFQ Contract Review Knowledge Base
	- DP World
	- Cargo Partner
	- CIQ AWK recovery
	- RKC Cumbria
	- HandNotes
- Added deduplication and linking-first memory behavior for new note capture.
- Added integration tests for remember, email/presentation/RFQ store, vault read, semantic search, and related-note retrieval.

### Milestone 9 - JP Knowledge Assistant
Status: Completed
- Added dynamic help/capabilities command route for supported workflows and query surfaces.
- Added structured lesson-learning capture via remember lesson commands with Situation/Decision/Outcome metadata.
- Added writing-style reference retrieval from prior stored notes for chat and presentation generation prompts.
- Strengthened knowledge retrieval response contract with Summary, Related knowledge, Source note paths, and Confidence.
- Added source-specific duplicate detection before storage for email, presentation, and RFQ knowledge bases.
- Expanded milestone integration tests for help, lesson storage, duplicate detection, and writing-style retrieval.

## Near-Term Priorities
1. Transition to usage-driven improvements from daily operations.
2. Validate extraction quality against larger real-world email corpora.
3. Expand RFQ ranking quality for mixed-format vault data.
4. Add downstream connectors beyond CSV/JSON for action sync.
