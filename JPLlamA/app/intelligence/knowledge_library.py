from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SYSTEM_FOLDER_NAME = "_JPLlamA"

NOT_CUSTOMER_COMPANIES = {
    "dp world",
    "agility",
    "cargo partner",
    "chain iq",
    "ciq",
    "awk",
    "eraneos",
}

FOLDER_MAP_SEED: List[Dict[str, Any]] = [
    {"folder": "Agility Backup", "category": "historical_company_context", "company": "Agility", "customer_status": "not_customer_by_default", "notes": "historical/company backup context"},
    {"folder": "Apple Notes", "category": "imported_notes", "customer_status": "unknown", "notes": "imported personal/work notes"},
    {"folder": "Backup", "category": "backup", "customer_status": "unknown", "notes": "backup archive"},
    {"folder": "Cargo Partner", "category": "historical_company_context", "company": "Cargo Partner", "customer_status": "not_customer_by_default", "notes": "historical/company context"},
    {"folder": "CIQ AWK recovery", "category": "recovered_company_context", "companies": ["Chain IQ", "CIQ", "AWK"], "customer_status": "not_customer_by_default", "notes": "recovered historical company/project context"},
    {"folder": "Desktop Acticels", "category": "articles_or_desktop_material", "customer_status": "unknown", "notes": "desktop article/material archive"},
    {"folder": "DP World", "category": "employer_company_context", "company": "DP World", "customer_status": "not_customer_by_default", "notes": "employer/reference/company context"},
    {"folder": "eMails to Remember", "category": "email_archive", "artifact_type": "email", "customer_status": "derive_from_content", "notes": "remembered emails and email metadata"},
    {"folder": "Evernote Backup", "category": "imported_notes_backup", "customer_status": "unknown", "notes": "imported Evernote backup"},
    {"folder": "HandNotes", "category": "handwritten_notes", "customer_status": "derive_from_content", "notes": "handwritten notes / personal working notes"},
    {"folder": "Photos Whiteboards", "category": "visual_notes", "customer_status": "derive_from_content", "notes": "photos and whiteboard captures"},
    {"folder": "PPTX to Remember", "category": "presentation_archive", "artifact_type": "presentation", "customer_status": "derive_from_content", "notes": "remembered/generated presentations and presentation notes"},
    {"folder": "Presentation Powerpoint Knowledge Base", "category": "presentation_knowledge", "artifact_type": "presentation_pattern", "customer_status": "derive_from_content", "notes": "slide style, presentation structure, reusable PowerPoint patterns"},
    {"folder": "RFQ Contract Review Knowledge Base", "category": "rfq_review_knowledge", "artifact_type": "rfq_review", "customer_status": "derive_from_content", "notes": "RFQ commercial/legal/operational review patterns; VW review may be gold standard if present"},
    {"folder": "RKC Cumbria", "category": "project_or_customer_context", "customer_status": "derive_from_content", "notes": "likely project/customer-related RFQ or commercial context"},
    {"folder": "Steuern", "category": "tax_private_admin", "customer_status": "not_customer_by_default", "notes": "tax/private admin context"},
    {"folder": "Stuff", "category": "miscellaneous", "customer_status": "unknown", "notes": "miscellaneous archive"},
    {"folder": "how to open JPLlamA", "category": "system_instruction_note", "customer_status": "not_customer_by_default", "notes": "operational instruction note"},
]


def is_customer_by_default(company_name: str) -> bool:
    return company_name.strip().lower() not in NOT_CUSTOMER_COMPANIES


def resolve_system_root(vault_path: Path) -> Path:
    vault = vault_path.expanduser()
    exact = vault / SYSTEM_FOLDER_NAME
    if exact.exists() and exact.is_dir():
        return exact

    candidates = [
        item
        for item in vault.iterdir()
        if item.is_dir() and "jpllama" in item.name.lower()
    ] if vault.exists() else []
    if candidates:
        candidates.sort(key=lambda item: len(item.name))
        return candidates[0]

    return exact


def _knowledge_library_paths(system_root: Path) -> Dict[str, Path]:
    kb = system_root / "Knowledge Library"
    return {
        "knowledge_catalog_md": kb / "Knowledge Catalog.md",
        "knowledge_catalog_json": kb / "Knowledge Catalog.json",
        "folder_map_md": kb / "Folder Map.md",
        "folder_map_json": kb / "Folder Map.json",
    }


def _default_knowledge_catalog_json() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now().isoformat(),
        "entries": [],
    }


