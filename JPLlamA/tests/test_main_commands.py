from __future__ import annotations

import sys
from pathlib import Path

from app import main as main_module
from app.main import (
    OPEN_WEBUI_REQUIRED,
    build_help_response,
    build_note_summary_context,
    build_runtime_dependency_report,
    build_rfq_context,
    build_writing_style_references,
    parse_organizer_mode,
    parse_remember_command,
    search_presentations,
)


def test_parse_remember_command_detects_supported_command():
    parsed = parse_remember_command("remember email Budget discussion for Q3")
    assert parsed is not None
    assert parsed["source"] == "email"
    assert "Budget discussion" in parsed["text"]


def test_parse_remember_command_detects_store_this_email_phrase():
    parsed = parse_remember_command("store this email Subject: Budget follow-up")
    assert parsed is not None
    assert parsed["source"] == "email"
    assert "Budget follow-up" in parsed["text"]


def test_parse_organizer_mode_detects_tail_mode():
    assert parse_organizer_mode("organize obsidian dry-run") == "dry-run"
    assert parse_organizer_mode("organize vault repair") == "repair"
    assert parse_organizer_mode("organize obsidian") == "organize"


def test_build_note_summary_context_compact_output():
    notes = [
        {
            "folder": "Projects",
            "summary": "Launch update with key milestones and risks.",
            "path": "/tmp/test.md",
        }
    ]

    context = build_note_summary_context(notes)

    assert "Relevant knowledge summaries" in context
    assert "Launch update" in context


def test_build_help_response_contains_all_capability_blocks():
    response = build_help_response()

    assert "KNOWLEDGE" in response
    assert "EMAIL" in response
    assert "RFQ" in response
    assert "PRESENTATIONS" in response
    assert "LESSONS" in response
    assert "SEARCH" in response
    assert "SYSTEM" in response


def test_build_writing_style_references_uses_ranked_notes():
    notes = [
        {
            "folder": "RFQ Contract Review Knowledge Base",
            "title": "RFQ - Bayer Ocean 2026",
            "summary": "Use explicit no-go wording and concise approval gates.",
        },
        {
            "folder": "eMails to Remember",
            "title": "Email - Weekly Follow Up",
            "summary": "Prefer short action-first bullets with clear deadlines.",
        },
    ]

    block = build_writing_style_references("review this rfq", notes)

    assert "Writing style references" in block
    assert "no-go wording" in block


def test_search_presentations_uses_sidecar_metadata(tmp_path: Path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    slide = output_dir / "customer-update.pptx"
    slide.write_text("", encoding="utf-8")
    (output_dir / "customer-update.json").write_text('{"customer":"ACME","topic":"RFQ"}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    hits = search_presentations("acme rfq", limit=5)

    assert hits
    assert "metadata" in hits[0]["summary"]


def test_build_rfq_context_contains_expected_sections(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Customers").mkdir(parents=True)
    (vault / "Customers" / "acme.md").write_text("Customer: ACME RFQ history", encoding="utf-8")

    obsidian = main_module.ObsidianClient(main_module.ObsidianConfig(vault_path=vault))
    context = build_rfq_context("Review this RFQ for ACME", obsidian)

    assert "RFQ workflow context" in context
    assert "Previous RFQs" in context
    assert "Similar customers" in context
    assert "Related presentations" in context
    assert "Memory hits" in context
    assert "Related notes" in context


def test_main_process_email_command_outputs_summary(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.main",
            "process",
            "email",
            "From: ceo@example.com\\nSubject: Q3 Plan\\n\\nPlease send update by 2026-07-20.",
        ],
    )

    main_module.main()
    output = capsys.readouterr().out
    assert "Email processed successfully" in output
    assert "Detected deadlines" in output


def test_main_remember_this_email_creates_note(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "eMails to Remember").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.main",
            "remember",
            "this",
            "email",
            "From: lead@example.com\\nSubject: Contract Decision\\n\\nDecision: approved option A by July 25, 2026.",
        ],
    )

    main_module.main()
    output = capsys.readouterr().out
    assert "Memory saved successfully" in output
    assert "Folder: eMails to Remember" in output
    assert list((vault / "eMails to Remember").glob("*.md"))


