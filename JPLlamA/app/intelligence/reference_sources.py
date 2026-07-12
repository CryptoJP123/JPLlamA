from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from urllib import request
from urllib.parse import urljoin, urlparse

from .knowledge_library import ensure_system_library

DEFAULT_REFERENCE_SOURCE_ID = "dp_world_freight_forwarding_documentation_centre"
DP_WORLD_NAME = "DP World Freight Forwarding Documentation Centre"
DP_WORLD_URL = "https://www.dpworld.com/en/supply-chain-solutions/freight-forwarding/documentation-centre"

_INDEX_COMMANDS = (
    "index the dp world documentation centre",
    "download the dp world freight forwarding documentation centre",
    "refresh the dp world documentation centre",
    "update the dp world t&c reference source",
    "download and index the dp world documentation centre",
)

_COUNTRY_NAMES = {
    "austria", "belgium", "canada", "czech republic", "denmark", "finland", "france", "germany",
    "hungary", "ireland", "italy", "mexico", "netherlands", "norway", "poland", "romania",
    "slovakia", "spain", "sweden", "switzerland", "uae", "usa", "united arab emirates", "united states",
}


@dataclass
class ReferenceIndexResult:
    index_path: str
    markdown_index_path: str
    documents_downloaded: int
    documents_failed: int
    snapshot_path: str
    source_url: str = DP_WORLD_URL


