# ARCHITECTURE

## Principles
- Keep the existing architecture and routing model.
- Add capability through narrow workflow modules.
- Keep markdown-based Obsidian interoperability first-class.
- Folder ownership is permanently user-managed: JPLlamA must never create, rename, reorganize, or delete user folders.
- Knowledge responses must be evidence-first: summary, related links, source paths, and confidence are returned from stored notes only.
- Desktop UX redesign is frontend-only: GUI may add orchestration surfaces, but backend workflows, data stores, and folder philosophy remain unchanged.

## Runtime Dependency Model (Version 1.5)
- Required for baseline operation:
  - Vault/Obsidian filesystem path (read/search/store)
  - Ollama service (general Q&A and generation)
  - Presenton service (presentation generation route)
- Optional by workflow/context:
  - Docker runtime (required only when Presenton deployment is container-backed)
  - Open WebUI service (optional watcher integration only; not required for current core GUI command routing)
- Service states are normalized and surfaced as:
  - connected
  - busy
  - waiting
  - unavailable
  - error
  - disconnected
- GUI service monitor now exposes, per service:
  - current status
  - current stage
  - last update age
  - helpful runtime message

## Current High-Level Flow
1. CLI request enters app/main.py.
2. Command routing chooses one of:
   - remember workflow
   - obsidian organizer workflow
   - email workflow
   - RFQ workflow
   - planner -> presentation/chat workflow
3. Retrieval is performed against Obsidian markdown notes.
4. Context summaries are injected into Ollama prompts.
5. Optional output artifacts are saved (presentations, notes, reports).

## Components

### app/main.py
- Command detection and workflow orchestration.
- Shared context-build helpers.
- Route-specific runtime behavior.
- Dynamic capability help route for Help/What can you do/Commands/Capabilities.
- Startup banner and polished status messaging for command workflows.
- Health and version command routes for operational visibility and release diagnostics.
- Backup and export command routes for operational data portability.
- Writing-style reference retrieval from prior stored notes for chat and presentation generation.
- Knowledge-query response contract: Summary, Related knowledge, Source note paths, Confidence.

### app/gui/main_window.py
- Primary desktop application shell for Version 1.4.
- Multi-theme command-center UI (Modern, Retro Futuristic, Classic Console) with persisted preference.
- Multiline natural-language command composer with keyboard-first ergonomics and command history navigation.
- Drag-and-drop first interaction surface with mixed file/folder/text/image intake.
- Content-type auto-detection and smart action suggestion layer mapped to existing backend commands.
- Smart workflow analysis includes detected type, customer, project, confidence, recommendation, and rationale.
- Rich conversation rendering with persistent user/assistant history, markdown, status highlighting, progress feedback, clickable artifact links, and controlled autoscroll behavior.
- Non-blocking command processing via QThreadPool/QRunnable worker model for responsive desktop operation.
- Run/Stop control for active command lifecycle with cancellation signaling.
- Live stage/status telemetry with elapsed time, ETA, files processed, job id, and service attribution.
- Timeout watchdog prompts for stalled operations with continue/retry/cancel handling.
- Service monitor surface for Vault/Ollama/Presenton/Knowledge state visibility.
- Service monitor now also reports Open WebUI and Docker runtime state with stage/message metadata.
- Optional developer mode live logs and lightweight runtime diagnostics.
- Left operational sidebar (recent activity/files/searches/favorites) and right knowledge-context sidebar.
- Related-notes panel is retrieval-backed and exposes explicit empty state when no related knowledge is found.
- Interactive help dialog, runtime settings dialog, and professional about dialog.
- Application/window/about logo rendering and icon wiring.
- Uses existing backend workflow modules while routing explicit knowledge queries to vault retrieval, with Ollama fallback when no relevant knowledge is found.

### packaging/pyinstaller/jpllama_gui.spec
- PyInstaller build specification for macOS desktop app bundle generation.
- Includes app metadata, icon wiring, bundle identifier, and bundled desktop assets.

### scripts/build_macos_app.sh
- Packaging helper script that generates branding assets and runs PyInstaller bundle creation.

### scripts/generate_desktop_branding_assets.py
- Generates desktop branding artifacts from the in-app vector construction:
  - PNG sizes for runtime/UI usage
  - SVG source logo
  - iconset + ICNS for macOS bundle packaging

### app/config.py
- Environment-driven configuration loading for local operational deployment.
- Runtime configuration validation for Vault, Ollama, Presenton, optional Open WebUI endpoint, and output directory readiness.

### app/email/parsers.py
- Parses .eml and text-based email payloads.
- Optionally parses .msg when extract-msg is installed.
- Produces summaries, keyword tags, entity detection, and action extraction.

### app/email/workflow.py
- End-to-end email pipeline:
  - parse
  - summarize/tags
  - detect entities
  - extract action tracks
  - search Obsidian
  - search memory
  - build compact response context

### app/rfq/workflow.py
- End-to-end RFQ review pipeline:
  - mode/transport detection from current payload only
  - first pass document classification and structure extraction
  - second pass chunked clause extraction with risk-priority ordering
  - timeout-aware partial completion and pending-item tracking
  - compact retrieval context across RFQ history, contracts, customer notes, presentations, memory, action/decision history, and DP World baseline notes
  - explicit finding classification: No-go, Challenge, Standard, and domain categories (Pricing, Legal, Customs, IT/EDI, Staffing, Operations, etc.)
  - JP-style markdown and DOCX report generation with sign-off gate
  - RFQ review knowledge persistence to Obsidian index/backlinks

