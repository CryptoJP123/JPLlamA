from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.main import build_rfq_context
from app.obsidian.client import ObsidianClient, ObsidianConfig
from app.rfq.workflow import RfqWorkflow


def _write_ooxml(file_path: Path, members: dict[str, str]) -> None:
    with ZipFile(file_path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _make_docx(file_path: Path, text: str, comments: str = "") -> None:
    members = {
        "[Content_Types].xml": "<Types/>",
        "word/document.xml": f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
    }
    if comments:
        members["word/comments.xml"] = f"<w:comments><w:comment>{comments}</w:comment></w:comments>"
    _write_ooxml(file_path, members)


def _make_xlsx(file_path: Path, text: str, *, dense_rows: int = 1) -> None:
    shared_strings = [text] + [f"row-{idx}-value" for idx in range(1, dense_rows + 3)]
    sst_items = "".join(f"<si><t>{item}</t></si>" for item in shared_strings)

    rows = ["<row r=\"1\"><c r=\"A1\" t=\"s\"><v>0</v></c></row>"]
    for idx in range(2, dense_rows + 2):
        rows.append(
            f"<row r=\"{idx}\">"
            f"<c r=\"A{idx}\" t=\"s\"><v>{idx % len(shared_strings)}</v></c>"
            f"<c r=\"B{idx}\" t=\"str\"><v>rate</v></c>"
            f"<c r=\"C{idx}\" t=\"str\"><v>origin charge</v></c>"
            f"<c r=\"D{idx}\" t=\"str\"><v>destination charge</v></c>"
            f"<c r=\"E{idx}\" t=\"str\"><v>demurrage</v></c>"
            f"<c r=\"F{idx}\" t=\"str\"><v>detention</v></c>"
            "</row>"
        )

    _write_ooxml(
        file_path,
        {
            "[Content_Types].xml": "<Types/>",
            "xl/sharedStrings.xml": f"<sst>{sst_items}</sst>",
            "xl/worksheets/sheet1.xml": "<worksheet><sheetData>" + "".join(rows) + "</sheetData></worksheet>",
            "xl/comments1.xml": "<comments><commentList><comment><text><t>Note</t></text></comment></commentList></comments>",
        },
    )


def _make_pptx(file_path: Path, text: str) -> None:
    _write_ooxml(
        file_path,
        {
            "[Content_Types].xml": "<Types/>",
            "ppt/slides/slide1.xml": f"<p:sld><p:txBody><a:t>{text}</a:t></p:txBody></p:sld>",
            "ppt/notesSlides/notesSlide1.xml": "<p:notes><a:t>Internal note</a:t></p:notes>",
            "ppt/comments/comment1.xml": "<p:cm><p:t>Comment A</p:t></p:cm>",
        },
    )


def _build_obsidian(vault: Path) -> ObsidianClient:
    (vault / "Projects").mkdir(parents=True, exist_ok=True)
    (vault / "Customers").mkdir(parents=True, exist_ok=True)
    (vault / "Reference").mkdir(parents=True, exist_ok=True)
    (vault / "RFQ Contract Review Knowledge Base").mkdir(parents=True, exist_ok=True)
    (vault / "Projects" / "prior-rfq.md").write_text(
        "summary: Prior RFQ findings on liabilities and service credits.",
        encoding="utf-8",
    )
    (vault / "Customers" / "customer-note.md").write_text(
        "Customer: ACME logistics account with recurrent customs requests.",
        encoding="utf-8",
    )
    (vault / "Reference" / "dpworld-baseline.md").write_text(
        "DP World standard trading conditions apply with country-specific requirements.",
        encoding="utf-8",
    )
    return ObsidianClient(ObsidianConfig(vault_path=vault))


def test_small_rfq_email_review(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    payload = (
        "From: bid@acme.com\n"
        "Subject: RFQ\n\n"
        "Please review this ocean RFQ. Standard trading conditions shall not apply. "
        "Unlimited liability applies and service credits are required."
    )

    result = workflow.process(payload, prompt="review this rfq", obsidian=obsidian, output_dir=tmp_path / "out")

    assert result.transport_mode in {"Ocean", "Mixed"}
    assert any("Outside baseline terms" in item.finding or item.outside_baseline for item in result.table1)
    assert Path(result.markdown_path).exists()
    assert Path(result.docx_path).exists()


def test_large_multi_attachment_rfq_zip(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir()
    _make_docx(attachments_dir / "tender.docx", "Control tower with 24x7 staffing")
    _make_xlsx(attachments_dir / "annex.xlsx", "BAF and EBS locked for 12 months")
    _make_pptx(attachments_dir / "deck.pptx", "EDI implementation and go-live")
    (attachments_dir / "terms.pdf").write_bytes(b"/Type /Page service credits and penalties apply")

    bundle = tmp_path / "rfq-pack.zip"
    with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as archive:
        for child in attachments_dir.iterdir():
            archive.write(child, arcname=child.name)

    result = workflow.process(str(bundle), prompt="review this tender", obsidian=obsidian, output_dir=tmp_path / "out")

    assert len(result.documents) >= 4
    assert any(item.file_type in {"docx", "xlsx", "pptx", "pdf"} for item in result.documents)
    assert result.table2


def test_large_pdf_docx_xlsx_pack(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "big.pdf").write_bytes(b"/Type /Page " + (b"liability and penalty " * 5000))
    _make_docx(pack / "big.docx", "standard terms waived and unlimited liability")
    _make_xlsx(pack / "big.xlsx", "duty vat customs responsibility")

    result = workflow.process(str(pack), prompt="assess this contract", obsidian=obsidian, output_dir=tmp_path / "out")

    assert len(result.documents) == 3
    assert any(item.total_chunks > 1 for item in result.documents)


def test_timeout_handling_marks_partial(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    huge = "\n".join(["liability penalty surcharge customs" for _ in range(20000)])
    result = workflow.process(
        huge,
        prompt="review this bid",
        obsidian=obsidian,
        output_dir=tmp_path / "out",
        timeout_seconds=1,
        chunk_chars=1200,
    )

    assert result.partial_review
    assert result.pending_items
    assert "Partial Review Notice" in result.markdown_report


def test_chunked_processing_records_chunks(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    text = "service credit and liability " * 3000
    result = workflow.process(text, prompt="review this rfq", obsidian=obsidian, output_dir=tmp_path / "out", chunk_chars=1000)

    assert result.documents[0].total_chunks > 2
    assert result.documents[0].chunks_processed >= 1
    assert result.recommendation in {"Bid", "Bid with Conditions", "Do Not Bid"}


def test_dp_world_comparison_and_no_go_detection(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    text = "The supplier standard trading conditions shall not apply and SSL T&C are waived."
    result = workflow.process(text, prompt="red flags as usual", obsidian=obsidian, output_dir=tmp_path / "out")

    assert "DP World baseline" in result.compact_context
    assert any(item.bucket == "No-go" for item in result.table1)
    assert any("Outside baseline terms" in line for line in result.markdown_report.splitlines())


def test_docx_generation_valid_zip(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    result = workflow.process("review terms with penalties", prompt="review this rfq", obsidian=obsidian, output_dir=tmp_path / "out")

    with ZipFile(result.docx_path) as archive:
        assert "word/document.xml" in archive.namelist()


def test_markdown_export_contains_tables(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    result = workflow.process("service credits and customs duty", prompt="review this rfq", obsidian=obsidian, output_dir=tmp_path / "out")
    content = Path(result.markdown_path).read_text(encoding="utf-8")

    assert "Executive Summary" in content
    assert "Table 1" in content
    assert "No-Go" in content
    assert "Commercial Risks" in content
    assert "Operational Challenges" in content
    assert "Contractual Risks" in content
    assert "Questions to Customer" in content
    assert "Questions to Product" in content
    assert "Questions to Legal" in content
    assert "Open Risks" in content
    assert "Recommendation" in content


def test_obsidian_storage_creates_index_and_note(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    result = workflow.process("liability and edi go-live", prompt="review this tender", obsidian=obsidian, output_dir=tmp_path / "out")

    assert result.obsidian_note_path
    assert Path(result.obsidian_note_path).exists()
    assert Path(result.obsidian_note_path).parent.name == "RFQ Contract Review Knowledge Base"


def test_search_reuse_of_prior_rfq_context(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    context = build_rfq_context("review this rfq for acme", obsidian)

    assert "Previous RFQs" in context
    assert "Action and decision history" in context
    assert "Prior contracts" in context


def test_country_baseline_rule_coverage_detects_legal_customs_and_payment_risks(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    text = (
        "Local law and jurisdiction clauses prevail over standard trading conditions. "
        "Incoterm DDP applies with all duties VAT and importer of record obligations on supplier. "
        "Payment terms are 120 days from invoice date."
    )
    result = workflow.process(text, prompt="review this tender", obsidian=obsidian, output_dir=tmp_path / "out")

    assert any(item.bucket == "No-go" and "legal hierarchy" in item.finding.lower() for item in result.table1)
    assert any("incoterm allocation" in item.finding.lower() for item in result.table2)
    assert any("extended payment terms" in item.finding.lower() for item in result.table2)


def test_xlsx_annex_dense_table_extraction_preserves_risk_terms(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    annex = tmp_path / "pricing-annex.xlsx"
    _make_xlsx(annex, "BAF and EBS locked for 12 months", dense_rows=240)

    result = workflow.process(str(annex), prompt="review this rfq", obsidian=obsidian, output_dir=tmp_path / "out")

    assert result.documents
    structure = " ".join(result.documents[0].structure).lower()
    assert "xlsx rows parsed" in structure
    assert any(item.category in {"Pricing", "Customs"} for item in result.table2)


def test_country_specific_legal_tax_and_compliance_rule_coverage(tmp_path: Path):
    vault = tmp_path / "vault"
    obsidian = _build_obsidian(vault)
    workflow = RfqWorkflow()

    text = (
        "In-country license and local sponsor are mandatory for contract award. "
        "Withholding tax and gross-up shall be borne by the service provider. "
        "Supplier provides sanctions indemnity with strict liability for all penalties."
    )
    result = workflow.process(text, prompt="review this tender", obsidian=obsidian, output_dir=tmp_path / "out")

    assert any("local-entity licensing" in item.finding.lower() for item in result.table1)
    assert any("sanctions/export-control indemnity" in item.finding.lower() for item in result.table1)
    assert any("tax gross-up/withholding" in item.finding.lower() for item in result.table2)
    assert "Tax" in result.approvals_required
    assert "Legal" in result.approvals_required
