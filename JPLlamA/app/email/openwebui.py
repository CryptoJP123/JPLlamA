from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, List, Optional

from app.email.workflow import EmailWorkflow
from app.memory.store import remember_email_workflow
from app.obsidian.client import ObsidianClient

SUPPORTED_SUFFIXES = {".eml", ".msg", ".txt", ".md"}


@dataclass
class WatcherRunResult:
    processed: int
    skipped: int
    failures: int
    state_path: str


class OpenWebUIUploadWatcher:
    def __init__(
        self,
        uploads_dir: Path,
        state_path: Path,
        *,
        workflow: Optional[EmailWorkflow] = None,
    ):
        self.uploads_dir = uploads_dir.expanduser()
        self.state_path = state_path.expanduser()
        self.workflow = workflow or EmailWorkflow()

    def _load_state(self) -> Dict[str, str]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: Dict[str, str]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _discover_candidates(self) -> List[Path]:
        if not self.uploads_dir.exists():
            return []
        files = []
        for path in self.uploads_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            files.append(path)
        files.sort(key=lambda p: p.stat().st_mtime)
        return files

    def run_once(self, *, obsidian: ObsidianClient, vault_path: Path) -> WatcherRunResult:
        state = self._load_state()
        candidates = self._discover_candidates()
        processed = 0
        skipped = 0
        failures = 0

        for path in candidates:
            key = str(path.resolve())
            signature = f"{path.stat().st_mtime_ns}:{path.stat().st_size}"
            if state.get(key) == signature:
                skipped += 1
                continue

            try:
                workflow = self.workflow.process(str(path), obsidian=obsidian)
                remember_email_workflow(workflow, vault_path=vault_path)
                processed += 1
                state[key] = signature
            except Exception:
                failures += 1

        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_state(state)
        return WatcherRunResult(
            processed=processed,
            skipped=skipped,
            failures=failures,
            state_path=str(self.state_path),
        )
