# CHANGELOG

## [2026-07-12] Milestone 19 - First Stable Presentation Workflow

### Added
- Added strict end-to-end presentation workflow validation that requires all production completion gates:
  - Presenton generation
  - PPTX validation
  - output artifact verification
  - Microsoft PowerPoint open confirmation
  - vault copy into `PPTX to Remember`
  - markdown note creation beside the PPTX
  - Knowledge Catalog update confirmation
- Added reliability evidence manifest for strict sequential 4-deck verification:
  - `output/workflow_presenton_4deck_manifest_20260712-000121.json`

### Changed
- Updated presentation-memory behavior to preserve one-to-one artifact mapping by creating a fresh presentation note when a concrete PPTX path is provided.

### Fixed
- Fixed post-export completion failure at `knowledge_catalog` caused by deduplicated markdown-note reuse with a new PPTX path.
- Fixed Presenton polling termination behavior to remove fixed poll-count ceilings and rely on terminal status or configured timeout.

### Validation
- Single-deck production workflow completed 100% with all completion gates satisfied.
- Four-deck strict sequential reliability run completed successfully (Overview, SSL, Global Standard Conditions, Switzerland).

## [2026-07-11] Milestone 18 - Command-Driven Knowledge and Reference Library

### Added
- Command-driven source policy.
- JPLlamA system folder `_JPLlamA` scaffolding.
- Knowledge Catalog scaffold (`Knowledge Catalog.md` / `Knowledge Catalog.json`).
- Folder Map scaffold (`Folder Map.md` / `Folder Map.json`).
- Reference Source registry scaffold (`reference_sources.yml`).
- DP World Freight Forwarding Documentation Centre reference registration and indexing/downloader support.

### Changed
- Vault/knowledge is no longer searched automatically for default prompts.
- Web search is no longer used automatically for default prompts.
- Reference sources are explicit-only.
- Source mode is shown in CLI/GUI responses.

### Fixed
- Knowledge retrieval no longer blocks direct tasks by default.
- Weather/current-data prompts no longer silently trigger vault search.
- Presentation prompts no longer consult vault context unless explicitly requested.

### Known Issues
- Presenton runtime stability may still need separate follow-up.
- RFQ intelligence can be improved after source-policy redesign.
- Knowledge Catalog quality improves as more remembered artifacts are cataloged.

## [2026-07-08] Milestone 17 - Search + Presentation Hardening

### Added
- SearXNG integration.
- Internet search.
- Presentation validation.
- Real PPTX storage.

### Fixed
- Placeholder PPTX bug.
- Artifact handoff.
- Open/Reveal buttons.

### Known Issues
- Intent router still missing.
- Smarter source selection.

## [2026-07-08] Milestone 16 - Workflow Redesign (Version 2.0)

### Added
- Added runtime dependency report coverage for Vault, Ollama, Presenton, Open WebUI, and Docker in health output.
- Added optional Open WebUI runtime setting (`JPLLAMA_OPENWEBUI_URL`) for explicit dependency visibility.
- Added GUI service monitor metadata for each service:
  - current status
  - current stage
  - last update age
  - helpful operational message
- Added prompt-driven slide count extraction so requests like "2-slide" are honored in GUI and CLI presentation routes.
- Added regression tests for status callback collision safety and runtime dependency classification.

### Changed
- Updated app version from 1.4 to 1.5 in app/main.py.
- Updated macOS bundle metadata to 1.5.0 in packaging/pyinstaller/jpllama_gui.spec.
- Refined GUI service state model to consistent lower-case states:
  - connected
  - busy
  - waiting
  - unavailable
  - error
  - disconnected
- Clarified Open WebUI runtime role as optional watcher integration (not required in current core GUI workflow path).

### Fixed
- Fixed status plumbing collision bug that could raise:
  - `main._emit_status() got multiple values for keyword argument 'service'`
- Fixed callback fan-out collisions by sanitizing duplicate service keys before forwarding status payloads.
- Improved Presenton failure transparency by surfacing underlying request error details.