### app/email/openwebui.py
- Watches Open WebUI upload folders for new email files.
- Runs email workflow processing once per new file signature.
- Persists processed state and stores resulting email memory notes.
- Optional integration only; not required by current core GUI execution routes.

### app/memory/store.py
- Generic remember() markdown capture.
- search_memory_notes() retrieval.
- remember_email_workflow() for email-specific storage including index and backlinks.
- Knowledge storage now targets existing user-owned folders only and enriches notes with aliases, related links, and backlinks.
- Lesson-learning structured capture (Situation, Decision, Outcome, Customer, Project, Keywords).
- Domain-specific duplicate detection before email/presentation/RFQ storage with linking-first reuse behavior.

### app/obsidian/client.py
- Weighted semantic-lite markdown retrieval with deduplication.
- Recency, folder weighting, tag/summary boosting.
- Reliability coverage for title, aliases, folder, backlinks, related links, and path matching.
- Ignores attachment/resource/media trees so binary support folders are never treated as note sources.

### app/obsidian/indexer.py
- Builds a parallelized background JSON index for very large vaults.
- Stores searchable note metadata and link structure in Archive/vault_index.json.

### app/obsidian/organizer.py
- Mode-based execution:
  - dry-run: plan/report only, no filesystem writes.
  - analyze: classification/report only, no vault mutations.
  - organize: safe markdown-only move/rename + enrichment + indexes + backlinks.
  - repair: rebuild metadata/indexes/backlinks without reorganization moves.
- Import lock awareness for write modes via lock files in vault root.
- Non-destructive write behavior using per-run backups in Archive/OrganizerBackups/.
- Preserves original filename/path aliases when notes are moved or renamed.

### app/obsidian/actions_exporter.py
- Extracts action items (todo, deadlines, follow-ups, risks, decisions) from notes.
- Exports action rows to JSON and CSV for downstream task-system ingestion.

### app/planner/planner.py
- Intent classification for presentation/chat route selection.

### app/presenton/client.py
- Presenton API orchestration for deck generation and output download.
- Provides optional stage callback/cancel hooks for GUI live feedback and stoppable long-running generation flows.

### app/ollama/client.py
- Provides optional streaming status callback/cancel hooks for GUI live feedback during model generation.

## Data Artifacts
- Obsidian notes under configured vault path.
- Email index at Index/Emails.md.
- Presentation files in output/.
- Organizer reports in output/ and vault archive paths.
- Organizer write backups in Archive/OrganizerBackups/<run-id>/.
- Background index at Archive/vault_index.json.
- Action exports at output/actions_export.json and output/actions_export.csv.
- Open WebUI watcher state at output/openwebui_watcher_state.json.

## RFQ Mode
- Trigger phrases: review this rfq, review rfq, review this tender, red flags as usual, assess this contract, review this bid.
- Retrieval targets:
  - previous RFQ notes
  - similar customer notes
  - prior contract notes
  - action/decision history
  - presentation outputs
  - memory hits
  - related notes
- All retrieval channels are summarized into one injected context block.

## Help and Capability Surface
- Supported help triggers:
  - help
  - what can you do
  - commands
  - capabilities
- Help output is generated from the active command mappings so capability text stays synchronized with routing behavior.
- System capability group includes health, version, backup, and export commands so command surface remains discoverable.

## Health and Version Surface
- Health commands:
  - health
  - system status
  - application status
- Version command:
  - version
- Health response reports:
  - Vault availability
  - Presenton/Ollama reachability
  - Test status from last run
  - Knowledge counts (notes, emails, RFQs, presentations, lessons)
  - Last backup and index timestamps

## Backup and Export Surface
- Backup commands:
  - backup knowledge
  - backup vault
  - backup configuration
- Export commands:
  - export lessons
  - export rfqs
  - export emails
  - export presentations
  - export knowledge
- Backup/export artifacts are written to configured output directory and do not modify user taxonomy.

## Knowledge Retrieval Contract
- Knowledge read/search routes always return:
  - Summary
  - Related knowledge (with why-related reason)
  - Source note paths
  - Confidence (high/medium/low)
- Retrieval is constrained to stored vault knowledge; no synthetic unsupported claims are added.

## Writing Style Retrieval
- JPLlamA does not train a model for style adaptation.
- Style alignment is retrieval-based: top prior notes are attached as wording/tone references for generation workflows.

## Large-Pack Strategy
- First pass: classify document types, map structure, detect embedded/comment channels, rank likely annex importance.
- Second pass: process in chunks and prioritize high-risk sections first (liability, terms exclusion, surcharge lock, penalties, VAT/duty, IT/EDI, staffing).
- Third pass: emit final tables and sign-off gate; if timeout budget is exceeded, emit partial report with pending list instead of failing silently.

## Obsidian Reliability Guarantees
- Organizer never processes non-markdown files by default.
- Attachment/resource/media trees are excluded from organization and search indexing.
- Write modes refuse to run when import lock files indicate active import.
- Renamed notes retain discoverability through aliases, original filename, and original path metadata.
- Index/backlink regeneration targets current paths and is available without full reorganization via repair mode.
