from __future__ import annotations

import os
import time
from pathlib import Path

from app.obsidian.client import ObsidianClient, ObsidianConfig


def test_search_ranks_and_deduplicates(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    (vault / "alpha.md").write_text(
        "Ollama deployment strategy\nUse Ollama for local LLM inference.",
        encoding="utf-8",
    )
    (vault / "beta.md").write_text(
        "Ollama deployment strategy\nUse Ollama for local LLM inference.",
        encoding="utf-8",
    )
    (vault / "roadmap.md").write_text(
        "Q3 roadmap\nEnterprise rollout plan with governance.",
        encoding="utf-8",
    )

    client = ObsidianClient(ObsidianConfig(vault_path=vault))
    results = client.search("ollma deploymnt", limit=5)

    assert results
    assert results[0]["path"].endswith("alpha.md") or results[0]["path"].endswith("beta.md")
    assert len(results) == 1
    assert results[0]["score"] > 0


def test_search_uses_tag_and_recency_weighting(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    fresh = vault / "Projects" / "fresh.md"
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_text(
        "---\n"
        "title: \"Fresh Note\"\n"
        "created: 2026-07-07T10:00:00+00:00\n"
        "tags:\n"
        "  - ollama\n"
        "summary: \"Latest ollama rollout status\"\n"
        "---\n\n"
        "Discussed ollama deployment readiness and project milestones.",
        encoding="utf-8",
    )

    old = vault / "Reference" / "old.md"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("Legacy document with ollama references.", encoding="utf-8")
    old_time = time.time() - (3600 * 24 * 500)
    os.utime(old, (old_time, old_time))

    client = ObsidianClient(ObsidianConfig(vault_path=vault))
    results = client.search("ollama rollout", limit=5)

    assert results
    assert results[0]["path"].endswith("fresh.md")
    assert results[0]["summary"]
    assert "ollama" in [tag.lower() for tag in results[0].get("tags", [])]


def test_search_matches_title_aliases_folder_and_backlinks(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    note = vault / "Customers" / "dp-world-summary.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        "title: \"DP World Custodian Data Platform\"\n"
        "aliases:\n"
        "  - DPWorld\n"
        "  - dp world global forwarding\n"
        "backlinks:\n"
        "  - Projects/rfq-evaluation\n"
        "summary: \"Customer password and custodian data requirements\"\n"
        "tags:\n"
        "  - rfq\n"
        "---\n\n"
        "Body for RFQ alignment.",
        encoding="utf-8",
    )

    client = ObsidianClient(ObsidianConfig(vault_path=vault))
    assert client.search("custodian", limit=5)
    assert client.search("DPWorld", limit=5)
    assert client.search("rfq-evaluation", limit=5)
    assert client.search("customers", limit=5)


def test_search_ignores_resource_folders(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    ignored = vault / "attachments" / "hidden-note.md"
    ignored.parent.mkdir(parents=True, exist_ok=True)
    ignored.write_text("password data that should not be indexed", encoding="utf-8")

    visible = vault / "Reference" / "visible-note.md"
    visible.parent.mkdir(parents=True, exist_ok=True)
    visible.write_text("password data should be indexed", encoding="utf-8")

    client = ObsidianClient(ObsidianConfig(vault_path=vault))
    results = client.search("password", limit=10)
    paths = [item["path"] for item in results]

    assert any(path.endswith("visible-note.md") for path in paths)
    assert all(not path.endswith("hidden-note.md") for path in paths)