def _chunk_text(text: str, size: int = 1800, overlap: int = 300) -> List[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    if len(normalized) <= size:
        return [normalized]

    chunks: List[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + size)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def _strip_html(text: str) -> str:
    no_script = re.sub(r"<script.*?>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    no_style = re.sub(r"<style.*?>.*?</style>", " ", no_script, flags=re.IGNORECASE | re.DOTALL)
    no_tags = re.sub(r"<[^>]+>", " ", no_style)
    return re.sub(r"\s+", " ", no_tags).strip()


def _extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            data = zf.read("word/document.xml").decode("utf-8", errors="ignore")
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", data)).strip()
    except Exception:
        return ""


def _extract_pptx_text(path: Path) -> str:
    chunks: List[str] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in sorted(zf.namelist()):
                if name.startswith("ppt/slides/") and name.endswith(".xml"):
                    data = zf.read(name).decode("utf-8", errors="ignore")
                    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", data)).strip()
                    if text:
                        chunks.append(text)
    except Exception:
        return ""
    return "\n".join(chunks)


def _extract_xlsx_text(path: Path) -> str:
    lines: List[str] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                shared_xml = zf.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
                shared_strings = [
                    re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()
                    for value in re.findall(r"<si>(.*?)</si>", shared_xml, flags=re.DOTALL)
                ]
            for name in sorted(zf.namelist()):
                if not (name.startswith("xl/worksheets/") and name.endswith(".xml")):
                    continue
                xml_text = zf.read(name).decode("utf-8", errors="ignore")
                for row in re.findall(r"<row[^>]*>(.*?)</row>", xml_text, flags=re.DOTALL):
                    cells: List[str] = []
                    for cell in re.findall(r"<c[^>]*>(.*?)</c>", row, flags=re.DOTALL):
                        v_match = re.search(r"<v>(.*?)</v>", cell, flags=re.DOTALL)
                        if not v_match:
                            continue
                        value = v_match.group(1).strip()
                        if " t=\"s\"" in cell and value.isdigit():
                            idx = int(value)
                            value = shared_strings[idx] if 0 <= idx < len(shared_strings) else value
                        cells.append(value)
                    if cells:
                        lines.append(" | ".join(cells))
    except Exception:
        return ""
    return "\n".join(lines)


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""

    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(page.strip() for page in pages if page and page.strip())
    except Exception:
        return ""


def _extract_text_for_index(path: Path, file_type: str, content_type: str) -> Tuple[str, str]:
    file_type = (file_type or "").lower().lstrip(".")
    content_type = (content_type or "").lower()

    if file_type in {"txt", "md", "csv", "json", "yaml", "yml", "xml"}:
        return path.read_text(encoding="utf-8", errors="ignore"), "utf8"
    if file_type in {"html", "htm"} or "text/html" in content_type:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        return _strip_html(raw), "html"
    if file_type == "pdf" or "application/pdf" in content_type:
        extracted = _extract_pdf_text(path)
        return extracted, "pdf"
    if file_type == "docx":
        return _extract_docx_text(path), "docx"
    if file_type == "pptx":
        return _extract_pptx_text(path), "pptx"
    if file_type == "xlsx":
        return _extract_xlsx_text(path), "xlsx"

    # Fallback for unknown binaries: decode printable text conservatively.
    raw = path.read_bytes()
    decoded = raw.decode("utf-8", errors="ignore")
    compact = re.sub(r"\s+", " ", decoded).strip()
    return compact, "binary-fallback"


def is_reference_index_command(prompt: str) -> bool:
    lowered = prompt.strip().lower()
    return any(lowered.startswith(command) for command in _INDEX_COMMANDS)


def _registry_yaml(local_folder: str, last_indexed: Optional[str]) -> str:
    return (
        "sources:\n"
        f"  - id: {DEFAULT_REFERENCE_SOURCE_ID}\n"
        f"    name: {DP_WORLD_NAME}\n"
        f"    url: {DP_WORLD_URL}\n"
        "    type: webpage_document_centre\n"
        "    purpose:\n"
        "      - freight forwarding terms and conditions\n"
        "      - logistics terms of service\n"
        "      - Smart Solutions Line shipping documents\n"
        "      - DP World Standard Trading Conditions\n"
        "      - country-specific terms and conditions\n"
        "      - RFQ legal/commercial review support\n"
        "    use_policy: explicit_only\n"
        "    refresh_policy: manual_or_on_command\n"
        f"    local_folder: {local_folder}\n"
        f"    last_indexed: {last_indexed if last_indexed else 'null'}\n"
    )


def _extract_links(html: str, base_url: str) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    for href, text in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, flags=re.IGNORECASE | re.DOTALL):
        clean_text = re.sub(r"<.*?>", "", text)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if not clean_text:
            clean_text = Path(parsed.path).name or full_url
        if any(token in full_url.lower() for token in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")) or "terms" in clean_text.lower() or "document" in clean_text.lower():
            links.append({"url": full_url, "title": clean_text})

    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in links:
        key = item["url"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _categorize(title: str) -> str:
    lowered = title.lower()
    if "smart solutions line" in lowered:
        return "Smart Solutions Line Shipping Documents"
    if "standard trading conditions" in lowered:
        return "DP World Standard Trading Conditions"
    if "country" in lowered or "terms" in lowered:
        return "Country-Specific Terms & Conditions"
    return "Documentation Centre"


def _extract_country(title: str) -> str:
    lowered = title.lower()
    for name in sorted(_COUNTRY_NAMES, key=len, reverse=True):
        if name in lowered:
            if name == "united arab emirates":
                return "UAE"
            if name == "united states":
                return "USA"
            return name.title()
    return ""


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned[:150] or "document"


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_markdown_index(path: Path, entries: List[Dict[str, Any]]) -> None:
    lines = [f"# {DP_WORLD_NAME} Index", ""]
    if not entries:
        lines.append("No documents indexed.")
    for idx, entry in enumerate(entries, start=1):
        lines.append(f"## {idx}. {entry.get('document_title')}")
        for key in (
            "category",
            "country",
            "source_url",
            "downloaded_file_path",
            "text_sidecar_path",
            "file_type",
            "content_type",
            "retrieved_at",
            "file_size",
            "checksum",
            "chunk_count",
            "status",
        ):
            lines.append(f"- {key}: {entry.get(key, '')}")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def download_and_index_dp_world_documentation_centre(vault_path: Path, fetch_timeout: float = 20.0) -> ReferenceIndexResult:
    system_root = ensure_system_library(vault_path)
    ref_root = system_root / "Reference Sources" / DP_WORLD_NAME
    docs_dir = ref_root / "documents"
    extracted_dir = ref_root / "extracted"
    chunks_dir = ref_root / "chunks"
    snapshots_dir = ref_root / "snapshots"
    docs_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    req = request.Request(DP_WORLD_URL, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=fetch_timeout) as response:
        html_bytes = response.read()
    html_text = html_bytes.decode("utf-8", errors="ignore")

    snapshot_path = snapshots_dir / f"documentation-centre-{now}.html"
    snapshot_path.write_text(html_text, encoding="utf-8")

    links = _extract_links(html_text, DP_WORLD_URL)
    entries: List[Dict[str, Any]] = []
    chunk_entries: List[Dict[str, Any]] = []
    downloaded = 0
    failed = 0

    for link in links:
        source_url = link["url"]
        title = link["title"]
        category = _categorize(title)
        country = _extract_country(title)
        parsed = urlparse(source_url)
        source_name = Path(parsed.path).name
        extension = Path(source_name).suffix.lower() or ".bin"
        file_name = f"{now}-{_safe_filename(title)}{extension if extension.startswith('.') else '.' + extension}"
        destination = docs_dir / file_name
        text_sidecar = extracted_dir / f"{Path(file_name).stem}.txt"
        chunk_sidecar = chunks_dir / f"{Path(file_name).stem}.json"

        entry: Dict[str, Any] = {
            "source_id": DEFAULT_REFERENCE_SOURCE_ID,
            "source_name": DP_WORLD_NAME,
            "document_title": title,
            "category": category,
            "country": country,
            "source_url": source_url,
            "downloaded_file_path": str(destination),
            "text_sidecar_path": "",
            "chunk_sidecar_path": "",
            "file_type": extension.lstrip("."),
            "content_type": "",
            "retrieved_at": datetime.now().isoformat(),
            "file_size": 0,
            "checksum": "",
            "chunk_count": 0,
            "notes": "indexed from documentation centre",
            "useful_for": "RFQ legal/commercial review support",
            "status": "indexed_url_only",
        }

        try:
            doc_req = request.Request(source_url, headers={"User-Agent": "Mozilla/5.0"})
            with request.urlopen(doc_req, timeout=fetch_timeout) as response:
                content = response.read()
                response_headers = getattr(response, "headers", {}) or {}
                content_type = str(getattr(response_headers, "get", lambda _k, _d="": "")("Content-Type", "")).strip()
            destination.write_bytes(content)
            entry["file_size"] = destination.stat().st_size
            entry["checksum"] = _checksum(destination)
            entry["content_type"] = content_type

            extracted_text, extraction_mode = _extract_text_for_index(destination, entry["file_type"], content_type)
            text_sidecar.write_text(extracted_text, encoding="utf-8")
            chunks = _chunk_text(extracted_text)
            chunk_payload = {
                "source_id": DEFAULT_REFERENCE_SOURCE_ID,
                "document_title": title,
                "source_url": source_url,
                "file_path": str(destination),
                "extraction_mode": extraction_mode,
                "chunk_count": len(chunks),
                "chunks": [
                    {
                        "chunk_id": f"{Path(file_name).stem}:{idx + 1}",
                        "ordinal": idx + 1,
                        "text": chunk,
                    }
                    for idx, chunk in enumerate(chunks)
                ],
            }
            chunk_sidecar.write_text(json.dumps(chunk_payload, indent=2), encoding="utf-8")

            for idx, chunk in enumerate(chunks):
                chunk_entries.append(
                    {
                        "chunk_id": f"{Path(file_name).stem}:{idx + 1}",
                        "document_title": title,
                        "source_url": source_url,
                        "downloaded_file_path": str(destination),
                        "text_sidecar_path": str(text_sidecar),
                        "chunk_sidecar_path": str(chunk_sidecar),
                        "ordinal": idx + 1,
                        "text": chunk,
                    }
                )

            entry["text_sidecar_path"] = str(text_sidecar)
            entry["chunk_sidecar_path"] = str(chunk_sidecar)
            entry["chunk_count"] = len(chunks)
            entry["status"] = "downloaded"
            downloaded += 1
        except Exception as exc:
            entry["downloaded_file_path"] = ""
            entry["status"] = "download_failed"
            entry["notes"] = f"download failed: {exc}"
            failed += 1

        entries.append(entry)

    index_json = ref_root / "index.json"
    payload = {
        "source_id": DEFAULT_REFERENCE_SOURCE_ID,
        "source_name": DP_WORLD_NAME,
        "source_url": DP_WORLD_URL,
        "last_indexed": datetime.now().isoformat(),
        "fast_index_path": str(ref_root / "chunk_index.json"),
        "documents": entries,
    }
    index_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    chunk_index = ref_root / "chunk_index.json"
    chunk_index.write_text(
        json.dumps(
            {
                "source_id": DEFAULT_REFERENCE_SOURCE_ID,
                "source_name": DP_WORLD_NAME,
                "source_url": DP_WORLD_URL,
                "last_indexed": payload["last_indexed"],
                "chunk_count": len(chunk_entries),
                "chunks": chunk_entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    chunk_index_md = ref_root / "chunk_index.md"
    summary_lines = [
        f"# {DP_WORLD_NAME} Chunk Index",
        "",
        f"- generated_at: {payload['last_indexed']}",
        f"- chunk_count: {len(chunk_entries)}",
        "",
    ]
    for chunk in chunk_entries[:60]:
        preview = str(chunk.get("text", "")).replace("\n", " ")[:220]
        summary_lines.append(f"## {chunk.get('chunk_id')}")
        summary_lines.append(f"- document_title: {chunk.get('document_title')}")
        summary_lines.append(f"- source_url: {chunk.get('source_url')}")
        summary_lines.append(f"- preview: {preview}")
        summary_lines.append("")
    chunk_index_md.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")

    index_md = ref_root / "index.md"
    _write_markdown_index(index_md, entries)

    registry_path = system_root / "Reference Sources" / "reference_sources.yml"
    registry_path.write_text(_registry_yaml(str(ref_root), payload["last_indexed"]), encoding="utf-8")

    return ReferenceIndexResult(
        index_path=str(index_json),
        markdown_index_path=str(index_md),
        documents_downloaded=downloaded,
        documents_failed=failed,
        snapshot_path=str(snapshot_path),
    )
