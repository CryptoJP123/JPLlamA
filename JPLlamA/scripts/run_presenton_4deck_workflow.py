from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.intelligence.knowledge_library import ensure_system_library, read_catalog
from app.main import ensure_presentation_in_vault, remember_presentation_knowledge
from app.ollama.client import OllamaClient, OllamaConfig
from app.presenton.client import PresentonClient, PresentonConfig


DECKS: List[Dict[str, str]] = [
    {"name": "DP World Documentation Centre Overview", "topic": "DP World Documentation Centre Overview", "query": "overview documentation centre dp world"},
    {"name": "DP World SSL", "topic": "DP World SSL", "query": "ssl dp world"},
    {"name": "DP World Global Standard Conditions", "topic": "DP World Global Standard Conditions", "query": "global standard conditions terms conditions dp world"},
    {"name": "DP World Switzerland", "topic": "DP World Switzerland", "query": "switzerland dp world"},
]


@dataclass
class DeckOutcome:
    deck: int
    topic: str
    status: str
    failure_stage: str = ""
    failure_reason: str = ""
    output_pptx: str = ""
    opened_in_powerpoint: bool = False
    vault_pptx: str = ""
    markdown_note: str = ""
    knowledge_updated: bool = False
    presentation_id: str = ""
    generation_seconds: float = 0.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_valid_pptx(path: Path) -> bool:
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".pptx":
        return False
    if path.stat().st_size < 128:
        return False
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
    except Exception:
        return False
    has_types = "[Content_Types].xml" in names
    has_presentation = "ppt/presentation.xml" in names
    has_slide = any(name.startswith("ppt/slides/slide") and name.endswith(".xml") for name in names)
    return has_types and has_presentation and has_slide


