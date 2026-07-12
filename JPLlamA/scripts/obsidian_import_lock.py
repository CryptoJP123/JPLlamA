from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

LOCK_NAMES = (".import.lock", "import.lock", ".obsidian-import.lock")


def _resolve_lock_path(vault: Path, lock_name: str) -> Path:
    if lock_name not in LOCK_NAMES:
        raise ValueError(f"Unsupported lock name: {lock_name}")
    return vault / lock_name


def set_lock(vault: Path, lock_name: str, source: str) -> Path:
    lock_path = _resolve_lock_path(vault, lock_name)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        f"locked_at={datetime.now(timezone.utc).isoformat()}\n"
        f"source={source or 'import'}\n"
        "status=import-in-progress\n"
    )
    lock_path.write_text(payload, encoding="utf-8")
    return lock_path


def clear_lock(vault: Path, lock_name: str) -> bool:
    lock_path = _resolve_lock_path(vault, lock_name)
    if not lock_path.exists():
        return False
    lock_path.unlink()
    return True


def print_status(vault: Path) -> int:
    found = False
    for lock_name in LOCK_NAMES:
        lock_path = vault / lock_name
        if lock_path.exists():
            found = True
            print(f"LOCKED: {lock_path}")
            content = lock_path.read_text(encoding="utf-8", errors="ignore").strip()
            if content:
                print(content)
    if not found:
        print(f"UNLOCKED: no import lock files found in {vault}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Obsidian import lock files for safe organizer runs")
    parser.add_argument("--vault", required=True, help="Absolute path to Obsidian vault")
    parser.add_argument("--lock-name", default=".import.lock", choices=LOCK_NAMES)
    parser.add_argument("--source", default="apple-notes-import", help="Source label stored in lock content")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--set", action="store_true", help="Create or update import lock file")
    group.add_argument("--clear", action="store_true", help="Remove import lock file")
    group.add_argument("--status", action="store_true", help="Show lock status")

    args = parser.parse_args()
    vault = Path(args.vault).expanduser()

    if args.status:
        raise SystemExit(print_status(vault))

    if args.set:
        lock_path = set_lock(vault, args.lock_name, args.source)
        print(f"Lock set: {lock_path}")
        return

    if args.clear:
        removed = clear_lock(vault, args.lock_name)
        if removed:
            print(f"Lock cleared: {vault / args.lock_name}")
        else:
            print(f"No lock file found: {vault / args.lock_name}")


if __name__ == "__main__":
    main()
