from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape as xml_escape
import io
import logging
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from app.email.parsers import EmailParser
from app.memory.store import remember_rfq_review, search_memory_notes
from app.obsidian.client import ObsidianClient

from .models import RfqDocumentSummary, RfqFinding, RfqReviewResult


logger = logging.getLogger(__name__)


TRANSPORT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "Air": ("airfreight", "air freight", "awb", "iata", "flight"),
    "Ocean": ("ocean", "sea freight", "bl", "bill of lading", "vessel", "container"),
    "Road": ("road", "truck", "trucking", "ftl", "ltl"),
    "Rail": ("rail", "wagon", "intermodal rail"),
    "Customs": ("customs", "clearance", "brokerage", "duty", "vat"),
    "Warehouse": ("warehouse", "storage", "putaway", "pick pack"),
    "4PL": ("4pl", "control tower", "lead logistics provider"),
    "LLP": ("llp", "lead logistics", "orchestration"),
}


RISK_RULES = [
    {
        "pattern": r"(standard trading conditions|standard terms|ssl t&c|country[- ]specific trading conditions).{0,40}(shall not apply|do not apply|excluded|waived|switch off|disapplied)",
        "bucket": "No-go",
        "category": "Legal",
        "severity": "Critical",
        "finding": "Tender switches off our standard trading conditions.",
        "outside_baseline": True,
        "sign_off": "P&L owner; Legal; Commercial",
    },
    {
        "pattern": r"(governing law|jurisdiction|local law).{0,80}(supersede|prevail over|override).{0,80}(standard trading conditions|standard terms)",
        "bucket": "No-go",
        "category": "Legal",
        "severity": "Critical",
        "finding": "Tender legal hierarchy overrides baseline standard terms.",
        "outside_baseline": True,
        "sign_off": "P&L owner; Legal",
    },
    {
        "pattern": r"(unlimited liability|liability.{0,20}unlimited|consequential damages|indirect damages)",
        "bucket": "No-go",
        "category": "Legal",
        "severity": "Critical",
        "finding": "Liability exposure is beyond baseline terms.",
        "outside_baseline": True,
        "sign_off": "P&L owner; Legal",
    },
    {
        "pattern": r"(no surcharge|surcharges?.{0,24}(included|fixed|not recoverable)|all[- ]in rate|baf|ebs|gri|pss).{0,30}(fixed|included|locked)",
        "bucket": "Challenge",
        "category": "Pricing",
        "severity": "High",
        "finding": "Surcharge recovery is constrained or switched off.",
        "outside_baseline": True,
        "sign_off": "Commercial; P&L owner",
    },
    {
        "pattern": r"(service credits|penalt(y|ies)|liquidated damages|missed transit time)",
        "bucket": "Challenge",
        "category": "Operations",
        "severity": "High",
        "finding": "Performance and penalty regime requires pricing and operational validation.",
        "outside_baseline": False,
        "sign_off": "Operations; Commercial",
    },
    {
        "pattern": r"(24x7|24/7|control tower|dedicated staffing|fixed staffing)",
        "bucket": "Challenge",
        "category": "Staffing",
        "severity": "High",
        "finding": "Staffing or control tower obligations are present and require scope validation.",
        "outside_baseline": False,
        "sign_off": "Operations; Commercial",
    },
    {
        "pattern": r"(edi|api integration|system implementation|interface testing|go-live)",
        "bucket": "Challenge",
        "category": "IT / EDI",
        "severity": "Medium",
        "finding": "IT/EDI implementation obligations are present.",
        "outside_baseline": False,
        "sign_off": "IT / EDI",
    },
    {
        "pattern": r"(customs responsibility|importer of record|exporter of record|duty|vat|tax)",
        "bucket": "Challenge",
        "category": "Customs",
        "severity": "Medium",
        "finding": "Customs, duty, or VAT responsibility requires explicit scope confirmation.",
        "outside_baseline": False,
        "sign_off": "Customs; Tax",
    },
    {
        "pattern": r"(incoterm|ddp|dap|fob|cif).{0,120}(all duties|all taxes|vat|importer of record)",
        "bucket": "Challenge",
        "category": "Customs",
        "severity": "High",
        "finding": "Incoterm allocation pushes duty/tax/importer obligations into our scope.",
        "outside_baseline": True,
        "sign_off": "Customs; Tax; Commercial",
    },
    {
        "pattern": r"(withholding tax|wht|gross[- ]up|tax gross up|zakat).{0,160}(shall be borne by|borne by|shall bear|must bear|responsible).{0,80}(supplier|carrier|service provider)",
        "bucket": "Challenge",
        "category": "Tax",
        "severity": "High",
        "finding": "Tax gross-up/withholding obligations shift country-specific tax burden to supplier.",
        "outside_baseline": True,
        "sign_off": "Tax; Finance; Commercial",
    },
    {
        "pattern": r"(local (license|entity|registration)|in[- ]country (license|entity)|national sponsor|local sponsor|branch registration).{0,80}(mandatory|required)",
        "bucket": "No-go",
        "category": "Legal",
        "severity": "Critical",
        "finding": "Tender mandates local-entity licensing/sponsorship conditions outside baseline operating model.",
        "outside_baseline": True,
        "sign_off": "P&L owner; Legal; Commercial",
    },
    {
        "pattern": r"(sanctions|export control|denied party|embargo).{0,120}(indemnif(y|ies)|unlimited|strict liability|all penalties)",
        "bucket": "No-go",
        "category": "Legal",
        "severity": "Critical",
        "finding": "Sanctions/export-control indemnity imposes strict or unlimited legal exposure.",
        "outside_baseline": True,
        "sign_off": "P&L owner; Legal; Compliance",
    },
    {
        "pattern": r"(payment terms?|invoice).{0,40}(90|120|150|180)\s*days",
        "bucket": "Challenge",
        "category": "Pricing",
        "severity": "High",
        "finding": "Extended payment terms materially impact cashflow and pricing assumptions.",
        "outside_baseline": False,
        "sign_off": "Commercial; Finance",
    },
    {
        "pattern": r"(insurance|claims process|dead freight|volume commitment|termination)",
        "bucket": "Standard",
        "category": "Standard",
        "severity": "Medium",
        "finding": "Commercial terms present and should be tracked in bid assumptions.",
        "outside_baseline": False,
        "sign_off": "",
    },
]