def _load_chunk_index(vault_path: Path) -> Dict[str, Any]:
    system_root = ensure_system_library(vault_path)
    chunk_index = system_root / "Reference Sources" / "DP World Freight Forwarding Documentation Centre" / "chunk_index.json"
    if not chunk_index.exists():
        raise RuntimeError(f"Reference chunk index not found: {chunk_index}")
    payload = json.loads(chunk_index.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(payload, dict):
        raise RuntimeError("Invalid chunk index payload")
    return payload


def _select_knowledge_snippets(chunk_index: Dict[str, Any], query: str, limit: int = 6) -> List[str]:
    chunks = chunk_index.get("chunks") if isinstance(chunk_index.get("chunks"), list) else []
    terms = [term for term in query.lower().split() if len(term) > 2]

    ranked: List[Dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text") or "")
        title = str(chunk.get("document_title") or "")
        haystack = f"{title}\n{text}".lower()
        score = sum(haystack.count(term) for term in terms)
        if score <= 0:
            continue
        ranked.append({"score": score, "text": text, "title": title, "source_url": str(chunk.get("source_url") or "")})

    ranked.sort(key=lambda item: item["score"], reverse=True)
    selected = ranked[:limit]
    if not selected:
        # Fallback to first chunks from local index only (still stored knowledge, no web access).
        for chunk in chunks[:limit]:
            if not isinstance(chunk, dict):
                continue
            selected.append(
                {
                    "score": 0,
                    "text": str(chunk.get("text") or ""),
                    "title": str(chunk.get("document_title") or ""),
                    "source_url": str(chunk.get("source_url") or ""),
                }
            )

    snippets: List[str] = []
    for idx, entry in enumerate(selected, start=1):
        preview = " ".join(str(entry.get("text") or "").split())[:420]
        title = str(entry.get("title") or "Untitled")
        source_url = str(entry.get("source_url") or "")
        snippets.append(f"{idx}. {title} | {source_url}\n{preview}")
    return snippets


def _build_outlines(slide_count: int = 4) -> List[Dict[str, str]]:
    base = [
        {"title": "Executive Summary", "content": "Key conclusions from stored DP World reference knowledge"},
        {"title": "Key Terms", "content": "Most relevant legal/commercial clauses and interpretation"},
        {"title": "Operational Implications", "content": "Execution risks and mitigation decisions"},
        {"title": "Recommended Actions", "content": "Decision gates and next steps"},
    ]
    return base[: max(1, min(slide_count, len(base)))]


def _open_in_powerpoint(pptx_path: Path, timeout_seconds: int = 25) -> bool:
    open_result = subprocess.run(
        ["open", "-a", "Microsoft PowerPoint", str(pptx_path)],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return open_result.returncode == 0


def _knowledge_updated(vault_path: Path, *, pptx_path: str, note_path: str) -> bool:
    entries = read_catalog(vault_path)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("stored_artifact_path") or "") == pptx_path and str(entry.get("vault_note_path") or "") == note_path:
            return True
    return False


def _compose_prompt(topic: str, snippets: List[str]) -> str:
    snippets_block = "\n\n".join(snippets)
    return (
        f"Create a concise executive 4-slide presentation titled '{topic}'. "
        "Use only the provided stored DP World Documentation Centre knowledge snippets. "
        "Do not use internet content. Keep bullets short and factual.\n\n"
        "Stored knowledge snippets:\n"
        f"{snippets_block}"
    )


def _run_single_deck(
    deck_number: int,
    topic: str,
    query: str,
    *,
    chunk_index: Dict[str, Any],
    ollama: OllamaClient,
    presenton: PresentonClient,
    output_dir: Path,
    vault_path: Path,
) -> DeckOutcome:
    started = time.monotonic()
    outcome = DeckOutcome(deck=deck_number, topic=topic, status="failed")

    try:
        snippets = _select_knowledge_snippets(chunk_index, query, limit=6)
        prompt = _compose_prompt(topic, snippets)

        content = ollama.chat(
            model=settings.text_model,
            messages=[
                {"role": "system", "content": "You write short executive slide content for presentations."},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )

        generated = presenton.build_presentation(
            content,
            outlines=_build_outlines(slide_count=4),
            output_dir=str(output_dir),
        )
        output_pptx = Path(str(generated.get("path") or "")).expanduser()
        outcome.presentation_id = str(generated.get("presentation_id") or "")
        outcome.output_pptx = str(output_pptx)

        if not _is_valid_pptx(output_pptx):
            outcome.failure_stage = "validate_output"
            outcome.failure_reason = f"Invalid PPTX: {output_pptx}"
            return outcome

        opened = _open_in_powerpoint(output_pptx)
        outcome.opened_in_powerpoint = opened
        if not opened:
            outcome.failure_stage = "open_powerpoint"
            outcome.failure_reason = f"Failed to open in Microsoft PowerPoint: {output_pptx}"
            return outcome

        vault_pptx = ensure_presentation_in_vault(
            str(output_pptx),
            vault_path=vault_path,
            preferred_filename=output_pptx.name,
            min_mtime=(generated.get("started_at") if isinstance(generated.get("started_at"), (int, float)) else None),
        )
        outcome.vault_pptx = str(vault_pptx)

        if not vault_pptx:
            outcome.failure_stage = "copy_to_vault"
            outcome.failure_reason = "No vault PPTX path returned"
            return outcome

        vault_path_obj = Path(vault_pptx).expanduser()
        if not _is_valid_pptx(vault_path_obj):
            outcome.failure_stage = "validate_vault_pptx"
            outcome.failure_reason = f"Invalid vault PPTX: {vault_path_obj}"
            return outcome

        if _sha256(output_pptx) != _sha256(vault_path_obj):
            outcome.failure_stage = "vault_integrity"
            outcome.failure_reason = "Vault PPTX differs from output PPTX"
            return outcome

        note_text = "\n".join(
            [
                f"topic: {topic}",
                "slides: 4",
                f"pptx: {vault_path_obj}",
                f"summary: {content[:300]}",
                f"speaker notes: {content[:1200]}",
                "",
                content,
            ]
        )
        stored = remember_presentation_knowledge(
            note_text,
            vault_path=vault_path,
            pptx_path=str(vault_path_obj),
            slide_count=4,
        )
        note_path = str(stored.get("path") or "")
        outcome.markdown_note = note_path
        if not note_path or not Path(note_path).exists():
            outcome.failure_stage = "markdown_note"
            outcome.failure_reason = "Markdown note was not created"
            return outcome

        outcome.knowledge_updated = _knowledge_updated(
            vault_path,
            pptx_path=str(vault_path_obj),
            note_path=note_path,
        )
        if not outcome.knowledge_updated:
            outcome.failure_stage = "knowledge_catalog"
            outcome.failure_reason = "Knowledge Catalog entry missing for this PPTX/note pair"
            return outcome

        outcome.status = "completed"
        outcome.generation_seconds = round(time.monotonic() - started, 2)
        return outcome
    except Exception as exc:
        outcome.failure_stage = outcome.failure_stage or "exception"
        outcome.failure_reason = str(exc)
        outcome.generation_seconds = round(time.monotonic() - started, 2)
        return outcome


def run_workflow(presenton_timeout: int, stop_on_first_failure: bool = True) -> Dict[str, Any]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = settings.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    vault_path = settings.obsidian_vault.expanduser()

    chunk_index = _load_chunk_index(vault_path)
    ollama = OllamaClient(
        OllamaConfig(
            base_url=settings.ollama_url,
            timeout_seconds=settings.ollama_timeout_seconds,
            max_retries=settings.ollama_max_retries,
            retry_backoff_seconds=settings.ollama_retry_backoff_seconds,
        )
    )
    presenton = PresentonClient(
        PresentonConfig(
            base_url=settings.presenton_url,
            username=settings.presenton_username,
            password=settings.presenton_password,
            template_name=settings.presenton_template,
            language=settings.presenton_language,
            timeout_seconds=presenton_timeout,
            max_retries=0,
            retry_backoff_seconds=settings.presenton_retry_backoff_seconds,
        )
    )

    manifest: Dict[str, Any] = {
        "status": "running",
        "stop_policy": "stop_on_first_failure" if stop_on_first_failure else "continue",
        "run_requirements": {
            "strictly_sequential": True,
            "single_presenton_job": True,
            "no_python_pptx": True,
            "no_fake_pptx": True,
            "stored_knowledge_only": True,
        },
        "decks": [deck["topic"] for deck in DECKS],
        "started_at": datetime.now().isoformat(),
        "results": [],
    }

    failed_deck: Optional[int] = None
    failure_stage: str = ""
    failure_detail: str = ""

    for index, deck in enumerate(DECKS, start=1):
        outcome = _run_single_deck(
            index,
            deck["topic"],
            deck["query"],
            chunk_index=chunk_index,
            ollama=ollama,
            presenton=presenton,
            output_dir=output_dir,
            vault_path=vault_path,
        )
        manifest["results"].append(
            {
                "deck": outcome.deck,
                "topic": outcome.topic,
                "status": outcome.status,
                "failure_stage": outcome.failure_stage,
                "failure_reason": outcome.failure_reason,
                "output_pptx": outcome.output_pptx,
                "opened_in_powerpoint": outcome.opened_in_powerpoint,
                "vault_pptx": outcome.vault_pptx,
                "markdown_note": outcome.markdown_note,
                "knowledge_updated": outcome.knowledge_updated,
                "presentation_id": outcome.presentation_id,
                "seconds": outcome.generation_seconds,
            }
        )

        if outcome.status != "completed":
            failed_deck = outcome.deck
            failure_stage = outcome.failure_stage
            failure_detail = outcome.failure_reason
            if stop_on_first_failure:
                break

    if failed_deck is None:
        manifest["status"] = "completed"
    else:
        manifest["status"] = "failed"
        manifest["failed_deck"] = failed_deck
        manifest["failed_stage"] = failure_stage
        manifest["failure_detail"] = failure_detail

    manifest["finished_at"] = datetime.now().isoformat()
    manifest_path = output_dir / f"workflow_presenton_4deck_manifest_{stamp}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strict sequential 4-deck Presenton workflow from stored DP World knowledge.")
    parser.add_argument("--presenton-timeout", type=int, default=180)
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    manifest = run_workflow(
        presenton_timeout=args.presenton_timeout,
        stop_on_first_failure=not args.continue_on_failure,
    )
    print(json.dumps(manifest, indent=2))

    if manifest.get("status") != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