### Tests
- Targeted regression suite passed for GUI/main/client/service watcher coverage.
- Full test suite result after Version 1.5 stabilization changes: 99 passed.

## [2026-07-08] Milestone 14 - Production Readiness (Version 1.4)

### Added
- Added Run/Stop execution control in desktop GUI so active operations can be cancelled safely and UI immediately returns to idle state.
- Added live operation-stage streaming in conversation panel for observability during command execution.
- Added expanded progress panel telemetry:
  - Overall Progress
  - Current Stage
  - Current Service
  - Elapsed Time
  - ETA
  - Files Processed
  - Current Customer
  - Current Project
  - Current Job ID
- Added service monitor panel with live states for Vault, Ollama, Presenton, and Knowledge.
- Added timeout watchdog detection (30s no-response) with Continue/Retry/Cancel prompt.
- Added developer-mode live log panel for service timing and operational traces.
- Added lightweight runtime diagnostics surface (CPU load and process RAM) in GUI health panel.
- Added optional status callbacks and cancellation hooks to Ollama and Presenton clients for staged live feedback.

### Changed
- Updated GUI worker orchestration to emit staged progress and stream operational updates while preserving non-blocking UI behavior.
- Updated command input ergonomics:
  - Enter and Ctrl+Enter run command
  - Shift+Enter keeps multiline editing
  - Paste/drag URL payloads insert local file paths directly in command input
- Improved status bar color-state behavior for Connected/Working/Busy/Error.
- Updated presentation failure UX with service/stage/reason guidance and explicit remediation actions.
- Updated app version from 1.3 to 1.4 in app/main.py.

### Fixed
- Fixed progress visibility gaps where long-running service calls lacked explicit live stage messages.
- Fixed cancellation UX gap where Run did not expose a Stop action during active execution.

### Tests
- Updated version assertion in tests/test_main_commands.py for 1.4.
- Full suite executed for regression validation after milestone integration.

## [2026-07-08] Milestone 13 - Desktop Experience Polish (Version 1.3)

### Added
- Added full desktop shell modernization in app/gui/main_window.py with a high-fidelity command-center layout and branded header.
- Added multi-theme desktop styling (Modern, Retro Futuristic, Classic Console) with persisted user preference via QSettings.
- Added multiline command input with keyboard ergonomics:
  - Ctrl+Enter to run command
  - Alt+Up / Alt+Down command history navigation
- Added non-blocking command execution using QThreadPool + QRunnable workers with live phase/progress updates.
- Added drag-and-drop highlight state and drop-success visual feedback animation.
- Added explicit smart-workflow recommendation rationale in drop analysis output.

### Changed
- Updated app version from 1.2 to 1.3 in app/main.py.
- Improved presentation failure UX in desktop UI with explicit reason, retry guidance, and settings remediation hints.
- Improved knowledge-query behavior to fallback to Ollama general AI response when vault has no relevant stored notes.
- Updated conversation rendering behavior with role-specific turn styling and bottom-follow autoscroll logic.
- Updated desktop settings/about/help surfaces to align with production polish requirements.

### Fixed
- Fixed GUI module import-path issue by exposing helper functions at module scope for test/runtime imports.
- Fixed Qt import regression by correcting QTextDocument import source to PySide6.QtGui.
- Fixed runtime reveal action error by importing sys for platform-specific Finder behavior.

### Tests
- Targeted regression suite: tests/test_gui_main_window.py and tests/test_main_commands.py passed.
- Full suite result: 96 passed.

## [2026-07-08] Milestone 12 - Desktop Polish & Integration (Version 1.2)

