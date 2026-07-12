from __future__ import annotations

import argparse
from pathlib import Path
import time

from app.config import settings
from app.email.openwebui import OpenWebUIUploadWatcher
from app.obsidian.client import ObsidianClient, ObsidianConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Open WebUI upload directory for email ingestion")
    parser.add_argument("--uploads-dir", required=True, help="Open WebUI uploads directory")
    parser.add_argument("--state", default="output/openwebui_watcher_state.json", help="Watcher state file")
    parser.add_argument("--interval", type=float, default=10.0, help="Polling interval seconds")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    args = parser.parse_args()

    obsidian = ObsidianClient(ObsidianConfig(vault_path=settings.obsidian_vault))
    watcher = OpenWebUIUploadWatcher(Path(args.uploads_dir), Path(args.state))

    if args.once:
        result = watcher.run_once(obsidian=obsidian, vault_path=settings.obsidian_vault)
        print("Processed:", result.processed)
        print("Skipped:", result.skipped)
        print("Failures:", result.failures)
        print("State:", result.state_path)
        return

    while True:
        result = watcher.run_once(obsidian=obsidian, vault_path=settings.obsidian_vault)
        print("Processed:", result.processed, "Skipped:", result.skipped, "Failures:", result.failures)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
