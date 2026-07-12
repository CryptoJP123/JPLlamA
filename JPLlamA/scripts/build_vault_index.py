from __future__ import annotations

import argparse
from pathlib import Path

from app.obsidian.indexer import build_vault_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build background Obsidian vault index")
    parser.add_argument("--vault", required=True, help="Absolute path to Obsidian vault")
    parser.add_argument("--output", help="Optional output JSON path")
    parser.add_argument("--workers", type=int, default=8, help="Parallel indexing workers")
    args = parser.parse_args()

    result = build_vault_index(
        Path(args.vault),
        output_path=Path(args.output).expanduser() if args.output else None,
        workers=args.workers,
    )

    print("Notes indexed:", result.notes_indexed)
    print("Index path:", result.output_path)
    print("Duration seconds:", round(result.duration_seconds, 2))


if __name__ == "__main__":
    main()