### Fixed
- Fixed legacy vault default path and removed deprecated JP Obsidian Vault path literals from code and tracked artifacts.
- Fixed vault integration so GUI and backend modules consistently resolve vault from runtime configuration.
- Fixed email storage false-negative by hardening required-folder matching for spacing/case normalization.
- Fixed incorrect zero knowledge count by aligning GUI runtime to configured vault and count refresh behavior.
- Fixed related-notes panel behavior by wiring real vault retrieval and explicit empty-state text: "No related knowledge found."
- Fixed current customer/project context to auto-update from dropped content and command/result flows.

### Added
- Added command routing split for desktop UI:
  - Explicit knowledge prompts route to vault retrieval.
  - General AI prompts route to Ollama chat.
- Added persistent conversation history panel with user command, AI response, status, markdown, links, and image rendering.
- Added richer drop workflow analysis output: detected type, customer, project, confidence, recommended workflow, and rationale.
- Added production branding asset pipeline with generated PNG/SVG/ICNS logo outputs under app/gui/assets.
- Added packaging scaffolding:
  - packaging/pyinstaller/jpllama_gui.spec
  - scripts/build_macos_app.sh
  - scripts/generate_desktop_branding_assets.py

### Changed
- Updated app version from 1.1 to 1.2 in app/main.py.
- Updated desktop About dialog content to include logo, version, modules, knowledge statistics, application path, vault path, and git revision.
- Updated health output to include explicit output directory status.

### Tests
- Expanded tests/test_gui_main_window.py with general-question routing and customer/project extraction coverage.
- Updated tests/test_main_commands.py version assertion for 1.2.
- Full suite result: 96 passed.

### Validation
- Desktop runtime launch validated with explicit module path configuration.
- PyInstaller bundle build validated successfully; output generated in dist/JPLlamA.app.

## [2026-07-08] Milestone 11 - Desktop Experience (Version 1.1)

### Added
- Added a complete desktop-first GUI redesign in app/gui/main_window.py with retro-futuristic console styling.
- Added natural language command bar with command examples and direct execution flow.
- Added drag-and-drop core workflow for files, folders, mixed bundles, text drops, and dropped images.
- Added automatic content-type detection and smart action suggestions for RFQ, email, presentation, knowledge, image, and document flows.
- Added professional results panel using markdown rendering with status highlighting and clickable file links.
- Added recent activity, recent files, recent searches, and favorite commands sidebar surfaces.
- Added knowledge summary, related notes, current vault, current customer, and current project contextual sidebar surfaces.
- Added progress tracking UI with progress bar, step label, ETA label, and files-processed counter.
- Added post-generation artifact actions: Open, Reveal in Finder, and Copy Path.
- Added interactive searchable help dialog with grouped command examples.
- Added settings dialog with Vault/Ollama/Presenton/theme/export/backup controls.
- Added professional about dialog with logo, version, capabilities, and statistics.
- Added scalable retro-futuristic logo generation and icon wiring for app/window/about usage.

### Changed
- Updated app version from 1.0 to 1.1 in app/main.py.
- Updated GUI tests to include drop classification and smart action suggestion coverage.
- Updated command-level version test expectation to Version 1.1 output.

### Tests
- Updated tests/test_gui_main_window.py with new desktop helper coverage.
- Updated tests/test_main_commands.py for version output assertion.

## [2026-07-08] Milestone 10 - Version 1.0 Final Polish

### Added
- Added startup banner output in app/main.py for clear runtime readiness.
- Added health/system status command route with configuration validation, service reachability checks, test status, and knowledge base statistics.
- Added version command route returning application version, modules, capability count, knowledge statistics, tests, and git revision.
- Added backup commands in app/main.py: backup knowledge, backup vault, backup configuration.
- Added export commands in app/main.py: export lessons, export rfqs, export emails, export presentations, export knowledge.
- Added environment-driven settings loader and configuration validator in app/config.py.

### Changed
- Upgraded help output to dynamic grouped capability rendering including system commands.
- Standardized command response messaging with clear [OK]/[WARN]/[FAIL]/[INFO] status prefixes.
- Improved startup validation failures to return actionable configuration messages before workflow execution.