ALLOWED_TYPES = {".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".eml", ".msg", ".txt", ".md"}


@dataclass
class _SourceDocument:
    name: str
    source: str
    file_type: str
    size_bytes: int
    text: str
    structure: List[str]


class RfqWorkflow:
    def __init__(self, email_parser: Optional[EmailParser] = None):
        self.email_parser = email_parser or EmailParser()

    def process(
        self,
        payload: str,
        *,
        prompt: str,
        obsidian: ObsidianClient,
        output_dir: Path = Path("output"),
        timeout_seconds: int = 90,
        chunk_chars: int = 6000,
    ) -> RfqReviewResult:
        start = time.monotonic()
        output_dir.mkdir(parents=True, exist_ok=True)

        source_documents = self._collect_documents(payload)
        if not source_documents:
            source_documents = [
                _SourceDocument(
                    name="inline-request.txt",
                    source="inline",
                    file_type="txt",
                    size_bytes=len(payload.encode("utf-8", errors="ignore")),
                    text=payload,
                    structure=["Inline request text"],
                )
            ]

        compact_context = self._build_compact_context(prompt, obsidian)
        all_text = "\n".join([doc.text for doc in source_documents if doc.text]).strip()
        transport_mode = self._detect_transport_mode(all_text)

        doc_summaries: List[RfqDocumentSummary] = []
        findings: List[RfqFinding] = []
        pending_items: List[str] = []

        ranked_docs = sorted(source_documents, key=self._document_priority, reverse=True)
        for doc in ranked_docs:
            elapsed = time.monotonic() - start
            if elapsed >= timeout_seconds:
                pending_items.append(doc.name)
                doc_summaries.append(
                    RfqDocumentSummary(
                        name=doc.name,
                        source=doc.source,
                        file_type=doc.file_type,
                        size_bytes=doc.size_bytes,
                        structure=doc.structure,
                        status="pending-timeout",
                        error="Not processed because global timeout budget was reached.",
                    )
                )
                continue

            chunks = self._chunk_text(doc.text, chunk_chars)
            if not chunks:
                chunks = [""]

            chunk_ranked = sorted(chunks, key=self._chunk_priority, reverse=True)
            max_chunk_budget = max(1, int(timeout_seconds * 5))
            processed = 0
            doc_findings: List[RfqFinding] = []
            for chunk in chunk_ranked:
                if time.monotonic() - start >= timeout_seconds:
                    break
                if processed >= max_chunk_budget:
                    break
                processed += 1
                doc_findings.extend(self._classify_chunk(chunk, source=doc.name))

            findings.extend(doc_findings)
            status = "processed" if processed == len(chunk_ranked) else "partial"
            if status != "processed":
                pending_items.append(doc.name)

            doc_summaries.append(
                RfqDocumentSummary(
                    name=doc.name,
                    source=doc.source,
                    file_type=doc.file_type,
                    size_bytes=doc.size_bytes,
                    structure=doc.structure,
                    text_excerpt=self._clean_excerpt(doc.text[:240]),
                    total_chunks=len(chunk_ranked),
                    chunks_processed=processed,
                    status=status,
                )
            )

        findings = self._dedupe_findings(findings)
        tables = self._build_tables(prompt, findings)
        approvals = self._approvals_from_findings(transport_mode, findings)
        recommendation, recommendation_reason = self._recommendation(findings, bool(pending_items))
        grouped_findings = self._group_findings(findings)
        customer_questions, product_questions, legal_questions = self._questions_from_findings(findings)

        partial_review = bool(pending_items)
        markdown_report = self._render_markdown(
            prompt=prompt,
            transport_mode=transport_mode,
            context=compact_context,
            doc_summaries=doc_summaries,
            grouped_findings=grouped_findings,
            summary_rows=self._summary_table_rows(transport_mode, findings, approvals, recommendation, recommendation_reason),
            customer_questions=customer_questions,
            product_questions=product_questions,
            legal_questions=legal_questions,
            open_risks=self._open_risks(findings, pending_items),
            recommendation=recommendation,
            recommendation_reason=recommendation_reason,
            approvals=approvals,
            partial_review=partial_review,
            pending_items=pending_items,
        )

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = f"rfq-review-{stamp}"
        markdown_path = output_dir / f"{stem}.md"
        docx_path = output_dir / f"{stem}.docx"
        markdown_path.write_text(markdown_report, encoding="utf-8")
        self._write_docx_report(
            docx_path,
            prompt=prompt,
            transport_mode=transport_mode,
            grouped_findings=grouped_findings,
            summary_rows=self._summary_table_rows(transport_mode, findings, approvals, recommendation, recommendation_reason),
            customer_questions=customer_questions,
            product_questions=product_questions,
            legal_questions=legal_questions,
            open_risks=self._open_risks(findings, pending_items),
            recommendation=recommendation,
            recommendation_reason=recommendation_reason,
            approvals=approvals,
            partial_review=partial_review,
            pending_items=pending_items,
        )

        related_paths = self._related_paths_from_context(compact_context)
        obsidian_saved = remember_rfq_review(
            title=f"RFQ Review - {transport_mode} - {datetime.now().strftime('%Y-%m-%d')}",
            summary=f"RFQ review completed with {len(tables[0]) + len(tables[1]) + len(tables[2])} findings.",
            markdown_body=markdown_report,
            tags=["rfq", "review", transport_mode.lower().replace(" ", "-")],
            related_paths=related_paths,
            vault_path=obsidian.config.vault_path,
        )

        return RfqReviewResult(
            transport_mode=transport_mode,
            documents=doc_summaries,
            table1=tables[0],
            table2=tables[1],
            table3=tables[2],
            approvals_required=approvals,
            partial_review=partial_review,
            pending_items=pending_items,
            compact_context=compact_context,
            markdown_report=markdown_report,
            markdown_path=str(markdown_path),
            docx_path=str(docx_path),
            obsidian_note_path=str(obsidian_saved.get("path") or ""),
            recommendation=recommendation,
            recommendation_reason=recommendation_reason,
        )

    def _collect_documents(self, payload: str) -> List[_SourceDocument]:
        raw_payload = payload.strip()
        candidate: Optional[Path] = None
        looks_like_path = (
            "\n" not in raw_payload
            and len(raw_payload) < 1024
            and ("/" in raw_payload or raw_payload.endswith(tuple(ALLOWED_TYPES)))
        )
        if looks_like_path:
            try:
                candidate = Path(raw_payload).expanduser()
            except (OSError, ValueError):
                candidate = None

        if candidate is not None and candidate.exists():
            if candidate.is_dir():
                docs: List[_SourceDocument] = []
                for child in sorted(candidate.rglob("*")):
                    if child.is_file() and (child.suffix.lower() in ALLOWED_TYPES or child.suffix == ""):
                        docs.extend(self._documents_from_file(child))
                return docs
            return self._documents_from_file(candidate)

        return [
            _SourceDocument(
                name="inline-request.txt",
                source="inline",
                file_type="txt",
                size_bytes=len(payload.encode("utf-8", errors="ignore")),
                text=payload,
                structure=["Inline request text"],
            )
        ]

    def _documents_from_file(self, file_path: Path) -> List[_SourceDocument]:
        suffix = file_path.suffix.lower()
        try:
            raw = file_path.read_bytes()
        except Exception:
            raw = b""
        size_bytes = len(raw)

        if suffix == ".zip":
            return self._documents_from_zip(file_path, raw)

        if suffix == ".eml":
            message = self.email_parser.parse_eml_file(file_path)
            lines = [
                f"Subject: {message.subject}",
                f"From: {message.sender}",
                message.body_text or "",
            ]
            if message.attachments:
                lines.append("Attachments:")
                for item in message.attachments:
                    lines.append(f"- {item.filename} ({item.content_type}, {item.size_bytes} bytes)")
            return [
                _SourceDocument(
                    name=file_path.name,
                    source=str(file_path),
                    file_type="eml",
                    size_bytes=size_bytes,
                    text="\n".join(lines).strip(),
                    structure=["Email body", f"Attachment count: {len(message.attachments)}"],
                )
            ]

        if suffix == ".msg":
            message = self.email_parser.parse_msg_file(file_path)
            return [
                _SourceDocument(
                    name=file_path.name,
                    source=str(file_path),
                    file_type="msg",
                    size_bytes=size_bytes,
                    text=f"Subject: {message.subject}\nFrom: {message.sender}\n{message.body_text}",
                    structure=["MSG body", f"Attachment count: {len(message.attachments)}"],
                )
            ]

        text, structure = self._extract_text_by_type(file_path.name, suffix, raw)
        return [
            _SourceDocument(
                name=file_path.name,
                source=str(file_path),
                file_type=suffix.lstrip(".") or "txt",
                size_bytes=size_bytes,
                text=text,
                structure=structure,
            )
        ]

    def _documents_from_zip(self, file_path: Path, raw: bytes) -> List[_SourceDocument]:
        docs: List[_SourceDocument] = []
        try:
            with ZipFile(io.BytesIO(raw)) as archive:
                for name in archive.namelist():
                    if name.endswith("/"):
                        continue
                    suffix = Path(name).suffix.lower()
                    if suffix and suffix not in ALLOWED_TYPES:
                        continue
                    payload = archive.read(name)
                    text, structure = self._extract_text_by_type(name, suffix, payload)
                    docs.append(
                        _SourceDocument(
                            name=f"{file_path.name}:{name}",
                            source=str(file_path),
                            file_type=suffix.lstrip(".") or "txt",
                            size_bytes=len(payload),
                            text=text,
                            structure=["ZIP member"] + structure,
                        )
                    )
        except Exception as exc:
            docs.append(
                _SourceDocument(
                    name=file_path.name,
                    source=str(file_path),
                    file_type="zip",
                    size_bytes=len(raw),
                    text="",
                    structure=[f"ZIP parse error: {exc}"],
                )
            )
        return docs

    def _extract_text_by_type(self, name: str, suffix: str, raw: bytes) -> Tuple[str, List[str]]:
        lower_suffix = suffix.lower()
        if lower_suffix in {".txt", ".md", ""}:
            return raw.decode("utf-8", errors="ignore"), ["Text document"]
        if lower_suffix == ".pdf":
            return self._extract_pdf_text(raw)
        if lower_suffix == ".xlsx":
            return self._extract_xlsx_text(name, raw)
        if lower_suffix in {".docx", ".pptx"}:
            return self._extract_ooxml_text(name, raw)
        if lower_suffix == ".zip":
            return "", ["ZIP container"]
        return raw.decode("utf-8", errors="ignore"), ["Generic binary decode"]

    def _local_name(self, tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    def _parse_shared_strings(self, xml_bytes: bytes) -> List[str]:
        items: List[str] = []
        try:
            root = ET.fromstring(xml_bytes)
        except Exception:
            return items

        for node in root.iter():
            if self._local_name(node.tag) != "si":
                continue
            texts: List[str] = []
            for child in node.iter():
                if self._local_name(child.tag) == "t" and child.text:
                    texts.append(child.text)
            merged = re.sub(r"\s+", " ", " ".join(texts)).strip()
            if merged:
                items.append(merged)
        return items

    def _extract_xlsx_text(self, name: str, raw: bytes) -> Tuple[str, List[str]]:
        structure: List[str] = []
        row_lines: List[str] = []
        parsed_rows = 0
        dense_rows = 0

        try:
            with ZipFile(io.BytesIO(raw)) as archive:
                members = archive.namelist()
                structure.append(f"XLSX members: {len(members)}")
                if "annex" in name.lower() or "pricing" in name.lower() or "rate" in name.lower():
                    structure.append("Annex/pricing workbook detected")

                shared_strings: List[str] = []
                if "xl/sharedStrings.xml" in members:
                    shared_strings = self._parse_shared_strings(archive.read("xl/sharedStrings.xml"))
                    structure.append(f"Shared strings: {len(shared_strings)}")

                sheet_members = [
                    member for member in members if member.startswith("xl/worksheets/") and member.endswith(".xml")
                ]
                comments = [member for member in members if member.startswith("xl/comments")]
                if comments:
                    structure.append(f"Comments/internal notes: {len(comments)}")

                for sheet_member in sheet_members:
                    try:
                        root = ET.fromstring(archive.read(sheet_member))
                    except Exception:
                        continue

                    sheet_name = Path(sheet_member).stem
                    for row in root.iter():
                        if self._local_name(row.tag) != "row":
                            continue
                        cells: List[str] = []
                        for cell in list(row):
                            if self._local_name(cell.tag) != "c":
                                continue
                            ref = str(cell.attrib.get("r") or "")
                            cell_type = str(cell.attrib.get("t") or "")
                            value_text = ""

                            for sub in cell.iter():
                                local = self._local_name(sub.tag)
                                if local == "v" and sub.text:
                                    raw_value = sub.text.strip()
                                    if cell_type == "s":
                                        try:
                                            idx = int(raw_value)
                                            if 0 <= idx < len(shared_strings):
                                                value_text = shared_strings[idx]
                                            else:
                                                value_text = raw_value
                                        except ValueError:
                                            value_text = raw_value
                                    else:
                                        value_text = raw_value
                                    break
                                if local == "t" and sub.text:
                                    value_text = sub.text.strip()

                            value_text = re.sub(r"\s+", " ", value_text).strip()
                            if not value_text:
                                continue
                            cells.append(f"{ref}={value_text}" if ref else value_text)

                        if not cells:
                            continue
                        parsed_rows += 1
                        if len(cells) >= 6:
                            dense_rows += 1
                        row_lines.append(f"{sheet_name}: " + " | ".join(cells[:12]))
                        if parsed_rows >= 1800:
                            break

                structure.append(f"XLSX rows parsed: {parsed_rows}")
                if dense_rows >= 50:
                    structure.append(f"High-density table rows: {dense_rows}")

                if not row_lines:
                    fallback, fallback_structure = self._extract_ooxml_text(name, raw)
                    return fallback, structure + fallback_structure

        except Exception as exc:
            return "", [f"XLSX parse error: {exc}"]

        text = "\n".join(row_lines)
        return text[:180000], structure

    def _extract_pdf_text(self, raw: bytes) -> Tuple[str, List[str]]:
        decoded = raw.decode("latin-1", errors="ignore")
        snippets = re.findall(r"\(([\x20-\x7E]{8,})\)", decoded)
        if not snippets:
            snippets = re.findall(r"[A-Za-z0-9,.;:()\-\s]{30,}", decoded)
        text = "\n".join(snippets)
        pages = max(1, decoded.count("/Type /Page"))
        return text[:120000], [f"Estimated pages: {pages}"]

    def _extract_ooxml_text(self, name: str, raw: bytes) -> Tuple[str, List[str]]:
        parts: List[str] = []
        structure: List[str] = []
        try:
            with ZipFile(io.BytesIO(raw)) as archive:
                members = archive.namelist()
                structure.append(f"OOXML members: {len(members)}")

                text_members = [
                    member
                    for member in members
                    if member.endswith(".xml")
                    and (
                        member.startswith("word/")
                        or member.startswith("ppt/")
                        or member.startswith("xl/")
                    )
                ]

                comments = [member for member in text_members if "comment" in member.lower()]
                if comments:
                    structure.append(f"Comments/internal notes: {len(comments)}")
                embeddings = [member for member in members if "embeddings/" in member.lower()]
                if embeddings:
                    structure.append(f"Embedded files: {len(embeddings)}")

                for member in text_members:
                    try:
                        xml_bytes = archive.read(member)
                    except Exception:
                        continue
                    xml = xml_bytes.decode("utf-8", errors="ignore")
                    chunks = re.findall(r">([^<>]{2,})<", xml)
                    if not chunks:
                        continue
                    joined = " ".join(chunks)
                    cleaned = re.sub(r"\s+", " ", joined).strip()
                    if cleaned:
                        parts.append(cleaned)

        except Exception as exc:
            return "", [f"OOXML parse error: {exc}"]

        return "\n".join(parts)[:180000], structure or ["OOXML text extraction"]

    def _build_compact_context(self, prompt: str, obsidian: ObsidianClient) -> str:
        prior_rfq = obsidian.search(f"rfq tender bid review {prompt}", limit=5)
        customer_notes = obsidian.search(f"customer contract notes {prompt}", limit=5)
        prior_contracts = obsidian.search(f"contract msa terms conditions {prompt}", limit=5)
        action_history = obsidian.search(f"actions decisions approvals risks {prompt}", limit=5)
        baseline_hits = obsidian.search(
            "DP World freight forwarding standard trading conditions country terms liability surcharge recovery",
            limit=5,
        )
        memory_hits = search_memory_notes(prompt, vault_path=obsidian.config.vault_path, limit=5)
        presentations = self._search_presentation_notes(prompt, limit=5)

        blocks = [
            "Compact RFQ context",
            self._render_hit_block("Prior RFQ reviews", prior_rfq),
            self._render_hit_block("Prior customer notes", customer_notes),
            self._render_hit_block("Prior contracts", prior_contracts),
            self._render_hit_block("Action and decision history", action_history),
            self._render_hit_block("Prior presentations", presentations),
            self._render_hit_block("Memory", memory_hits),
            self._render_hit_block("DP World baseline", baseline_hits),
        ]
        return "\n\n".join(blocks)

    def _render_hit_block(self, title: str, hits: Sequence[Dict[str, object]]) -> str:
        lines = [f"{title}:"]
        if not hits:
            lines.append("- none")
            return "\n".join(lines)
        for hit in hits[:5]:
            folder = str(hit.get("folder") or "General")
            summary = str(hit.get("summary") or hit.get("snippet") or "").strip()
            path = str(hit.get("path") or "")
            if summary:
                lines.append(f"- [{folder}] {summary[:160]}")
            if path:
                lines.append(f"  source={path}")
        return "\n".join(lines)

    def _search_presentation_notes(self, query: str, limit: int = 5) -> List[Dict[str, object]]:
        output_dir = Path("output")
        if not output_dir.exists():
            return []

        terms = [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", query) if len(t) > 2]
        results: List[Dict[str, object]] = []
        for candidate in output_dir.glob("**/*"):
            if not candidate.is_file() or candidate.suffix.lower() not in {".pptx", ".pdf", ".md", ".docx"}:
                continue
            name_lower = candidate.name.lower()
            score = sum(name_lower.count(term) for term in terms)
            if terms and score <= 0:
                continue
            results.append(
                {
                    "path": str(candidate),
                    "folder": "Presentations",
                    "summary": f"{candidate.name} (score={score})",
                }
            )
        return results[:limit]

    def _detect_transport_mode(self, text: str) -> str:
        lowered = text.lower()
        scores: Dict[str, int] = {}
        for mode, keywords in TRANSPORT_KEYWORDS.items():
            scores[mode] = sum(lowered.count(keyword) for keyword in keywords)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] == 0:
            return "Mixed"
        if len(ranked) > 1 and ranked[1][1] > 0 and ranked[0][1] <= ranked[1][1] + 1:
            return "Mixed"
        return ranked[0][0]

    def _chunk_text(self, text: str, chunk_chars: int) -> List[str]:
        normalized = text.strip()
        if not normalized:
            return []
        chunks: List[str] = []
        step = max(400, chunk_chars - 800)
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + chunk_chars)
            chunks.append(normalized[start:end])
            start += step
        return chunks

    def _chunk_priority(self, chunk: str) -> int:
        lowered = chunk.lower()
        risk_terms = [
            "liability",
            "penalty",
            "termination",
            "surcharge",
            "baf",
            "ebs",
            "gri",
            "pss",
            "duty",
            "vat",
            "customs",
            "24x7",
            "edi",
            "service credit",
            "incoterm",
            "demurrage",
            "detention",
            "origin charge",
            "destination charge",
            "payment term",
            "annex",
        ]
        return sum(lowered.count(term) for term in risk_terms)

    def _document_priority(self, doc: _SourceDocument) -> int:
        type_weight = {
            "pdf": 5,
            "docx": 6,
            "xlsx": 8,
            "pptx": 4,
            "eml": 3,
            "msg": 3,
            "txt": 2,
            "md": 2,
        }.get(doc.file_type, 1)
        name_score = self._chunk_priority(doc.name)
        if doc.file_type == "xlsx" and re.search(r"annex|pricing|rate", doc.name, flags=re.IGNORECASE):
            name_score += 20
        text_score = self._chunk_priority(doc.text[:2000])
        return type_weight * 10 + name_score + text_score

    def _classify_chunk(self, chunk: str, *, source: str) -> List[RfqFinding]:
        findings: List[RfqFinding] = []
        lowered = chunk.lower()

        for rule in RISK_RULES:
            match = re.search(rule["pattern"], lowered, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            evidence = self._evidence_window(chunk, match.start(), match.end())
            findings.append(
                RfqFinding(
                    bucket=str(rule["bucket"]),
                    category=str(rule["category"]),
                    severity=str(rule["severity"]),
                    finding=str(rule["finding"]),
                    evidence=evidence,
                    source=source,
                    sign_off=str(rule.get("sign_off") or ""),
                    outside_baseline=bool(rule.get("outside_baseline")),
                )
            )

        if "standard trading conditions" in lowered and "apply" in lowered and "shall not" not in lowered:
            findings.append(
                RfqFinding(
                    bucket="Standard",
                    category="Standard",
                    severity="Low",
                    finding="Standard trading conditions appear to remain in force.",
                    evidence=self._clean_excerpt(chunk[:180]),
                    source=source,
                    sign_off="",
                    outside_baseline=False,
                )
            )

        return findings

    def _build_tables(self, prompt: str, findings: List[RfqFinding]) -> Tuple[List[RfqFinding], List[RfqFinding], List[RfqFinding]]:
        no_go = [item for item in findings if item.bucket == "No-go"]
        challenge = [item for item in findings if item.bucket == "Challenge"]
        standard = [item for item in findings if item.bucket == "Standard"]

        request_questions = self._extract_questions(prompt)
        table1: List[RfqFinding] = []
        if request_questions:
            for question in request_questions:
                answer_finding = self._answer_question(question, findings)
                table1.append(answer_finding)
            table1.extend(no_go)
        else:
            table1 = no_go

        return table1, challenge, standard

    def _extract_questions(self, text: str) -> List[str]:
        candidates = [item.strip() for item in re.split(r"[\n\r]+", text) if "?" in item]
        seen: set[str] = set()
        questions: List[str] = []
        for candidate in candidates:
            clean = candidate.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            questions.append(clean[:220])
        return questions[:4]

    def _answer_question(self, question: str, findings: Sequence[RfqFinding]) -> RfqFinding:
        lower = question.lower()
        if "liability" in lower:
            matched = next((item for item in findings if "liability" in item.finding.lower()), None)
            if matched:
                text = "Question answered: liability is outside baseline terms based on tender wording."
                evidence = matched.evidence
                category = "Legal"
                bucket = "No-go"
                sign_off = "P&L owner; Legal"
            else:
                text = "Question captured: no direct liability clause identified in processed chunks."
                evidence = question
                category = "Approvals"
                bucket = "Challenge"
                sign_off = "Legal"
        else:
            text = "Question captured and mapped to findings in this review."
            evidence = question
            category = "Approvals"
            bucket = "Challenge"
            sign_off = ""

        return RfqFinding(
            bucket=bucket,
            category=category,
            severity="High" if bucket == "No-go" else "Medium",
            finding=text,
            evidence=evidence,
            source="request",
            sign_off=sign_off,
            outside_baseline=(bucket == "No-go"),
        )

    def _approvals_from_findings(self, transport_mode: str, findings: Sequence[RfqFinding]) -> List[str]:
        approvals: List[str] = []

        mode_map = {
            "Air": "Global Head of Airfreight",
            "Ocean": "Global Ocean Product",
        }
        if transport_mode in mode_map:
            approvals.append(mode_map[transport_mode])

        for finding in findings:
            if finding.sign_off:
                for part in finding.sign_off.split(";"):
                    item = part.strip()
                    if item and item not in approvals:
                        approvals.append(item)
            category = finding.category
            if category == "IT / EDI" and "IT / EDI" not in approvals:
                approvals.append("IT / EDI")
            if category in {"Customs", "Tax"} and "Customs" not in approvals:
                approvals.append("Customs")
            if category == "Tax" and "Tax" not in approvals:
                approvals.append("Tax")
            if category in {"Operations", "Staffing", "Reporting"} and "Operations" not in approvals:
                approvals.append("Operations")
            if category in {"Pricing", "Approvals"} and "Commercial" not in approvals:
                approvals.append("Commercial")
            if category == "Legal" and "Legal" not in approvals:
                approvals.append("Legal")
            if finding.bucket == "No-go" and "P&L owner" not in approvals:
                approvals.append("P&L owner")

        return approvals

    def _group_findings(self, findings: Sequence[RfqFinding]) -> Dict[str, List[RfqFinding]]:
        buckets = {
            "No-Go": [],
            "Commercial Risks": [],
            "Operational Challenges": [],
            "Contractual Risks": [],
        }
        for item in findings:
            if item.bucket == "No-go":
                buckets["No-Go"].append(item)
            elif item.category in {"Pricing", "Tax", "Customs"}:
                buckets["Commercial Risks"].append(item)
            elif item.category in {"Operations", "Staffing", "IT / EDI"}:
                buckets["Operational Challenges"].append(item)
            else:
                buckets["Contractual Risks"].append(item)
        return buckets

    def _summary_table_rows(
        self,
        transport_mode: str,
        findings: Sequence[RfqFinding],
        approvals: Sequence[str],
        recommendation: str,
        recommendation_reason: str,
    ) -> List[Tuple[str, str]]:
        grouped = self._group_findings(findings)
        return [
            ("Transport mode", transport_mode),
            ("No-Go items", str(len(grouped["No-Go"]))),
            ("Commercial risks", str(len(grouped["Commercial Risks"]))),
            ("Operational challenges", str(len(grouped["Operational Challenges"]))),
            ("Contractual risks", str(len(grouped["Contractual Risks"]))),
            ("Approvals required", "; ".join(approvals) if approvals else "none"),
            ("Recommendation", recommendation),
            ("Rationale", recommendation_reason),
        ]

    def _questions_from_findings(self, findings: Sequence[RfqFinding]) -> Tuple[List[str], List[str], List[str]]:
        customer_questions: List[str] = []
        product_questions: List[str] = []
        legal_questions: List[str] = []

        if any(item.outside_baseline for item in findings):
            customer_questions.append("Can the customer restore baseline trading terms, or confirm the commercial offset for the requested deviations?")

        if any(item.category in {"Pricing", "Tax", "Customs"} for item in findings):
            customer_questions.append("Can the customer confirm which surcharges, duties, VAT, and payment terms are in scope and recoverable?")

        if any(item.category == "Operations" for item in findings):
            product_questions.append("Can Product/Operations confirm service scope, volumes, service-credit exposure, and the operating model required to deliver this bid?")

        if any(item.category in {"Staffing", "IT / EDI"} for item in findings):
            product_questions.append("Can Product confirm staffing, control-tower, EDI, integration, and go-live requirements before pricing?")

        if any(item.category == "Legal" for item in findings):
            legal_questions.append("Can Legal confirm whether liability caps, governing law, sanctions, and indemnity wording are acceptable?")

        if any(item.category == "Tax" for item in findings):
            legal_questions.append("Can Legal and Tax confirm withholding-tax, gross-up, and local registration implications?")

        if not customer_questions:
            customer_questions.append("Can the customer confirm award criteria, scope assumptions, and any deviations from baseline terms?")
        if not product_questions:
            product_questions.append("Can Product confirm the delivery model, SLA assumptions, and any operational constraints?")
        if not legal_questions:
            legal_questions.append("Can Legal confirm the standard contract position and any exceptions that need approval?")

        return customer_questions, product_questions, legal_questions

    def _open_risks(self, findings: Sequence[RfqFinding], pending_items: Sequence[str]) -> List[str]:
        risks: List[str] = []
        for item in findings:
            if item.bucket == "No-go":
                continue
            if item.finding not in risks:
                risks.append(item.finding)
        for item in pending_items:
            risks.append(f"Pending document: {item}")
        return risks[:8]

    def _recommendation(self, findings: Sequence[RfqFinding], partial_review: bool) -> Tuple[str, str]:
        no_go = [item for item in findings if item.bucket == "No-go"]
        commercial = [item for item in findings if item.category in {"Pricing", "Tax", "Customs"}]
        operational = [item for item in findings if item.category in {"Operations", "Staffing", "IT / EDI"}]

        if no_go:
            return (
                "Do Not Bid",
                f"{len(no_go)} no-go clause(s) exceed baseline terms and require legal/commercial exception handling.",
            )
        if partial_review:
            return (
                "Bid with Conditions",
                "The review finished partially, so bid only after the missing items are reviewed and closed.",
            )
        if commercial or operational:
            return (
                "Bid with Conditions",
                "Commercial or operational exceptions are present and should be priced and approved explicitly.",
            )
        return ("Bid", "No material exceptions were identified in the processed content.")

    def _render_findings_rows(self, findings: Sequence[RfqFinding]) -> List[str]:
        lines = ["| Severity | Category | Finding | Evidence | Source | Sign-off |", "|---|---|---|---|---|---|"]
        if not findings:
            lines.append("| Low | Standard | None identified | n/a | system | |")
            return lines

        for item in findings:
            evidence = self._clean_excerpt(item.evidence)
            finding = item.finding
            if item.outside_baseline:
                finding = f"Outside baseline terms: {finding}"
            lines.append(
                f"| {item.severity} ({item.bucket}) | {item.category} | {finding} | {evidence} | {item.source} | {item.sign_off} |"
            )
        return lines

    def _render_markdown(
        self,
        *,
        prompt: str,
        transport_mode: str,
        context: str,
        doc_summaries: Sequence[RfqDocumentSummary],
        grouped_findings: Dict[str, Sequence[RfqFinding]],
        summary_rows: Sequence[Tuple[str, str]],
        customer_questions: Sequence[str],
        product_questions: Sequence[str],
        legal_questions: Sequence[str],
        open_risks: Sequence[str],
        recommendation: str,
        recommendation_reason: str,
        approvals: Sequence[str],
        partial_review: bool,
        pending_items: Sequence[str],
    ) -> str:
        lines: List[str] = []
        lines.append("# RFQ Review")
        lines.append("")
        lines.append("## Executive Summary")
        lines.append(f"- Transport mode detected: {transport_mode}")
        lines.append(f"- Recommendation: {recommendation}")
        lines.append(f"- Rationale: {recommendation_reason}")
        if partial_review:
            lines.append("- Review status: partial review completed; some items remain pending.")
        lines.append("")
        lines.append("## Table 1")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        for metric, value in summary_rows:
            lines.append(f"| {metric} | {value} |")
        lines.append("")
        lines.append("## No-Go")
        lines.extend(self._render_findings_rows(grouped_findings["No-Go"]))
        lines.append("")
        lines.append("## Table 2")
        lines.append("### Commercial Risks")
        lines.extend(self._render_findings_rows(grouped_findings["Commercial Risks"]))
        lines.append("")
        lines.append("## Table 3")
        lines.append("### Operational Challenges")
        lines.extend(self._render_findings_rows(grouped_findings["Operational Challenges"]))
        lines.append("")
        lines.append("## Table 4")
        lines.append("### Contractual Risks")
        lines.extend(self._render_findings_rows(grouped_findings["Contractual Risks"]))
        lines.append("")
        lines.append("## Questions to Customer")
        for question in customer_questions:
            lines.append(f"- {question}")
        lines.append("")
        lines.append("## Questions to Product")
        for question in product_questions:
            lines.append(f"- {question}")
        lines.append("")
        lines.append("## Questions to Legal")
        for question in legal_questions:
            lines.append(f"- {question}")
        lines.append("")
        lines.append("## Open Risks")
        if open_risks:
            for item in open_risks:
                lines.append(f"- {item}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("## Recommendation")
        lines.append(f"{recommendation}")
        lines.append(f"Reason: {recommendation_reason}")
        lines.append("")
        lines.append("## Context")
        lines.append(context)
        lines.append("")
        lines.append("## Document Processing")
        lines.append("| Document | Type | Status | Chunks | Notes |")
        lines.append("|---|---|---|---|---|")
        for doc in doc_summaries:
            notes = "; ".join(doc.structure[:3])
            lines.append(
                f"| {doc.name} | {doc.file_type} | {doc.status} | {doc.chunks_processed}/{doc.total_chunks} | {notes} |"
            )
        lines.append("")
        lines.append("## Sign-off Gate")
        if approvals:
            lines.append("The following approvals are required before quoting:")
            for item in approvals:
                lines.append(f"- {item}")
        else:
            lines.append("No explicit approval gate detected from processed clauses.")

        if partial_review:
            lines.append("")
            lines.append("## Partial Review Notice")
            lines.append("Processing completed in chunks and timed out before all items were completed.")
            for item in pending_items:
                lines.append(f"- Pending: {item}")

        return "\n".join(lines).strip() + "\n"

    def _render_findings_table(self, findings: Sequence[RfqFinding]) -> List[str]:
        lines = ["| Severity | Category | Finding | Evidence | Source | Sign-off |", "|---|---|---|---|---|---|"]
        if not findings:
            lines.append("| Low | Standard | No specific findings detected in processed content. | n/a | system | |")
            return lines

        for item in findings:
            evidence = self._clean_excerpt(item.evidence)
            finding = item.finding
            if item.outside_baseline:
                finding = f"Outside baseline terms: {finding}"
            lines.append(
                f"| {item.severity} ({item.bucket}) | {item.category} | {finding} | {evidence} | {item.source} | {item.sign_off} |"
            )
        return lines

    def _write_docx_report(
        self,
        path: Path,
        *,
        prompt: str,
        transport_mode: str,
        grouped_findings: Dict[str, Sequence[RfqFinding]],
        summary_rows: Sequence[Tuple[str, str]],
        customer_questions: Sequence[str],
        product_questions: Sequence[str],
        legal_questions: Sequence[str],
        open_risks: Sequence[str],
        recommendation: str,
        recommendation_reason: str,
        approvals: Sequence[str],
        partial_review: bool,
        pending_items: Sequence[str],
    ) -> None:
        body_parts: List[str] = []
        body_parts.append(self._docx_paragraph("RFQ Review"))
        body_parts.append(self._docx_paragraph(f"Transport mode detected: {transport_mode}"))
        body_parts.append(self._docx_paragraph(f"Recommendation: {recommendation}"))
        body_parts.append(self._docx_paragraph(f"Rationale: {recommendation_reason}"))

        body_parts.append(self._docx_paragraph("Executive Summary"))
        body_parts.append(self._docx_table([RfqFinding(bucket=metric, category=metric, severity="Low", finding=value, evidence=value, source="system") for metric, value in summary_rows]))

        body_parts.append(self._docx_paragraph("No-Go"))
        body_parts.append(self._docx_table(grouped_findings["No-Go"]))
        body_parts.append(self._docx_paragraph("Commercial Risks"))
        body_parts.append(self._docx_table(grouped_findings["Commercial Risks"]))
        body_parts.append(self._docx_paragraph("Operational Challenges"))
        body_parts.append(self._docx_table(grouped_findings["Operational Challenges"]))
        body_parts.append(self._docx_paragraph("Contractual Risks"))
        body_parts.append(self._docx_table(grouped_findings["Contractual Risks"]))

        body_parts.append(self._docx_paragraph("Questions to Customer"))
        for item in customer_questions:
            body_parts.append(self._docx_paragraph(f"- {item}"))
        body_parts.append(self._docx_paragraph("Questions to Product"))
        for item in product_questions:
            body_parts.append(self._docx_paragraph(f"- {item}"))
        body_parts.append(self._docx_paragraph("Questions to Legal"))
        for item in legal_questions:
            body_parts.append(self._docx_paragraph(f"- {item}"))

        body_parts.append(self._docx_paragraph("Open Risks"))
        for item in open_risks or ["none"]:
            body_parts.append(self._docx_paragraph(f"- {item}"))

        body_parts.append(self._docx_paragraph("Recommendation"))
        body_parts.append(self._docx_paragraph(recommendation))
        body_parts.append(self._docx_paragraph(recommendation_reason))

        body_parts.append(self._docx_paragraph("Sign-off Gate"))
        if approvals:
            for item in approvals:
                body_parts.append(self._docx_paragraph(f"- {item}"))
        else:
            body_parts.append(self._docx_paragraph("- No explicit sign-off gate detected."))

        if partial_review:
            body_parts.append(self._docx_paragraph("Partial review notice: processing timed out for some items."))
            for item in pending_items:
                body_parts.append(self._docx_paragraph(f"- Pending: {item}"))

        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{''.join(body_parts)}<w:sectPr/></w:body>"
            "</w:document>"
        )

        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        )

        rels_root = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>"
        )

        rels_document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
        )

        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", rels_root)
            archive.writestr("word/document.xml", document_xml)
            archive.writestr("word/_rels/document.xml.rels", rels_document)

    def _docx_paragraph(self, text: str) -> str:
        escaped = xml_escape(text)
        return (
            "<w:p><w:r><w:t xml:space=\"preserve\">"
            + escaped
            + "</w:t></w:r></w:p>"
        )

    def _docx_table(self, findings: Sequence[RfqFinding]) -> str:
        headers = ["Severity", "Category", "Finding", "Evidence", "Source", "Sign-off"]
        rows: List[List[str]] = [headers]
        if findings:
            for item in findings:
                finding = item.finding
                if item.outside_baseline:
                    finding = f"Outside baseline terms: {finding}"
                rows.append(
                    [
                        f"{item.severity} ({item.bucket})",
                        item.category,
                        finding,
                        self._clean_excerpt(item.evidence),
                        item.source,
                        item.sign_off,
                    ]
                )
        else:
            rows.append(["Low", "Standard", "No specific findings detected.", "n/a", "system", ""])

        xml_rows = []
        for row in rows:
            cells = []
            for cell in row:
                cells.append(
                    "<w:tc><w:p><w:r><w:t xml:space=\"preserve\">"
                    + xml_escape(cell)
                    + "</w:t></w:r></w:p></w:tc>"
                )
            xml_rows.append("<w:tr>" + "".join(cells) + "</w:tr>")
        return "<w:tbl>" + "".join(xml_rows) + "</w:tbl>"

    def _dedupe_findings(self, findings: Sequence[RfqFinding]) -> List[RfqFinding]:
        seen: set[Tuple[str, str, str]] = set()
        deduped: List[RfqFinding] = []
        for item in findings:
            key = (
                item.bucket.lower(),
                item.category.lower(),
                re.sub(r"\s+", " ", item.finding.lower()).strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _evidence_window(self, text: str, start: int, end: int) -> str:
        left = max(0, start - 120)
        right = min(len(text), end + 120)
        return self._clean_excerpt(text[left:right])

    def _clean_excerpt(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()[:220]

    def _related_paths_from_context(self, context: str) -> List[str]:
        paths = re.findall(r"source=([^\n]+)", context)
        deduped: List[str] = []
        seen = set()
        for path in paths:
            clean = path.strip()
            if clean and clean not in seen:
                seen.add(clean)
                deduped.append(clean)
        return deduped
