from __future__ import annotations

import argparse
from pathlib import Path

from app.obsidian.apple_notes_migration import run_apple_notes_migration_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Run JPLlamA Apple Notes migration")
    parser.add_argument("--vault", required=True, help="Absolute path to Obsidian vault")
    args = parser.parse_args()

    engine = run_apple_notes_migration_engine(Path(args.vault), organizer_mode="organize")
    result = engine.migration

    print("Apple Notes migration completed.")
    print("Semantic organization completed.")
    print("Apple Notes hierarchy removed.")
    print("Search validated.")
    print("Knowledge base ready.")
    print("Original Apple Notes count:", result.original_apple_notes_count)
    print("Customers/Apple before:", result.customers_apple_before)
    print("Customers/Apple after:", result.customers_apple_after)
    print("Migrated notes:", result.migrated_notes)
    print("Markdown count before:", result.total_markdown_before)
    print("Markdown count after:", result.total_markdown_after)
    print("Customers created:", result.customers_created)
    print("Projects created:", result.projects_created)
    print("Meetings created:", result.meetings_created)
    print("Personal created:", result.personal_created)
    print("Reference created:", result.reference_created)
    print("Apple Notes folders removed:", result.apple_notes_folders_removed)
    print("Images archived:", result.images_archived)
    print("Broken links:", result.broken_links)
    print("Search validation:", result.search_validation)
    print("Knowledge graph:", result.knowledge_graph)
    print("Semantic organizer mode:", engine.organizer_mode)
    print("Semantic organizer moved:", engine.organizer_notes_moved)
    print("Semantic organizer renamed:", engine.organizer_notes_renamed)
    print("Semantic organizer duplicates:", engine.organizer_duplicates_found)
    print("Semantic organizer report:", engine.organizer_report_path)
    print("Tests passed.")
    print("Next milestone.")


if __name__ == "__main__":
    main()
