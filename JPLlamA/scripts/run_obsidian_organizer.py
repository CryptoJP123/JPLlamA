from __future__ import annotations

import argparse
from pathlib import Path

from app.obsidian.organizer import run_obsidian_organizer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run JPLlamA Obsidian organizer")
    parser.add_argument("--vault", required=True, help="Absolute path to Obsidian vault")
    parser.add_argument("--mode", choices=["dry-run", "analyze", "organize", "repair"], default="organize")
    args = parser.parse_args()

    result = run_obsidian_organizer(Path(args.vault), mode=args.mode)

    print("Mode:", result.mode)
    print("Folders created:", result.folders_created)
    print("Notes moved:", result.notes_moved)
    print("Notes renamed:", result.notes_renamed)
    print("Notes archived:", result.notes_archived)
    print("Duplicates:", result.duplicates_found)
    print("Review items:", result.review_items)
    print("Top customers:", result.top_customers[:5])
    print("Top projects:", result.top_projects[:5])
    print("Knowledge graph statistics:", result.knowledge_graph_stats)
    print("Estimated vault quality improvement:", result.quality_improvement)
    print("Report:", result.report_path)


if __name__ == "__main__":
    main()
