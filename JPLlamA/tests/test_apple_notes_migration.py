from __future__ import annotations

from pathlib import Path

from app.obsidian.apple_notes_migration import (
    AppleNotesMigrator,
    run_apple_notes_migration,
    run_apple_notes_migration_engine,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_migration_moves_apple_notes_and_removes_empty_import_tree(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(
        vault / "Apple Notes" / "DP World" / "ops-note.md",
        "Customer: DP World\nMeeting minutes for implementation workshop.",
    )
    _write(
        vault / "Apple Notes" / "Private" / "goal.md",
        "My personal goal and private planning note.",
    )

    result = run_apple_notes_migration(vault)

    assert result.original_apple_notes_count == 2
    assert result.migrated_notes >= 2
    assert result.notes_renamed >= 0
    assert result.missing_files == 0
    assert not (vault / "Apple Notes").exists()
    assert (vault / "DPWorld" / "ops-note.md").exists()
    assert (vault / "Personal" / "goal.md").exists()


def test_migration_does_not_treat_apple_notes_as_customer_apple(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(
        vault / "Apple Notes" / "General" / "opsx.md",
        "OPSX plan and leadership update for process excellence.",
    )

    result = run_apple_notes_migration(vault)

    assert result.customers_apple_after == 0
    customer_apple = vault / "Customers" / "Apple"
    assert not customer_apple.exists()


def test_migration_ignores_import_source_label_apple_notes(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(
        vault / "Apple Notes" / "General" / "source-labeled.md",
        "Customer: Apple Notes\nImplementation actions and workshop prep.",
    )

    run_apple_notes_migration(vault)

    assert not (vault / "Customers" / "Apple Notes").exists()
    assert not (vault / "Customers" / "Apple").exists()


def test_migration_engine_runs_semantic_organizer_second(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(
        vault / "Apple Notes" / "DP World" / "ops-note.md",
        "Customer: DP World\nMeeting minutes for implementation workshop.",
    )

    result = run_apple_notes_migration_engine(vault, organizer_mode="organize")

    assert result.migration.migrated_notes >= 1
    assert result.organizer_mode == "organize"
    assert Path(result.organizer_report_path).exists()


def test_update_links_tolerates_missing_intermediate_paths(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    existing = vault / "Reference" / "one.md"
    _write(existing, "[[Old/path]] and [x](Old/path.md)")

    migrator = AppleNotesMigrator(vault)
    migrator.move_map = {Path("Old/path.md"): Path("New/path.md")}

    missing = vault / "Reference" / "missing.md"
    migrator._iter_markdown_paths = lambda: iter([missing, existing])  # type: ignore[assignment]
    migrator._update_links()

    updated = existing.read_text(encoding="utf-8")
    assert "[[New/path]]" in updated
    assert "](New/path.md)" in updated


def test_migration_removes_empty_customers_apple_folder(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Customers" / "Apple").mkdir(parents=True, exist_ok=True)

    run_apple_notes_migration(vault)

    assert not (vault / "Customers" / "Apple").exists()


def test_migration_keeps_customers_apple_for_genuine_apple_inc_notes(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault / "Customers" / "Apple" / "account.md",
        "---\nsource: customer-crm\ncustomer: Apple Inc\n---\n\nCustomer: Apple Inc\nEnterprise account planning.",
    )

    run_apple_notes_migration(vault)

    assert (vault / "Customers" / "Apple").exists()
    assert (vault / "Customers" / "Apple" / "account.md").exists()


def test_migration_is_idempotent_for_already_migrated_source_notes(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault / "Reference" / "stable.md",
        "---\nsource: apple-notes-import\n---\n\nOPSX planning note in final folder.",
    )

    result = run_apple_notes_migration(vault)

    assert result.migrated_notes == 0
    assert (vault / "Reference" / "stable.md").exists()
