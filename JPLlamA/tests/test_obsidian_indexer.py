from __future__ import annotations

import json
from pathlib import Path

from app.obsidian.indexer import build_vault_index


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_vault_index_ignores_attachments_and_writes_json(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault / "Projects" / "roadmap.md", "# Roadmap\n\nProject planning summary.")
    _write(vault / "attachments" / "ignored.md", "Should be ignored due to folder")

    output = tmp_path / "out" / "index.json"
    result = build_vault_index(vault, output_path=output, workers=2)

    assert result.notes_indexed == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["counts"]["notes"] == 1
    assert payload["notes"][0]["path"].endswith("Projects/roadmap.md")