### Tests
- Expanded tests/test_main_commands.py with health, version, backup, and export command coverage.
- Full suite result for Version 1.0 release: all tests passing.

## [2026-07-08] Milestone 9 - JP Knowledge Assistant

### Added
- Added dynamic Help/What can you do/Commands/Capabilities command route in app/main.py with grouped capability output (Knowledge, Email, RFQ, Presentations, Memory, Search).
- Added lesson-learning remember commands (remember/store/save this lesson) routed through existing memory workflow.
- Added structured lesson markdown persistence in app/memory/store.py with Situation, Decision, Outcome, Customer, Project, Keywords, related notes, and backlinks.
- Added writing-style reference retrieval block in app/main.py for chat and presentation generation flows using prior stored notes.

### Changed
- Updated knowledge retrieval response format in app/main.py to always return Summary, Related knowledge (with relation reasons), Source note paths, and Confidence.
- Added source-specific duplicate detection before storing email, presentation, and RFQ knowledge notes in app/memory/store.py.
- Scoped duplicate checks for domain stores to their target knowledge-base folders to avoid cross-domain false positives.
- Updated Open WebUI watcher integration test to align with no-folder-creation architecture by using existing required email folder.

### Tests
- Added and updated milestone integration tests across:
  - tests/test_knowledge_management.py
  - tests/test_main_commands.py
  - tests/test_memory_store.py
  - tests/test_openwebui_watcher.py
- Full suite result: 79 passed.

## [2026-07-08] Milestone 8 - Knowledge Management

### Added
- Added dedicated knowledge read/search route in app/main.py for vault retrieval questions with ranked hits, summaries, source links, and related-note output.
- Added semantic search trigger route support ("semantic search", "read from vault", and knowledge query patterns).
- Added presentation storage helper in app/memory/store.py targeting folder "Presentation Powerpoint Knowledge Base" with extraction for topic, customer, project, summary, speaker notes, and related presentations.
- Added RFQ storage helper in app/memory/store.py for direct "store this rfq" capture targeting folder "RFQ Contract Review Knowledge Base".
- Added milestone integration tests in tests/test_knowledge_management.py for remember, email/presentation/RFQ storage, vault read, semantic search, and related note retrieval.

### Changed
- Enforced permanent folder ownership rule in storage workflows: JPLlamA now stores only into existing user folders and never creates new folders.
- Updated remember() to choose among existing folders only, add aliases/related/backlink metadata, and deduplicate existing knowledge instead of writing duplicates.
- Updated remember_email_workflow() to store only under "eMails to Remember" and persist required sections (summary, actions, deadlines, entities, related notes).
- Updated remember_rfq_review() to store only under "RFQ Contract Review Knowledge Base" and persist RFQ metadata fields.
- Extended app/obsidian/client.py search result payload to include aliases/backlinks/related/title for improved related-note retrieval and rendering.

### Tests
- Ran milestone suite:
  - tests/test_memory_store.py
  - tests/test_main_commands.py
  - tests/test_rfq_workflow.py
  - tests/test_obsidian_client.py
  - tests/test_knowledge_management.py
- Result: 38 passed.

## [2026-07-07] Apple Notes Migration Engine Hardening

### Added
- Added dedicated migration engine pipeline in app/obsidian/apple_notes_migration.py via run_apple_notes_migration_engine():
  - Stage 1: Apple Notes migration (ignore import hierarchy, classify by semantic meaning, move notes).
  - Stage 2: semantic organizer run after migration completes.
- Updated app/main.py and scripts/run_apple_notes_migration.py to execute migration-first pipeline for Apple Notes commands.
- Added tests for migration engine sequencing and import-source label handling in tests/test_apple_notes_migration.py.

### Changed
- Hardened organizer customer normalization in app/obsidian/organizer.py so import-source names like "Apple"/"Apple Notes" are never treated as customer entities.

### Tests
- Updated tests/test_main_commands.py for the migration engine command route output.

## [2026-07-07] RFQ Rule-Pack Expansion

