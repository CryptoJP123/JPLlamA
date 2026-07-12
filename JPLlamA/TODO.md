# TODO

## Milestone 16 - Workflow Redesign (Version 2.0)
- Completed.
- Reworked knowledge retrieval into find/answer modes with source labeling and internet fallback.
- Fixed presentation delivery so the generated PPTX is verified, copied into output, and surfaced with file actions.
- Redesigned RFQ output into an executive commercial review with recommendation and benchmark sections.
- Updated GUI and CLI outputs to reflect the new assistant behavior.
- Validation completed:
	- Targeted regression suite passed.
	- Full suite passed: 105 tests.

## Milestone 14 - Production Readiness (Version 1.4)
- Completed.
- Added Run/Stop active execution control with safe cancellation and immediate idle-state restore.
- Added live operation-stage stream so users always see current work in progress.
- Added Presenton and Ollama staged live status reporting in GUI worker flow.
- Added vault search staged feedback (vault/Obsidian/memory/related/ranking/context/hit-miss).
- Replaced progress area with expanded production telemetry (stage/service/elapsed/ETA/files/customer/project/job id).
- Added live service monitor for Vault, Ollama, Presenton, and Knowledge with state transitions.
- Added timeout watchdog with Continue/Retry/Cancel handling for stalled operations.
- Added optional developer mode logs and runtime diagnostics.
- Preserved Version 1.3 visual design language and existing backend architecture.
- Validation completed:
	- Full regression suite executed for 1.4 readiness.

## Milestone 13 - Desktop Experience Polish (Version 1.3)
- Completed.
- Rebuilt desktop experience shell to a production-style command-center layout while preserving backend workflows.
- Added theme system (Modern, Retro Futuristic, Classic Console) with persisted user preference.
- Added multiline command input with Ctrl+Enter submission and Alt+Up/Alt+Down history navigation.
- Added non-blocking threaded execution with live progress-phase feedback.
- Improved conversation rendering with role-specific styling, markdown output handling, and autoscroll-follow behavior.
- Improved smart drop analysis, recommendation rationale, and visual drop-success feedback.
- Improved Presenton failure handling with explicit reason/retry/settings guidance.
- Added knowledge-query fallback to Ollama when vault retrieval has no relevant notes.
- Validation completed:
	- Targeted tests: GUI + command routing passed
	- Full test suite: 96 passed

## Milestone 12 - Desktop Polish & Integration (Version 1.2)
- Completed.
- Fixed vault configuration defaults and removed legacy vault hardcoded references.
- Fixed desktop-vault integration consistency across health, memory, knowledge, search, RFQ, email, and presentation command flows.
- Fixed email storage folder detection reliability for existing eMails to Remember vault folder.
- Fixed knowledge-count display pathing so markdown totals use the active configured vault.
- Implemented retrieval-backed related-notes panel and explicit empty-state messaging.
- Added automatic customer/project detection and desktop state updates from drop and command flows.
- Upgraded command interface routing for knowledge-vs-general AI behavior.
- Converted result surface to persistent conversation history.
- Generated logo assets (PNG/SVG/ICNS) and wired icon usage in desktop UI.
- Prepared and validated macOS packaging pipeline with PyInstaller.
- Validation completed:
	- Full test suite: 96 passed
	- Desktop launch smoke validated
	- PyInstaller bundle generation validated

## Milestone 11 - Desktop Experience (Version 1.1)
- Completed.
- Desktop is now the primary professional GUI interface for JPLlamA.
- Added natural language command bar and drag-and-drop-first home workspace.
- Added smart action suggestion workflow for dropped RFQ/email/presentation/knowledge/image/document inputs.
- Added rich result rendering with links, status colors, and artifact actions.
- Added operational sidebars, progress surfaces, interactive help, settings dialog, and about dialog with logo.
- Preserved backend, knowledge storage, and folder ownership architecture.

