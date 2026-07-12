from __future__ import annotations

import json
from pathlib import Path

from app.intelligence.knowledge_library import ensure_system_library


def test_system_folder_and_folder_map_created(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    root = ensure_system_library(vault)

    assert root.name == "_JPLlamA"
    folder_map_md = root / "Knowledge Library" / "Folder Map.md"
    folder_map_json = root / "Knowledge Library" / "Folder Map.json"
    assert folder_map_md.exists()
    assert folder_map_json.exists()

    text = folder_map_md.read_text(encoding="utf-8")
    for folder in (
        "eMails to Remember",
        "PPTX to Remember",
        "RFQ Contract Review Knowledge Base",
        "Presentation Powerpoint Knowledge Base",
        "DP World",
        "Agility Backup",
        "Cargo Partner",
        "CIQ AWK recovery",
    ):
        assert folder in text

    payload = json.loads(folder_map_json.read_text(encoding="utf-8"))
    names = {item["folder"] for item in payload.get("folders", [])}
    assert "RFQ Contract Review Knowledge Base" in names
    assert "Presentation Powerpoint Knowledge Base" in names
