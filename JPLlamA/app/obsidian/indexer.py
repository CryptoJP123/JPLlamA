from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional

IGNORED_DIRS = {
    "attachments",
    "resources",
    "resource",
    "media",
    "images",
    "img",
    "assets",
    "organizerbackups",
    ".obsidian",
    ".trash",
    ".git",
    "__pycache__",
}


@dataclass
class IndexBuildResult:
    notes_indexed: int
    output_path: str
    duration_seconds: float


def _iter_markdown_files(vault_path: Path) -> Iterable[Path]:
    for path in vault_path.rglob("*.md"):
        parts = {part.lower() for part in path.relative_to(vault_path).parts}
        if parts.intersection(IGNORED_DIRS):
            continue
        yield path


def _extract_frontmatter(text: str) -> Dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}

    block = text[4:end]
    frontmatter: Dict[str, object] = {}
    current_list: Optional[str] = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_list:
            value = line[4:].strip().strip('"').strip("'")
            frontmatter.setdefault(current_list, [])
            if isinstance(frontmatter[current_list], list):
                frontmatter[current_list].append(value)
            continue

        current_list = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if value:
            frontmatter[key] = value
        else:
            frontmatter[key] = []
            current_list = key

    return frontmatter


def _extract_links(text: str) -> List[str]:
    links = []
    for match in re.findall(r"\[\[([^\]|#]+)", text):
        target = str(match).strip()
        if target:
            links.append(target)
    return sorted(set(links))[:200]


def _summary(text: str) -> str:
    stripped = re.sub(r"---\n.*?\n---\n", "", text, flags=re.DOTALL)
    clean = re.sub(r"\s+", " ", stripped).strip()
    if not clean:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    return " ".join(sentences[:2])[:320]


def _index_note(path: Path, vault_path: Path) -> Dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    frontmatter = _extract_frontmatter(text)
    stat = path.stat()
    rel = path.relative_to(vault_path)

    return {
        "path": rel.as_posix(),
        "title": str(frontmatter.get("title") or path.stem.replace("-", " ")),
        "folder": rel.parts[0] if rel.parts else "",
        "summary": str(frontmatter.get("summary") or _summary(text)),
        "tags": frontmatter.get("tags") if isinstance(frontmatter.get("tags"), list) else [],
        "aliases": frontmatter.get("aliases") if isinstance(frontmatter.get("aliases"), list) else [],
        "customer": frontmatter.get("customer") or "",
        "project": frontmatter.get("project") or "",
        "meeting": frontmatter.get("meeting") or "",
        "technology": frontmatter.get("technology") if isinstance(frontmatter.get("technology"), list) else [],
        "links": _extract_links(text),
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size_bytes": stat.st_size,
    }


def build_vault_index(
    vault_path: Path,
    *,
    output_path: Optional[Path] = None,
    workers: int = 8,
) -> IndexBuildResult:
    started = datetime.now(timezone.utc)
    vault = vault_path.expanduser()
    output = (output_path or (vault / "Archive" / "vault_index.json")).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    files = list(_iter_markdown_files(vault))
    records: List[Dict[str, object]] = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(_index_note, path, vault) for path in files]
        for future in as_completed(futures):
            records.append(future.result())

    records.sort(key=lambda item: str(item.get("path") or ""))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "vault": str(vault),
        "notes": records,
        "counts": {
            "notes": len(records),
            "folders": len({str(item.get("folder") or "") for item in records}),
        },
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    return IndexBuildResult(notes_indexed=len(records), output_path=str(output), duration_seconds=duration)
