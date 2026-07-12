from __future__ import annotations

import argparse
from pathlib import Path

from app.obsidian.actions_exporter import export_actions


def main() -> None:
    parser = argparse.ArgumentParser(description="Export actions to JSON and CSV")
    parser.add_argument("--vault", required=True, help="Absolute path to Obsidian vault")
    parser.add_argument("--output-dir", default="output", help="Directory for exports")
    args = parser.parse_args()

    result = export_actions(Path(args.vault), Path(args.output_dir))
    print("Total actions:", result.total_actions)
    print("JSON:", result.json_path)
    print("CSV:", result.csv_path)


if __name__ == "__main__":
    main()