def _render_folder_map_md(items: List[Dict[str, Any]]) -> str:
    lines = ["# Folder Map", "", "Editable map of JP vault folders.", ""]
    for item in items:
        lines.append(f"## {item['folder']}")
        for key, value in item.items():
            if key == "folder":
                continue
            if isinstance(value, list):
                lines.append(f"- {key}: {', '.join(str(v) for v in value)}")
            else:
                lines.append(f"- {key}: {value}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_knowledge_catalog_md(catalog: Dict[str, Any]) -> str:
    lines = ["# Knowledge Catalog", "", "Catalog map to original archive artifacts.", ""]
    entries = catalog.get("entries") or []
    if not entries:
        lines.append("No catalog entries yet.")
        return "\n".join(lines) + "\n"

    for entry in entries:
        lines.append(f"## {entry.get('title') or entry.get('catalog_id')}")
        for key in (
            "catalog_id",
            "artifact_type",
            "customer",
            "company_context",
            "project",
            "date",
            "source_folder",
            "original_path",
            "vault_note_path",
            "stored_artifact_path",
            "summary",
            "quality_marker",
            "confidence",
            "last_updated",
        ):
            lines.append(f"- {key}: {entry.get(key, '')}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def ensure_system_library(vault_path: Path) -> Path:
    vault = vault_path.expanduser()
    system_root = resolve_system_root(vault)

    paths = _knowledge_library_paths(system_root)
    (system_root / "Knowledge Library").mkdir(parents=True, exist_ok=True)
    (system_root / "Reference Sources" / "DP World Freight Forwarding Documentation Centre" / "documents").mkdir(parents=True, exist_ok=True)
    (system_root / "Reference Sources" / "DP World Freight Forwarding Documentation Centre" / "snapshots").mkdir(parents=True, exist_ok=True)
    (system_root / "Templates").mkdir(parents=True, exist_ok=True)
    (system_root / "System Notes").mkdir(parents=True, exist_ok=True)

    if not paths["folder_map_json"].exists():
        paths["folder_map_json"].write_text(json.dumps({"folders": FOLDER_MAP_SEED}, indent=2), encoding="utf-8")
    if not paths["folder_map_md"].exists():
        paths["folder_map_md"].write_text(_render_folder_map_md(FOLDER_MAP_SEED), encoding="utf-8")

    if not paths["knowledge_catalog_json"].exists():
        catalog = _default_knowledge_catalog_json()
        paths["knowledge_catalog_json"].write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    if not paths["knowledge_catalog_md"].exists():
        paths["knowledge_catalog_md"].write_text(_render_knowledge_catalog_md(_default_knowledge_catalog_json()), encoding="utf-8")

    templates = {
        system_root / "Templates" / "RFQ Review Pattern.md": "# RFQ Review Pattern\n\nAdd reusable RFQ review structure here.\n",
        system_root / "Templates" / "Presentation Pattern.md": "# Presentation Pattern\n\nAdd reusable presentation structure here.\n",
        system_root / "System Notes" / "Source Policy.md": "# Source Policy\n\nDefault mode is Direct. Vault/web/reference sources are explicit-only.\n",
        system_root / "System Notes" / "Changelog Links.md": "# Changelog Links\n\nTrack milestone links and important architecture updates here.\n",
    }
    for path, content in templates.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    return system_root


def _load_catalog(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _default_knowledge_catalog_json()
    try:
        parsed = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return _default_knowledge_catalog_json()
    if not isinstance(parsed, dict):
        return _default_knowledge_catalog_json()
    if "entries" not in parsed or not isinstance(parsed["entries"], list):
        parsed["entries"] = []
    return parsed


def upsert_catalog_entry(vault_path: Path, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not entry:
        return None
    system_root = ensure_system_library(vault_path)
    paths = _knowledge_library_paths(system_root)
    catalog = _load_catalog(paths["knowledge_catalog_json"])

    entries: List[Dict[str, Any]] = list(catalog.get("entries") or [])
    key = str(entry.get("vault_note_path") or entry.get("stored_artifact_path") or entry.get("original_path") or "").strip()
    if not key:
        return None

    now_value = datetime.now().isoformat()
    normalized = {
        "catalog_id": entry.get("catalog_id") or f"cat-{abs(hash(key))}",
        "title": entry.get("title") or "Untitled",
        "artifact_type": entry.get("artifact_type") or "document",
        "customer": entry.get("customer") or "unknown",
        "company_context": entry.get("company_context") or "",
        "project": entry.get("project") or "unknown",
        "date": entry.get("date") or now_value[:10],
        "source_folder": entry.get("source_folder") or "",
        "original_path": entry.get("original_path") or "",
        "vault_note_path": entry.get("vault_note_path") or "",
        "stored_artifact_path": entry.get("stored_artifact_path") or "",
        "summary": entry.get("summary") or "",
        "key_details": entry.get("key_details") or [],
        "entities": entry.get("entities") or [],
        "tags": entry.get("tags") or [],
        "topics": entry.get("topics") or [],
        "useful_for": entry.get("useful_for") or "",
        "related_notes": entry.get("related_notes") or [],
        "related_artifacts": entry.get("related_artifacts") or [],
        "quality_marker": entry.get("quality_marker") or "useful_example",
        "confidence": entry.get("confidence") or "medium",
        "last_updated": now_value,
    }

    replaced = False
    for idx, existing in enumerate(entries):
        existing_key = str(existing.get("vault_note_path") or existing.get("stored_artifact_path") or existing.get("original_path") or "").strip()
        if existing_key == key:
            entries[idx] = normalized
            replaced = True
            break
    if not replaced:
        entries.append(normalized)

    catalog["updated_at"] = now_value
    catalog["entries"] = entries

    paths["knowledge_catalog_json"].write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    paths["knowledge_catalog_md"].write_text(_render_knowledge_catalog_md(catalog), encoding="utf-8")
    return normalized


def read_catalog(vault_path: Path) -> List[Dict[str, Any]]:
    system_root = ensure_system_library(vault_path)
    catalog_path = _knowledge_library_paths(system_root)["knowledge_catalog_json"]
    return list(_load_catalog(catalog_path).get("entries") or [])