### Added
- Expanded RFQ country-specific baseline rule packs in [app/rfq/workflow.py](app/rfq/workflow.py) for:
  - Local entity/license/sponsor mandatory clauses (no-go).
  - Tax gross-up/withholding (WHT/Zakat) burden-shift clauses.
  - Sanctions/export-control strict indemnity clauses (no-go).
- Added regression coverage in [tests/test_rfq_workflow.py](tests/test_rfq_workflow.py) for legal/tax/compliance detection and approvals routing.

## [2026-07-07] Obsidian Reliability Milestone

### Added
- Organizer execution modes in app/obsidian/organizer.py: dry-run, analyze, organize, repair.
- Import lock protection for organizer write modes using vault lock files (.import.lock, import.lock, .obsidian-import.lock).
- Non-destructive backup snapshots for organizer content rewrites under Archive/OrganizerBackups/<run-id>/.
- Original filename/path preservation fields in frontmatter for moved notes.
- New index pages for RFQ and Emails with managed-block refresh.
- CLI support for organizer modes in app/main.py and scripts/run_obsidian_organizer.py.

### Changed
- Obsidian search scoring in app/obsidian/client.py now includes title, aliases, folder, backlinks, related links, and path matches.
- Obsidian search now ignores attachment/resource/media trees consistently.
- Organizer now preserves searchability for renamed notes through aliases and original metadata fields.

### Tests
- Expanded tests/test_obsidian_organizer.py for dry-run, repair, import lock, alias/original path preservation, and RFQ/Emails index refresh.
- Expanded tests/test_obsidian_client.py for title/alias/backlink/folder matching and ignored resource trees.
- Expanded tests/test_main_commands.py for organizer mode parsing and import lock safe exit.

## [2026-07-07] RFQ Review Workflow Milestone

### Added
- Dedicated RFQ workflow module in app/rfq/workflow.py and app/rfq/models.py.
- RFQ command coverage for: review this rfq, review this tender, red flags as usual, assess this contract, review this bid.
- Multi-format staged RFQ processing support for text/email, PDF, DOCX, XLSX, PPTX, ZIP, and mixed bundles.
- Timeout-aware chunked processing with partial review reporting.
- Explicit risk classification and outside-baseline detection for terms-switch-off and liability/surcharge risks.
- JP-style RFQ output generation to Markdown and DOCX with 3 tables and sign-off gate.
- RFQ review persistence in Obsidian via remember_rfq_review() and Index/RFQ Reviews.md updates.
- New RFQ workflow tests in tests/test_rfq_workflow.py.

### Changed
- app/main.py RFQ route now executes permanent workflow instead of one-off RFQ prompt response.
- app/main.py RFQ context helper now includes prior contracts and action/decision history sections.
- app/memory/__init__.py exports RFQ persistence helper.

## [2026-07-07] Backlog Completion Pass

### Added
- Open WebUI upload watcher in [app/email/openwebui.py](app/email/openwebui.py) with CLI runner [scripts/watch_openwebui_uploads.py](scripts/watch_openwebui_uploads.py).
- Parallel vault index builder in [app/obsidian/indexer.py](app/obsidian/indexer.py) with CLI runner [scripts/build_vault_index.py](scripts/build_vault_index.py).
- Action exporter to JSON/CSV in [app/obsidian/actions_exporter.py](app/obsidian/actions_exporter.py) with CLI runner [scripts/export_actions.py](scripts/export_actions.py).
- New tests:
  - [tests/test_obsidian_indexer.py](tests/test_obsidian_indexer.py)
  - [tests/test_actions_exporter.py](tests/test_actions_exporter.py)
  - [tests/test_openwebui_watcher.py](tests/test_openwebui_watcher.py)

### Changed
- Further customer/project normalization cleanup in [app/obsidian/organizer.py](app/obsidian/organizer.py) to reduce noisy labels.
- Updated user docs in [docs/email_rfq_usage.md](docs/email_rfq_usage.md) with watcher/index/export commands.
- Closed remaining TODO items in [TODO.md](TODO.md).

