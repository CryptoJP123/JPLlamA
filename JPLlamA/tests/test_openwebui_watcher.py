from __future__ import annotations

from pathlib import Path

from app.email.openwebui import OpenWebUIUploadWatcher
from app.obsidian.client import ObsidianClient, ObsidianConfig


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_openwebui_watcher_processes_new_upload_once(tmp_path: Path):
    vault = tmp_path / "vault"
    uploads = tmp_path / "uploads"
    state = tmp_path / "state" / "watcher.json"
    vault.mkdir()
    (vault / "eMails to Remember").mkdir(parents=True)
    uploads.mkdir()

    _write(
        uploads / "mail.eml",
        "From: ceo@example.com\nSubject: Weekly update\n\nPlease send report by 2026-07-20.",
    )

    watcher = OpenWebUIUploadWatcher(uploads, state)
    obsidian = ObsidianClient(ObsidianConfig(vault_path=vault))

    first = watcher.run_once(obsidian=obsidian, vault_path=vault)
    second = watcher.run_once(obsidian=obsidian, vault_path=vault)

    assert first.processed == 1
    assert second.processed == 0
    assert second.skipped >= 1
    assert list((vault / "eMails to Remember").glob("*.md"))
