# Email and RFQ Usage

## Email Processing

### Process an .eml file
```bash
python -m app.main "process email /path/to/message.eml"
```

### Process a .msg file
```bash
python -m app.main "process email /path/to/message.msg"
```

If .msg parsing is unavailable, install optional support:
```bash
pip install extract-msg
```

### Process copied email text
```bash
python -m app.main "process email From: ceo@example.com\nSubject: Weekly Update\n\nPlease send the latest timeline by July 20, 2026."
```

### Open WebUI uploads
When Open WebUI provides a local file path after upload, pass that path directly:
```bash
python -m app.main "process email /path/from/open-webui/upload/message.eml"
```

## Remember Email
Supported commands:
- remember this email
- store this email
- save email

Example:
```bash
python -m app.main "remember this email From: lead@example.com\nSubject: Contract Decision\n\nDecision: approved option A by July 25, 2026."
```

This stores:
- markdown note in Meetings folder
- related note links
- Index/Emails.md entry
- backlinks on related notes

## RFQ Mode

### Review RFQ
```bash
python -m app.main "review this rfq ACME cloud migration response"
```

Also supported:
- review this tender ...
- red flags as usual ...
- assess this contract ...
- review this bid ...

RFQ mode automatically searches:
- previous RFQs
- similar customers
- prior contracts
- action/decision history
- presentations in output
- memory hits
- related notes

RFQ mode automatically processes:
- email body text
- PDF, DOCX, XLSX, PPTX, ZIP bundles
- comments/internal notes from OOXML packs when present
- mixed submissions with many attachments

Outputs:
- Markdown report in output/
- DOCX report in output/
- Obsidian RFQ note + Index/RFQ Reviews.md entry

Large-file strategy:
- first pass classification and annex ranking
- second pass chunked high-risk clause extraction
- third pass final report tables
- timeout-safe partial report if full pack cannot finish in budget
- dense XLSX annex parsing includes shared strings + worksheet row extraction for pricing matrices

## Runtime Troubleshooting

### Ollama unavailable
Typical error:
- Unable to reach Ollama at http://127.0.0.1:11434

Checks:
1. Start Ollama locally.
2. Confirm the URL in app/config.py.
3. Use timeout/retry CLI options while validating:
```bash
python -m app.main "review this rfq ..." --ollama-timeout 10 --ollama-retries 1
```

### Presenton unavailable
Checks:
1. Confirm Presenton service is running.
2. Verify URL and credentials in app/config.py.
3. Tune timeout/retries:
```bash
python -m app.main "Build me a 3 slide executive presentation explaining Ollama." --presenton-timeout 30 --presenton-retries 1
```

## Open WebUI Upload Watcher

Process uploads automatically and remember them as email notes.

One scan:
```bash
PYTHONPATH=. python scripts/watch_openwebui_uploads.py --uploads-dir /path/to/openwebui/uploads --once
```

Continuous watcher:
```bash
PYTHONPATH=. python scripts/watch_openwebui_uploads.py --uploads-dir /path/to/openwebui/uploads --interval 10
```

## Obsidian Import Lock Helper

Use lock files to ensure organizer write modes do not run while imports are active.

Set lock before import:
```bash
PYTHONPATH=. python scripts/obsidian_import_lock.py --vault "/path/to/vault" --set --source apple-notes-import
```

Check lock status:
```bash
PYTHONPATH=. python scripts/obsidian_import_lock.py --vault "/path/to/vault" --status
```

Clear lock after import completes:
```bash
PYTHONPATH=. python scripts/obsidian_import_lock.py --vault "/path/to/vault" --clear
```

## Background Vault Index Builder

Build a large-vault JSON index in parallel.

```bash
PYTHONPATH=. python scripts/build_vault_index.py --vault "/path/to/vault" --workers 8
```

## Action Export (CSV/JSON)

Export actions from notes to JSON and CSV.

```bash
PYTHONPATH=. python scripts/export_actions.py --vault "/path/to/vault" --output-dir output
```