def test_main_knowledge_read_route_returns_links(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Customers").mkdir(parents=True)
    (vault / "Customers" / "bayer-notes.md").write_text(
        "---\n"
        "title: \"Bayer Customs\"\n"
        "summary: \"Bayer customs and import process\"\n"
        "related:\n"
        "  - \"RFQ Bayer 2026\"\n"
        "---\n\n"
        "Bayer customs process overview.",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "what", "do", "we", "know", "about", "Bayer?"])

    main_module.main()
    output = capsys.readouterr().out

    assert "Knowledge retrieval" in output
    assert "Mode: Answer" in output
    assert "Source note paths:" in output
    assert "Source note paths:" in output


def test_main_knowledge_find_mode_lists_notes(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Customers").mkdir(parents=True)
    (vault / "Customers" / "acme.md").write_text(
        "---\n"
        "title: \"ACME Notes\"\n"
        "summary: \"ACME contract and timeline details\"\n"
        "---\n\n"
        "ACME contract timeline and review notes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "find", "notes", "about", "ACME"])

    main_module.main()
    output = capsys.readouterr().out

    assert "Mode: Answer" in output
    assert "Answer source: Knowledge" in output
    assert "ACME Notes" in output


def test_main_knowledge_answer_mode_uses_vault_and_ollama(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Customers").mkdir(parents=True)
    (vault / "Customers" / "acme.md").write_text(
        "---\n"
        "title: \"ACME Notes\"\n"
        "summary: \"ACME contract and timeline details\"\n"
        "---\n\n"
        "ACME contract timeline and review notes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)

    class _FakeOllama:
        def __init__(self, _config):
            pass

        def chat(self, **kwargs):
            return "ACME has a contract timeline and review notes." 

    monkeypatch.setattr(main_module, "OllamaClient", _FakeOllama)
    monkeypatch.setattr(sys, "argv", ["app.main", "answer", "from", "vault", "ACME", "contract", "timeline"])

    main_module.main()
    output = capsys.readouterr().out

    assert "Mode: Answer" in output
    assert "ACME has a contract timeline" in output
    assert "Answer source: Knowledge" in output


def test_main_knowledge_internet_fallback_labels_source(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)

    class _FakeOllama:
        def __init__(self, _config):
            pass

        def chat(self, **kwargs):
            return "Web answer."

    monkeypatch.setattr(main_module, "OllamaClient", _FakeOllama)
    monkeypatch.setattr(main_module, "_search_web_sources", lambda _query, limit=3: [{"path": "https://example.com", "folder": "Internet", "summary": "Example result", "snippet": "Example result"}])
    monkeypatch.setattr(sys, "argv", ["app.main", "search", "the", "web", "for", "current", "release", "status"])

    main_module.main()
    output = capsys.readouterr().out

    assert "Source mode: Internet" in output
    assert "https://example.com" in output


def test_search_web_sources_prefers_searxng_json():
    html_response = (
        '<article class="result result-default category-general">'
        '<a href="https://example.com/result" class="url_header" rel="noreferrer">'
        '<div class="url_wrapper"><span class="url_o1"><span class="url_i1">https://example.com</span></span></div>'
        '</a>'
        '<h3><a href="https://example.com/result">Example Result</a></h3>'
        '<p class="content">Example snippet</p>'
        '</article>'
    )

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return html_response.encode("utf-8")

    captured = {}

    def _fake_urlopen(req, timeout=6):
        captured["url"] = req.full_url
        return _FakeResponse()

    main_module.settings.searxng_url = "http://searxng:8080"
    main_module.request.urlopen = _fake_urlopen

    results = main_module._search_web_sources("copilot", limit=3)

    assert captured["url"] == "http://searxng:8080/search"
    assert results
    assert results[0]["folder"] == "SearXNG"
    assert "Example Result" in results[0]["summary"]


def test_needs_web_search_detects_weather_typos_and_web_phrasing():
    assert main_module._needs_web_search("whats the wether like in rust tomorrow?") is True
    assert main_module._needs_web_search("look up the web for rust rain forecast") is True
    assert main_module._needs_web_search("summarize last quarter rfq notes") is False


def test_build_knowledge_read_response_for_weather_uses_web_sources(monkeypatch):
    class _FakeObsidian:
        def search(self, *_args, **_kwargs):
            raise AssertionError("weather prompts should not rely on vault hits")

    monkeypatch.setattr(main_module, "_search_web_sources", lambda _query, limit=3: [
        {"path": "https://weather.example.com", "folder": "SearXNG", "summary": "Weather update: sunny", "snippet": "Weather update: sunny"}
    ])

    class _FakeOllama:
        def __init__(self, _config):
            pass

        def chat(self, **kwargs):
            return "Weather is sunny."

    monkeypatch.setattr(main_module, "OllamaClient", _FakeOllama)

    output = main_module.build_knowledge_read_response(
        "can you search for the weather in Rust, Germany tomorrow?",
        _FakeObsidian(),
        include_web=True,
    )

    assert "Mode: Mixed" in output
    assert "Answer source: Mixed" in output
    assert "weather.example.com" in output


def test_main_organizer_lock_exits_safely(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".import.lock").write_text("busy", encoding="utf-8")
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "organize", "obsidian"])

    main_module.main()
    output = capsys.readouterr().out
    assert "Organizer skipped safely" in output


def test_main_apple_notes_migration_command(monkeypatch, capsys, tmp_path: Path):
    class _FakeMigrationResult:
        original_apple_notes_count = 1
        customers_apple_before = 1
        customers_apple_after = 0
        migrated_notes = 1
        notes_renamed = 0
        missing_files = 0
        total_markdown_before = 2
        total_markdown_after = 2
        customers_created = 1
        projects_created = 0
        meetings_created = 0
        personal_created = 1
        reference_created = 0
        apple_notes_folders_removed = 1
        images_archived = 0
        broken_links = 0
        search_validation = {"OPSX": 1}
        knowledge_graph = {"notes": 2}

    class _FakeEngineResult:
        migration = _FakeMigrationResult()
        organizer_mode = "organize"
        organizer_notes_moved = 3
        organizer_notes_renamed = 1
        organizer_duplicates_found = 0
        organizer_report_path = "Archive/organizer_report.json"

    monkeypatch.setattr(main_module, "run_apple_notes_migration_engine", lambda _vault, organizer_mode="organize": _FakeEngineResult())
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "migrate", "apple", "notes"])

    main_module.main()
    output = capsys.readouterr().out
    assert "Apple Notes migration completed." in output
    assert "Semantic organizer mode:" in output