## Milestone 10 - Version 1.0
- Completed.
- Final polish shipped for startup UX, dynamic help, health/version diagnostics, backup/export commands, and configuration validation.
- Version 1.0 is now in daily-use mode.

## Completed in this pass
- Added permanent RFQ review workflow with staged large-document handling and partial timeout-safe reporting.
- Added RFQ JP-format report output to Markdown and DOCX with sign-off gate.
- Added explicit outside-baseline / no-go detection for switched-off standard terms and liability terms.
- Added RFQ review memory capture in Obsidian with index/backlinks and retrieval re-use.
- Added RFQ workflow test coverage for chunking, timeout handling, mixed attachments, exports, and storage.
- Added dedicated RFQ mode tests for retrieval composition and ordering.
- Added integration-style tests for process email and remember this email commands.
- Improved presentation search ranking to include sidecar metadata files.
- Added safer handling for missing optional extract-msg with explicit install hint.
- Added retry policy for Ollama and Presenton transient failures.
- Added configurable timeout/retry CLI options.
- Added structured logs for workflow stages.
- Increased type precision for context helper structures.
- Added richer entity extraction (email addresses, organizations, person confidence).
- Improved deadline extraction to normalize dates to ISO where parseable.
- Added docs/examples for email and RFQ workflows and troubleshooting.
- Rebuilt Obsidian organizer for full-vault markdown-only processing with ignored attachments/resources.
- Improved organizer classification, normalization, summaries, tags, aliases, links, backlinks, duplicate/review detection, and reporting.
- Executed organizer on full imported vault and generated organizer_report.json.
- Added optional Open WebUI upload watcher for automatic ingestion.
- Added background vault index builder for very large vaults.
- Added action export pipeline to JSON/CSV for downstream task-system integration.
- Improved customer/project normalization filtering for residual noisy labels.
- Completed Obsidian reliability pass with safe organizer modes (dry-run/analyze/organize/repair).
- Added import lock safety for organizer write modes to avoid organizing during active imports.
- Added non-destructive organizer backups and original filename/path preservation metadata.
- Expanded Obsidian search matching coverage (title, aliases, folder, backlinks, related links, path).
- Expanded reliability tests for visibility after move/rename, lock behavior, mode behavior, and index refresh.
- Validated RFQ rule coverage with additional country-baseline legal/customs/payment patterns and tests.
- Improved annex table extraction for high-density XLSX pricing matrices.
- Added import lock helper script for Apple Notes import workflows.
- Added knowledge read/search route with ranked retrieval, source links, and related note surfacing.
- Enforced permanent user-owned folder architecture in memory storage flows (no folder creation).
- Added dedicated storage routes for email, presentation, and RFQ knowledge bases.
- Added deduplication + linking-first behavior for new knowledge notes.
- Added milestone integration tests for remember, email/presentation/RFQ store, read from vault, semantic search, and related note retrieval.
- Added dynamic Help/What can you do/Commands/Capabilities route with grouped capability output.
- Added lesson-learning command support and structured lesson note storage fields.
- Added writing-style reference retrieval from prior RFQ/email/presentation/stored notes for generation workflows.
- Added retrieval response contract fields: Summary, Related knowledge with reasons, Source note paths, Confidence.
- Added duplicate detection before email/presentation/RFQ storage with target-folder scoped checks.
- Expanded integration tests for help, lesson storage, duplicate detection, and writing-style retrieval.
- Updated Open WebUI watcher test setup to align with existing-folder-only storage rule.

## Immediate
- No open immediate build items. Usage feedback now drives future changes.

## Reliability
- No open reliability TODO items for this milestone. Ongoing monitoring continues during regular usage.

## Quality
- No open quality blockers for current milestone.

## Documentation
- Documentation updated for watcher, index builder, and action export usage.

## Backlog
- No remaining tracked TODO actions. Future enhancements will be added as new milestones.
