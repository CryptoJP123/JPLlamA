from __future__ import annotations

import json
from pathlib import Path

from app.obsidian.actions_exporter import export_actions


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_export_actions_writes_json_and_csv(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault / "Meetings" / "email-note.md",
        "\n".join(
            [
                "# Email note",
                "## Actions",
                "### To Do",
                "- Send updated draft",
                "### Deadlines",
                "- 2026-07-20",
                "### Decisions",
                "- Approved scope",
            ]
        ),
    )

    output_dir = tmp_path / "output"
    result = export_actions(vault, output_dir)

    assert result.total_actions == 3
    payload = json.loads((output_dir / "actions_export.json").read_text(encoding="utf-8"))
    assert payload["total_actions"] == 3
    csv_text = (output_dir / "actions_export.csv").read_text(encoding="utf-8")
    assert "action_type" in csv_text
    assert "approved scope" in csv_text.lower()