def test_main_health_command_outputs_system_status(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "eMails to Remember").mkdir(parents=True)
    (vault / "eMails to Remember" / "email.md").write_text("# Email", encoding="utf-8")
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(main_module.settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(main_module, "_service_reachable", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sys, "argv", ["app.main", "health"])

    main_module.main()
    output = capsys.readouterr().out
    assert "System health" in output
    assert "Vault connected" in output
    assert "Ollama reachable" in output


def test_main_version_command_outputs_version(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["app.main", "version"])
    main_module.main()
    output = capsys.readouterr().out
    assert "JPLlamA Version 2.0" in output
    assert "Capabilities:" in output


def test_runtime_dependency_report_marks_openwebui_optional(monkeypatch, tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(main_module, "_service_reachable", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main_module, "_docker_reachable", lambda *_args, **_kwargs: True)

    report = build_runtime_dependency_report()
    names = {name: (required, state) for name, required, state, _detail in report}

    assert names["Vault"][1] == "connected"
    assert names["Ollama"][1] == "OK"
    assert names["Presenton"][1] == "OK"
    assert names["Docker"][1] == "OK"
    assert names["Open WebUI"][1] == "OK"
    assert names["SearXNG"][1] == "OK"
    assert names["Open WebUI"][0] is OPEN_WEBUI_REQUIRED


def test_main_backup_knowledge_command_writes_output(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Reference").mkdir(parents=True)
    (vault / "Reference" / "note.md").write_text("# note", encoding="utf-8")
    output_dir = tmp_path / "output"
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(main_module.settings, "output_dir", output_dir)
    monkeypatch.setattr(sys, "argv", ["app.main", "backup", "knowledge"])

    main_module.main()
    output = capsys.readouterr().out
    assert "Backup completed" in output
    assert list(output_dir.glob("knowledge-backup-*.json"))


def test_main_export_lessons_command_writes_output(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Lessons Learned").mkdir(parents=True)
    (vault / "Lessons Learned" / "lesson.md").write_text("# Lesson", encoding="utf-8")
    output_dir = tmp_path / "output"
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(main_module.settings, "output_dir", output_dir)
    monkeypatch.setattr(sys, "argv", ["app.main", "export", "lessons"])

    main_module.main()
    output = capsys.readouterr().out
    assert "Export completed" in output
    assert list(output_dir.glob("export-lessons-*.json"))