## [2026-07-07] Full-Vault Organizer Rebuild

### Added
- Strict markdown-only organizer traversal with ignored attachment/resource trees in [app/obsidian/organizer.py](app/obsidian/organizer.py).
- Link/backlink extraction for graph-aware enrichment and reporting in [app/obsidian/organizer.py](app/obsidian/organizer.py).
- New organizer tests for attachment safety and DP World normalization in [tests/test_obsidian_organizer.py](tests/test_obsidian_organizer.py).

### Changed
- Improved classification signals using title, aliases, summary, frontmatter, content, folder, links, backlinks, customer, project, company, people, technology, meeting, confidence.
- Improved customer normalization with canonical DP World mapping.
- Improved duplicate and review detection quality.
- Improved generated summaries, aliases, tags, indexes, and managed related backlinks.
- Expanded organizer report with richer knowledge graph statistics and improvement estimate.

### Validation
- Tests: 28 passed.
- Full imported vault organizer run completed with report generated at /Users/jeanpierrelang/JP Obsidian Vault/Archive/organizer_report.json.

## [2026-07-07] TODO Completion Pass

### Added
- RFQ workflow coverage and command-level integration tests in [tests/test_main_commands.py](tests/test_main_commands.py).
- Ollama retry tests in [tests/test_ollama_client.py](tests/test_ollama_client.py).
- Presenton retry test updates in [tests/test_presenton_client.py](tests/test_presenton_client.py).
- Usage and troubleshooting guide in [docs/email_rfq_usage.md](docs/email_rfq_usage.md).

### Changed
- Added retry/backoff and timeout controls in [app/ollama/client.py](app/ollama/client.py) and [app/presenton/client.py](app/presenton/client.py).
- Added timeout/retry CLI options and structured workflow logs in [app/main.py](app/main.py).
- Improved presentation retrieval ranking with sidecar metadata support in [app/main.py](app/main.py).
- Improved email entity/action extraction and deadline normalization in [app/email/parsers.py](app/email/parsers.py).
- Extended email entity model for email addresses, organizations, and person confidence in [app/email/models.py](app/email/models.py).
- Added richer workflow context rendering in [app/email/workflow.py](app/email/workflow.py).

### Tests
- Test result after this pass: 26 passed.

### Runtime Validation
- Email workflow command route validated end-to-end.
- RFQ route validated with timeout/retry CLI controls and graceful Ollama-unavailable handling.

## [2026-07-07] Milestone 4 - Digital Employee

### Added
- New email workflow orchestrator in app/email/workflow.py.
- Email domain objects for entities, action extraction, and workflow result in app/email/models.py.
- Email parser support for:
  - .eml files
  - .msg files (optional, requires extract-msg)
  - copied/raw email text
  - uploaded file path parsing
- Entity detection from emails:
  - customer
  - project
  - meeting
  - action items
  - deadlines
  - people
- Action extraction from emails:
  - To Do
  - Deadlines
  - Follow-ups
  - Risks
  - Decisions
- Memory search helper in app/memory/store.py.
- Email remember workflow in app/memory/store.py with:
  - markdown email note generation
  - related note links
  - email index update (Index/Emails.md)
  - backlink update on related notes
- Main command additions in app/main.py:
  - remember this email
  - store this email
  - save email
  - process email / analyze email / summarize email
  - RFQ commands: review this rfq / review rfq

### Changed
- app/main.py now routes dedicated email and RFQ workflows before general planner flow.
- Summary context helpers were generalized to reduce duplication.
- Logging initialization added in app/main.py.

### Tests
- Added/updated tests:
  - tests/test_email_parser.py
  - tests/test_main_commands.py
  - tests/test_memory_store.py
- Test result: 18 passed.

### Runtime Validation
- app.main run executed successfully through routing.
- Local Ollama endpoint was unavailable at runtime and returned a handled error.
