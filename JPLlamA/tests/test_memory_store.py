from __future__ import annotations

from datetime import datetime
import io
from pathlib import Path
import zipfile

from app.email.workflow import EmailWorkflow
from app.memory.store import (
    ensure_presentation_in_vault,
    remember,
    remember_email_workflow,
    remember_presentation_knowledge,
)
from app.obsidian.client import ObsidianClient, ObsidianConfig


def _minimal_pptx_bytes() -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("[Content_Types].xml", """<?xml version='1.0' encoding='UTF-8'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
    <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
    <Default Extension='xml' ContentType='application/xml'/>
    <Override PartName='/ppt/presentation.xml' ContentType='application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'/>
    <Override PartName='/ppt/slides/slide1.xml' ContentType='application/vnd.openxmlformats-officedocument.presentationml.slide+xml'/>
</Types>
""")
                archive.writestr("_rels/.rels", """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
    <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='ppt/presentation.xml'/>
</Relationships>
""")
                archive.writestr("ppt/presentation.xml", """<?xml version='1.0' encoding='UTF-8'?>
<p:presentation xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships' xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'>
    <p:sldIdLst>
        <p:sldId id='256' r:id='rId1'/>
    </p:sldIdLst>
</p:presentation>
""")
                archive.writestr("ppt/slides/slide1.xml", """<?xml version='1.0' encoding='UTF-8'?>
<p:sld xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships' xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'>
    <p:cSld/>
</p:sld>
""")
        return buffer.getvalue()


def test_remember_creates_markdown_note(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)
    payload = remember(
        "Discussed Ollama rollout plan with customer stakeholders and next steps.",
        vault_path=vault,
        folder="Projects",
        source="user",
        now=datetime(2026, 7, 7, 12, 0, 0),
    )

    note_path = Path(payload["path"])
    assert note_path.exists()
    assert note_path.parent.name == "Projects"
    text = note_path.read_text(encoding="utf-8")
    assert "summary:" in text
    assert "source:" in text
    assert "#" in text
    assert "## Summary" in text
    assert payload["title"]


def test_remember_auto_chooses_ai_folder(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "AI").mkdir(parents=True)
    (vault / "Reference").mkdir(parents=True)
    payload = remember(
        "Evaluate Ollama model routing and AI prompt quality for enterprise use.",
        vault_path=vault,
        source="document",
        now=datetime(2026, 7, 7, 12, 0, 0),
    )

    assert payload["folder"] == "AI"
    assert Path(payload["path"]).parent.name == "AI"


def test_remember_email_workflow_creates_index_and_backlinks(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "eMails to Remember").mkdir(parents=True)
    related = vault / "Projects" / "apollo.md"
    related.parent.mkdir(parents=True, exist_ok=True)
    related.write_text("# Apollo\n", encoding="utf-8")

    obsidian = ObsidianClient(ObsidianConfig(vault_path=vault))
    workflow = EmailWorkflow().process(
        "From: lead@example.com\nSubject: Apollo decision\n\nPlease send update by July 22, 2026.",
        obsidian=obsidian,
    )

    stored = remember_email_workflow(
        workflow,
        vault_path=vault,
        now=datetime(2026, 7, 7, 12, 0, 0),
    )

    note_path = Path(stored["path"])
    assert note_path.exists()
    assert note_path.parent.name == "eMails to Remember"
    assert "## Deadlines" in note_path.read_text(encoding="utf-8")


def test_remember_lesson_writes_structured_sections(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "Lessons Learned").mkdir(parents=True)

    payload = remember(
        "Situation: Bid had customs delays. Decision: involve broker at kickoff. Outcome: reduced handover issues. Customer: DP World Project: Customs rollout Keywords: customs, kickoff, broker",
        vault_path=vault,
        source="lesson",
        now=datetime(2026, 7, 7, 12, 30, 0),
    )

    note_path = Path(payload["path"])
    text = note_path.read_text(encoding="utf-8")
    assert note_path.parent.name == "Lessons Learned"
    assert "## Situation" in text
    assert "## Decision" in text
    assert "## Outcome" in text


