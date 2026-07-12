from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import re
from typing import Dict, Iterable, List, Tuple

IGNORED_DIRS = {"attachments", "resources", ".obsidian", ".trash", ".git", "__pycache__"}
ACTION_SECTIONS = {
    "to do": "todo",
    "deadlines": "deadlines",
    "follow-ups": "follow_ups",
    "risks": "risks",
    "decisions": "decisions",
}


@dataclass
class ActionExportResult:
    total_actions: int
    json_path: str
    csv_path: str


def _iter_markdown_files(vault_path: Path) -> Iterable[Path]:
    for path in vault_path.rglob("*.md"):
        parts = {part.lower() for part in path.relative_to(vault_path).parts}
        if parts.intersection(IGNORED_DIRS):
            continue
        yield path


def _extract_actions_from_text(text: str) -> Dict[str, List[str]]:
    lines = text.splitlines()
    actions: Dict[str, List[str]] = {value: [] for value in ACTION_SECTIONS.values()}
    current: str = ""

    for raw in lines:
        line = raw.strip()
        heading = re.match(r"^###\s+(.+)$", line)
        if heading:
            key = heading.group(1).strip().lower()
            current = ACTION_SECTIONS.get(key, "")
            continue

        if current and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                actions[current].append(value)

    return actions


def export_actions(vault_path: Path, output_dir: Path) -> ActionExportResult:
    vault = vault_path.expanduser()
    out = output_dir.expanduser()
    out.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, str]] = []
    for md_file in _iter_markdown_files(vault):
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        actions = _extract_actions_from_text(text)
        rel = md_file.relative_to(vault).as_posix()
        for action_type, items in actions.items():
            for item in items:
                rows.append(
                    {
                        "path": rel,
                        "action_type": action_type,
                        "action": item,
                    }
                )

    json_path = out / "actions_export.json"
    csv_path = out / "actions_export.csv"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "vault": str(vault),
        "total_actions": len(rows),
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "action_type", "action"])
        writer.writeheader()
        writer.writerows(rows)

    return ActionExportResult(total_actions=len(rows), json_path=str(json_path), csv_path=str(csv_path))
