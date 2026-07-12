from __future__ import annotations

import sys
from pathlib import Path

from app import main as main_module


def test_remember_this_uses_existing_folder_only(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Reference").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "remember", "this", "Reference", "playbook", "for", "launch", "readiness"])

    main_module.main()
    output = capsys.readouterr().out

    assert "Memory saved successfully" in output
    assert "Folder: Reference" in output
    assert list((vault / "Reference").glob("*.md"))


def test_store_this_email_routes_to_emails_to_remember(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "eMails to Remember").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.main",
            "store",
            "this",
            "email",
            "From: ops@example.com\\nSubject: Weekly Review\\n\\nFollow up with Rezso by July 30, 2026.",
        ],
    )

    main_module.main()
    output = capsys.readouterr().out

    assert "Memory saved successfully" in output
    assert "Folder: eMails to Remember" in output
    assert list((vault / "eMails to Remember").glob("*.md"))


def test_store_this_presentation_uses_presentation_knowledge_base(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Presentation Powerpoint Knowledge Base").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.main",
            "store",
            "this",
            "presentation",
            "Topic: AI Control Tower Customer: Bayer Project: Freight AI Speaker notes: focus on ROI and rollout plan.",
        ],
    )

    main_module.main()
    output = capsys.readouterr().out

    assert "Memory saved successfully" in output
    assert "Folder: Presentation Powerpoint Knowledge Base" in output
    notes = list((vault / "Presentation Powerpoint Knowledge Base").glob("*.md"))
    assert notes
    text = notes[0].read_text(encoding="utf-8")
    assert "topic:" in text.lower()
    assert "speaker_notes:" in text.lower()


def test_store_this_rfq_uses_rfq_knowledge_base(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "RFQ Contract Review Knowledge Base").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.main",
            "store",
            "this",
            "rfq",
            "Customer: Bayer Country: Germany Mode: Ocean No-go liability terms are outside baseline.",
        ],
    )

    main_module.main()
    output = capsys.readouterr().out

    assert "Memory saved successfully" in output
    assert "Folder: RFQ Contract Review Knowledge Base" in output
    assert list((vault / "RFQ Contract Review Knowledge Base").glob("*.md"))


def test_read_from_vault_returns_ranked_links(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Customers").mkdir(parents=True)
    (vault / "Customers" / "paycargo.md").write_text(
        "---\n"
        "title: \"PayCargo Integration\"\n"
        "summary: \"API milestones and rollout constraints\"\n"
        "---\n\n"
        "PayCargo integration roadmap and implementation notes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "read", "from", "vault", "PayCargo", "integration"])

    main_module.main()
    output = capsys.readouterr().out

    assert "Knowledge retrieval" in output
    assert "Ranked notes:" in output
    assert "link:" in output


def test_semantic_search_route_works(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)
    (vault / "Projects" / "customs-rfq.md").write_text(
        "---\n"
        "title: \"RFQ Customs Checklist\"\n"
        "summary: \"Customs obligations and documentation\"\n"
        "---\n\n"
        "Checklist includes importer of record and customs compliance.",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "semantic", "search", "customs", "rfq"])

    main_module.main()
    output = capsys.readouterr().out

    assert "Knowledge retrieval" in output
    assert "Summary:" in output
    assert "Source note paths:" in output
    assert "Confidence:" in output


def test_related_note_retrieval_is_rendered(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)
    (vault / "Projects" / "dpw-lessons.md").write_text(
        "---\n"
        "title: \"DP World Lessons\"\n"
        "summary: \"Lessons learned from implementation\"\n"
        "related:\n"
        "  - \"DPW RFQ 2025\"\n"
        "backlinks:\n"
        "  - \"DPW Customs\"\n"
        "---\n\n"
        "Lessons from DP World implementation and customer approvals.",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "what", "do", "we", "know", "about", "DP", "World?"])

    main_module.main()
    output = capsys.readouterr().out

    assert "Related knowledge:" in output
    assert "DPW RFQ 2025" in output or "DPW Customs" in output


def test_help_command_lists_capabilities(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(sys, "argv", ["app.main", "Help"])

    main_module.main()
    output = capsys.readouterr().out

    assert "KNOWLEDGE" in output
    assert "EMAIL" in output
    assert "RFQ" in output
    assert "PRESENTATIONS" in output
    assert "MEMORY" in output
    assert "SEARCH" in output


def test_remember_this_lesson_stores_structured_fields(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Lessons Learned").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.main",
            "remember",
            "this",
            "lesson",
            "Situation: customs delay Decision: early broker onboarding Outcome: reduced clearance time Customer: Bayer Project: Ocean rollout Keywords: customs, broker, clearance",
        ],
    )

    main_module.main()
    output = capsys.readouterr().out

    assert "Memory saved successfully" in output
    assert "Folder: Lessons Learned" in output
    notes = list((vault / "Lessons Learned").glob("*.md"))
    assert notes
    text = notes[0].read_text(encoding="utf-8")
    assert "## Situation" in text
    assert "## Decision" in text
    assert "## Outcome" in text


def test_duplicate_detection_reuses_existing_note(monkeypatch, capsys, tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Reference").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    remember_payload = "Store this control-tower integration lesson with recurring customs exceptions."

    monkeypatch.setattr(sys, "argv", ["app.main", "remember", "this", remember_payload])
    main_module.main()
    _ = capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["app.main", "remember", "this", remember_payload])
    main_module.main()
    output = capsys.readouterr().out

    assert "Deduplicated: existing note reused" in output