def test_remember_email_workflow_deduplicates_existing_note(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "eMails to Remember").mkdir(parents=True)
    existing = vault / "eMails to Remember" / "existing.md"
    existing.write_text(
        "---\nsummary: \"Contract decision approved\"\n---\nSubject: Contract Decision\nDecision approved option A.",
        encoding="utf-8",
    )

    obsidian = ObsidianClient(ObsidianConfig(vault_path=vault))
    workflow = EmailWorkflow().process(
        "From: lead@example.com\nSubject: Contract Decision\n\nDecision approved option A and kickoff next week.",
        obsidian=obsidian,
    )

    stored = remember_email_workflow(workflow, vault_path=vault, now=datetime(2026, 7, 7, 13, 0, 0))
    assert stored.get("deduplicated") == "true"
    assert stored["path"].endswith("existing.md")


def test_remember_presentation_knowledge_stores_original_pptx_link(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "PPTX to Remember").mkdir(parents=True)
    pptx_path = tmp_path / "output" / "quarterly-review.pptx"
    pptx_path.parent.mkdir(parents=True, exist_ok=True)
    pptx_path.write_bytes(_minimal_pptx_bytes())

    stored = remember_presentation_knowledge(
        "topic: Quarterly Review\nslides: 2\nkeywords: finance, risk\npptx: " + str(pptx_path) + "\nsummary: Quarterly review deck",
        vault_path=vault,
        pptx_path=str(pptx_path),
        slide_count=2,
        now=datetime(2026, 7, 7, 14, 0, 0),
    )

    note_path = Path(stored["path"])
    text = note_path.read_text(encoding="utf-8")

    assert note_path.parent.name == "PPTX to Remember"
    assert "## Original PPTX" in text
    assert str(pptx_path) in text
    assert "pptx_path:" in text


def test_ensure_presentation_in_vault_copies_external_file(tmp_path: Path):
    vault = tmp_path / "vault"
    target_folder = vault / "PPTX to Remember"
    target_folder.mkdir(parents=True)

    source = tmp_path / "output" / "generated.pptx"
    source.parent.mkdir(parents=True)
    source.write_bytes(_minimal_pptx_bytes())

    resolved = ensure_presentation_in_vault(str(source), vault_path=vault)

    copied = Path(resolved)
    assert copied.exists()
    assert copied.parent == target_folder
    assert copied.name == "generated.pptx"


def test_ensure_presentation_in_vault_recovers_newest_when_path_missing(tmp_path: Path):
    vault = tmp_path / "vault"
    target_folder = vault / "PPTX to Remember"
    target_folder.mkdir(parents=True)

    first = target_folder / "old.pptx"
    first.write_bytes(_minimal_pptx_bytes())
    second = target_folder / "new.pptx"
    second.write_bytes(_minimal_pptx_bytes())

    resolved = ensure_presentation_in_vault("", vault_path=vault)

    assert resolved == str(second)


def test_ensure_presentation_in_vault_recovers_from_workspace_output(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    target_folder = vault / "PPTX to Remember"
    target_folder.mkdir(parents=True)

    workspace_output = tmp_path / "output"
    workspace_output.mkdir(parents=True)
    recovered = workspace_output / "deck-from-output.pptx"
    recovered.write_bytes(_minimal_pptx_bytes())

    monkeypatch.setattr("app.memory.store.settings.output_dir", workspace_output)

    resolved = ensure_presentation_in_vault("", vault_path=vault)

    copied = Path(resolved)
    assert copied.exists()
    assert copied.parent == target_folder
    assert copied.name == "deck-from-output.pptx"


def test_ensure_presentation_in_vault_ignores_placeholder_preferred_filename(tmp_path: Path):
    vault = tmp_path / "vault"
    target_folder = vault / "PPTX to Remember"
    target_folder.mkdir(parents=True)

    # Placeholder that should never be selected.
    (target_folder / "final.pptx").write_bytes(b"placeholder")

    valid_source = tmp_path / "output" / "real-deck.pptx"
    valid_source.parent.mkdir(parents=True)
    valid_source.write_bytes(_minimal_pptx_bytes())

    resolved = ensure_presentation_in_vault(
        str(valid_source),
        vault_path=vault,
        preferred_filename="final.pptx",
    )

    copied = Path(resolved)
    assert copied.exists()
    assert copied.name == "real-deck.pptx"
