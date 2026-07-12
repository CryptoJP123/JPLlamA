from __future__ import annotations

from pathlib import Path
import pytest

from app.obsidian.organizer import ObsidianOrganizer, run_obsidian_organizer


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_organizer_moves_and_enriches_notes(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(
        vault / "Apple Notes" / "DP World Logistics Germany B.V. & Co. KG.md",
        "Meeting minutes about cargo terminal logistics at DP World.",
    )
    _write(
        vault / "Apple Notes" / "Project Roadmap Q4.md",
        "Project roadmap and milestone plan for release.",
    )

    result = run_obsidian_organizer(vault)

    assert result.notes_moved >= 2
    assert (vault / "DPWorld").exists()
    assert (vault / "Projects").exists()

    moved_files = list(vault.rglob("*.md"))
    assert any("dpworld" in p.name.lower() or "cargo" in p.read_text(encoding="utf-8", errors="ignore").lower() for p in moved_files)

    note_candidates = [
        p
        for p in moved_files
        if p.name
        not in {
            "Customers.md",
            "Projects.md",
            "Meetings.md",
            "Leadership.md",
            "HiFi.md",
            "AI.md",
            "DPWorld.md",
            "Reference.md",
            "RFQ.md",
            "RFQs.md",
            "Emails.md",
            "Presentations.md",
        }
        and "OrganizerBackups" not in p.as_posix()
    ]
    sample = note_candidates[0].read_text(encoding="utf-8", errors="ignore")
    assert "summary:" in sample
    assert "keywords:" in sample
    assert "confidence:" in sample


def test_organizer_archives_duplicates_and_review_items(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    content = "duplicate note content for archive testing"
    _write(vault / "A" / "dup1.md", content)
    _write(vault / "B" / "dup2.md", content)
    _write(vault / "C" / "tiny.md", "short")

    result = run_obsidian_organizer(vault)

    assert result.duplicates_found >= 1
    assert result.review_items >= 1
    assert (vault / "Archive" / "Duplicates").exists()
    assert (vault / "Archive" / "Review").exists()
    assert (vault / "Archive" / "organizer_report.json").exists()
    assert all(name.lower() != "duplicates" for name, _ in result.top_customers)


def test_organizer_ignores_attachments_and_resources(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(vault / "attachments" / "image.png", "binary")
    _write(vault / "resources" / "photo.jpg", "binary")
    _write(vault / "Apple Notes" / "Meeting.md", "Meeting with customer and action items.")

    result = run_obsidian_organizer(vault)

    assert result.notes_moved >= 1
    assert (vault / "attachments" / "image.png").exists()
    assert (vault / "resources" / "photo.jpg").exists()


def test_organizer_normalizes_dp_world_customer_variants(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(vault / "Apple Notes" / "one.md", "Client: DP World\nMeeting notes with delivery actions and milestone updates for Q3 planning.")
    _write(vault / "Apple Notes" / "two.md", "Customer: DPWorld\nProject status includes budget update and deployment timeline for next sprint.")
    _write(vault / "Apple Notes" / "three.md", "Account: DP World Global Forwarding\nRoadmap details include technology tracks, owners, and decisions.")

    result = run_obsidian_organizer(vault)

    customers = [name for name, _ in result.top_customers]
    assert any(name == "DP World" for name in customers)


def test_organizer_dry_run_makes_no_filesystem_changes(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    original = vault / "Apple Notes" / "Project Roadmap Q4.md"
    _write(original, "Project roadmap and milestone plan for release.")

    result = run_obsidian_organizer(vault, mode="dry-run")

    assert result.mode == "dry-run"
    assert original.exists()
    assert list(vault.rglob("*.md")) == [original]
    assert (vault / "Archive" / "organizer_report.dry-run.json").exists()


def test_organizer_repair_mode_rebuilds_metadata_without_move(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    note = vault / "Reference" / "ops-note.md"
    _write(note, "# Ops Note\n\nDP World customer update and RFQ checkpoint.")

    result = run_obsidian_organizer(vault, mode="repair")

    assert result.mode == "repair"
    assert note.exists()
    assert result.notes_moved == 0
    updated = note.read_text(encoding="utf-8", errors="ignore")
    assert "title:" in updated
    assert "aliases:" in updated
    assert (vault / "Archive" / "organizer_report.repair.json").exists()


def test_organizer_exits_cleanly_when_import_lock_exists(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault / "Apple Notes" / "Meeting.md", "Meeting with customer and action items.")
    _write(vault / ".import.lock", "import in progress")

    with pytest.raises(RuntimeError, match="Import appears active"):
        run_obsidian_organizer(vault, mode="organize")

    analyze_result = run_obsidian_organizer(vault, mode="analyze")
    assert analyze_result.mode == "analyze"


def test_organizer_preserves_original_filename_and_aliases_after_move(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    original_name = "DP World Global Forwarding Meeting Notes.md"
    _write(vault / "Apple Notes" / original_name, "Customer: DP World\nRFQ planning and data review notes.")

    run_obsidian_organizer(vault, mode="organize")

    moved_notes = [
        p
        for p in vault.rglob("*.md")
        if "organizer_report" not in p.name
        and p.name
        not in {"Customers.md", "Projects.md", "Meetings.md", "Leadership.md", "HiFi.md", "AI.md", "DPWorld.md", "Reference.md", "RFQ.md", "RFQs.md", "Emails.md", "Presentations.md"}
        and "OrganizerBackups" not in p.as_posix()
    ]
    assert moved_notes
    text = moved_notes[0].read_text(encoding="utf-8", errors="ignore")
    assert "original_filename:" in text
    assert "original_path:" in text
    assert "DP World Global Forwarding Meeting Notes" in text


def test_organizer_builds_rfq_and_email_indexes_with_current_paths(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(
        vault / "Projects" / "rfq-review.md",
        "---\n"
        "tags:\n"
        "  - rfq\n"
        "source: \"rfq-workflow\"\n"
        "---\n\n"
        "RFQ review body",
    )
    _write(
        vault / "Meetings" / "email-note.md",
        "---\n"
        "tags:\n"
        "  - email\n"
        "source: \"email\"\n"
        "---\n\n"
        "Email body",
    )

    run_obsidian_organizer(vault, mode="repair")

    rfq_index = (vault / "RFQ.md").read_text(encoding="utf-8", errors="ignore")
    email_index = (vault / "Emails.md").read_text(encoding="utf-8", errors="ignore")
    assert "rfq-review" in rfq_index
    assert "email-note" in email_index


def test_organizer_ignores_organizer_backups_tree(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(vault / "Archive" / "OrganizerBackups" / "20260707-000000" / "backup-note.md", "archived backup")
    _write(vault / "Apple Notes" / "real-note.md", "Customer: DP World\nMeeting notes and actions.")

    result = run_obsidian_organizer(vault, mode="analyze")

    assert result.knowledge_graph_stats["notes"] == 1


def test_organizer_update_links_tolerates_missing_note_path(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    organizer = ObsidianOrganizer(vault, mode="organize")
    organizer.move_map = {Path("Apple Notes/old.md"): Path("Reference/new.md")}

    missing = vault / "Reference" / "gone.md"
    organizer._iter_markdown_paths = lambda: [missing]  # type: ignore[assignment]

    organizer._update_links()
