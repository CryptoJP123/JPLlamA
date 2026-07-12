from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

TARGET_FOLDERS: Tuple[str, ...] = (
    "Customers",
    "Projects",
    "Meetings",
    "Ideas",
    "Personal",
    "Reference",
    "HiFi",
    "AI",
    "DPWorld",
)

FOLDER_KEYWORDS: Dict[str, set] = {
    "Customers": {"customer", "client", "account", "stakeholder", "crm"},
    "Projects": {"project", "roadmap", "milestone", "delivery", "launch", "plan"},
    "Meetings": {"meeting", "agenda", "minutes", "workshop", "sync", "standup"},
    "Ideas": {"idea", "brainstorm", "concept", "hypothesis", "draft", "proposal"},
    "Personal": {"personal", "journal", "habit", "family", "health", "life"},
    "Reference": {"reference", "guide", "manual", "documentation", "howto", "faq"},
    "HiFi": {"hifi", "audio", "speaker", "amplifier", "dac", "headphone"},
    "AI": {"ai", "ollama", "llm", "model", "prompt", "embedding", "rag", "agent"},
    "DPWorld": {"dpworld", "dp", "port", "terminal", "shipping", "logistics", "cargo"},
}


@dataclass
class NoteProposal:
    note: str
    current_folder: str
    proposed_folder: str
    confidence: float
    reason: str


def tokenize(text: str) -> List[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z0-9_]+", text)]


def extract_frontmatter_tags(text: str) -> List[str]:
    if not text.startswith("---\n"):
        return []

    end = text.find("\n---\n", 4)
    if end < 0:
        return []

    block = text[4:end]
    tags: List[str] = []
    in_tags = False

    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.lower().startswith("tags:"):
            in_tags = True
            _, value = line.split(":", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                tags.extend([v.strip().lower() for v in value.split(",") if v.strip()])
            continue

        if in_tags and line.startswith("-"):
            tags.append(line.lstrip("- ").strip().strip('"').strip("'").lower())
            continue

        if in_tags and not line.startswith("-"):
            in_tags = False

    return tags


def classify_note(note_path: Path, vault: Path) -> NoteProposal:
    rel = note_path.relative_to(vault)
    current_folder = rel.parts[0] if len(rel.parts) > 1 else "(root)"

    text = note_path.read_text(encoding="utf-8", errors="ignore")
    title_tokens = tokenize(note_path.stem)
    body_tokens = tokenize(text[:6000])
    tags = extract_frontmatter_tags(text)

    token_set = set(title_tokens + body_tokens)
    tag_set = set(tags)

    folder_scores: Dict[str, float] = {folder: 0.0 for folder in TARGET_FOLDERS}
    folder_reasons: Dict[str, List[str]] = {folder: [] for folder in TARGET_FOLDERS}

    for folder, keywords in FOLDER_KEYWORDS.items():
        keyword_hits = sorted(token_set.intersection(keywords))
        tag_hits = sorted(tag_set.intersection(keywords))

        if keyword_hits:
            folder_scores[folder] += 1.0 * len(keyword_hits)
            folder_reasons[folder].append(f"keywords={','.join(keyword_hits[:4])}")

        if tag_hits:
            folder_scores[folder] += 2.0 * len(tag_hits)
            folder_reasons[folder].append(f"tags={','.join(tag_hits[:4])}")

    if current_folder in folder_scores and current_folder != "(root)":
        folder_scores[current_folder] += 0.5
        folder_reasons[current_folder].append("existing-folder-boost")

    sorted_scores = sorted(folder_scores.items(), key=lambda item: item[1], reverse=True)
    best_folder, best_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    if best_score <= 0.0:
        best_folder = "Reference"
        best_score = 0.1
        second_score = 0.0
        folder_reasons[best_folder].append("fallback-reference")

    margin = max(0.0, best_score - second_score)
    confidence = min(0.99, 0.45 + (0.08 * best_score) + (0.12 * margin))

    reason_bits = folder_reasons.get(best_folder) or ["weak-signal"]
    reason = "; ".join(reason_bits[:3])

    return NoteProposal(
        note=str(rel),
        current_folder=current_folder,
        proposed_folder=best_folder,
        confidence=round(confidence, 2),
        reason=reason,
    )


def scan_vault(vault: Path) -> List[Path]:
    return sorted(vault.rglob("*.md"))


def build_report(vault: Path) -> List[NoteProposal]:
    proposals: List[NoteProposal] = []
    for md_file in scan_vault(vault):
        proposals.append(classify_note(md_file, vault))
    return proposals


def write_csv(path: Path, rows: Iterable[NoteProposal]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["note", "current_folder", "proposed_folder", "confidence", "reason"])
        for row in rows:
            writer.writerow([row.note, row.current_folder, row.proposed_folder, row.confidence, row.reason])


def sample_would_move(rows: List[NoteProposal], sample_size: int) -> List[NoteProposal]:
    candidates = [
        row
        for row in rows
        if row.current_folder != row.proposed_folder and row.confidence >= 0.65
    ]
    candidates.sort(key=lambda row: row.confidence, reverse=True)
    return candidates[:sample_size]


def main() -> None:
    parser = argparse.ArgumentParser(description="Non-destructive Obsidian reorganization dry run")
    parser.add_argument("--vault", required=True, help="Absolute path to Obsidian vault")
    parser.add_argument(
        "--report",
        default="output/obsidian_reorg_report.csv",
        help="Where to write the classification report CSV",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="How many high-confidence mismatches to preview as would-move sample",
    )
    args = parser.parse_args()

    vault = Path(args.vault).expanduser()
    if not vault.exists():
        raise SystemExit(f"Vault not found: {vault}")

    rows = build_report(vault)
    report_path = Path(args.report)
    write_csv(report_path, rows)

    would_move = sample_would_move(rows, args.sample_size)

    print(f"Scanned notes: {len(rows)}")
    print(f"Report written: {report_path}")
    print()
    print("Would-move sample (dry run only):")
    if not would_move:
        print("- No high-confidence mismatches found.")
    for row in would_move:
        print(
            f"- {row.note} | {row.current_folder} -> {row.proposed_folder} "
            f"| confidence={row.confidence} | reason={row.reason}"
        )


if __name__ == "__main__":
    main()
