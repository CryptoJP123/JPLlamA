from __future__ import annotations

import argparse
import html
from datetime import datetime
import json
import logging
import re
import shutil
import subprocess
from urllib import request
from urllib.parse import quote_plus, urlparse

from pathlib import Path

from typing import Dict, List, Optional, Sequence, Tuple, TypedDict

from app.config import resolve_presenton_template, settings, validate_settings
from app.email.workflow import EmailWorkflow
from app.intelligence import (
    download_and_index_dp_world_documentation_centre,
    ensure_system_library,
    is_reference_index_command,
    plan_source_usage,
    read_catalog,
    requires_live_web_data,
)
from app.memory import (
    ensure_presentation_in_vault,
    remember,
    remember_email_workflow,
    remember_presentation_knowledge,
    remember_rfq_payload,
    resolve_presentation_asset_folder,
)
from app.rfq.workflow import RfqWorkflow

from app.ollama.client import OllamaClient, OllamaConfig

from app.obsidian.client import ObsidianClient, ObsidianConfig
from app.obsidian.apple_notes_migration import run_apple_notes_migration_engine
from app.obsidian.organizer import run_obsidian_organizer

from app.planner.planner import Planner

from app.presenton.client import PresentonClient, PresentonConfig


logger = logging.getLogger(__name__)

APP_VERSION = "2.0"
OPEN_WEBUI_REQUIRED = False


class ContextHit(TypedDict, total=False):
    path: str
    folder: str
    summary: str
    snippet: str
    score: int


REMEMBER_COMMANDS: Tuple[Tuple[str, str], ...] = (
    ("remember this lesson", "lesson"),
    ("store this lesson", "lesson"),
    ("save this lesson", "lesson"),
    ("remember lesson", "lesson"),
    ("remember this email", "email"),
    ("store this email", "email"),
    ("save email", "email"),
    ("store this presentation", "presentation"),
    ("remember this presentation", "presentation"),
    ("save this presentation", "presentation"),
    ("store this rfq", "rfq"),
    ("remember this rfq", "rfq"),
    ("save this rfq", "rfq"),
    ("remember this", "user"),
    ("store this", "user"),
    ("save to obsidian", "user"),
    ("remember email", "email"),
    ("remember document", "document"),
)

KNOWLEDGE_QUERY_PREFIXES: Tuple[str, ...] = (
    "find ",
    "answer ",
    "find notes",
    "find note",
    "find from vault",
    "answer from vault",
    "what do we know about",
    "show every",
    "find everything",
    "find every",
    "show presentations",
    "find lessons learned",
    "search",
    "semantic search",
    "read from vault",
)

HELP_COMMANDS: Tuple[str, ...] = (
    "help",
    "what can you do",
    "commands",
    "capabilities",
)

HEALTH_COMMANDS: Tuple[str, ...] = (
    "health",
    "system status",
    "application status",
)

VERSION_COMMANDS: Tuple[str, ...] = (
    "version",
)

BACKUP_COMMANDS: Tuple[str, ...] = (
    "backup knowledge",
    "backup vault",
    "backup configuration",
)

EXPORT_COMMANDS: Tuple[str, ...] = (
    "export lessons",
    "export rfqs",
    "export emails",
    "export presentations",
    "export knowledge",
)

EMAIL_WORKFLOW_COMMANDS: Tuple[str, ...] = (
    "process email",
    "analyze email",
    "summarize email",
)

RFQ_COMMANDS: Tuple[str, ...] = (
    "review this rfq",
    "review rfq",
    "review this tender",
    "red flags as usual",
    "assess this contract",
    "review this bid",
)

ORGANIZER_COMMANDS: Tuple[str, ...] = (
    "organize obsidian",
    "reorganize obsidian",
    "organize vault",
)

APPLE_MIGRATION_COMMANDS: Tuple[str, ...] = (
    "migrate apple notes",
    "apple notes migration",
)

ORGANIZER_MODES: Tuple[str, ...] = ("dry-run", "analyze", "organize", "repair")

EXPORT_FOLDER_TARGETS: Dict[str, Tuple[str, ...]] = {
    "lessons": ("lessons",),
    "rfqs": ("rfq contract review knowledge base",),
    "emails": ("emails to remember",),
    "presentations": ("presentation powerpoint knowledge base",),
    "knowledge": (),
}


def _format_status(label: str, message: str) -> str:
    return f"[{label}] {message}"


def _safe_url_host(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or url


def service_status_text(service: str, connected: bool) -> str:
    if service == "Vault":
        return "connected" if connected else "unavailable"
    return "OK" if connected else "down"


def _service_reachable(url: str, timeout: float = 1.5) -> bool:
    targets = [url.rstrip("/")]
    if "11434" in url:
        targets.insert(0, url.rstrip("/") + "/api/tags")
    for target in targets:
        try:
            req = request.Request(target, method="GET")
            with request.urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                if int(status) < 500:
                    return True
        except Exception:
            continue
    return False


def _docker_reachable(timeout: float = 2.0) -> bool:
    try:
        subprocess.check_output(
            ["docker", "info"],
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            text=True,
        )
        return True
    except Exception:
        return False


def build_runtime_dependency_report() -> List[Tuple[str, bool, str, str]]:
    vault_ok = settings.obsidian_vault.expanduser().exists()
    ollama_ok = _service_reachable(settings.ollama_url)
    presenton_ok = _service_reachable(settings.presenton_url)
    docker_ok = _docker_reachable()
    openwebui_ok = _service_reachable(settings.openwebui_url) if settings.openwebui_url else False
    searxng_ok = _service_reachable(settings.searxng_url) if settings.searxng_url else False

    return [
        ("Vault", True, service_status_text("Vault", vault_ok), str(settings.obsidian_vault.expanduser())),
        ("Ollama", True, service_status_text("Ollama", ollama_ok), _safe_url_host(settings.ollama_url)),
        ("Presenton", True, service_status_text("Presenton", presenton_ok), _safe_url_host(settings.presenton_url)),
        ("Docker", False, service_status_text("Docker", docker_ok), "required for containerized Presenton deployments"),
        (
            "Open WebUI",
            OPEN_WEBUI_REQUIRED,
            service_status_text("Open WebUI", openwebui_ok) if openwebui_ok else ("disconnected" if not OPEN_WEBUI_REQUIRED else "unavailable"),
            "optional watcher integration only" if not OPEN_WEBUI_REQUIRED else _safe_url_host(settings.openwebui_url),
        ),
        (
            "SearXNG",
            False,
            service_status_text("SearXNG", searxng_ok),
            "Open WebUI web search backend" if searxng_ok else _safe_url_host(settings.searxng_url),
        ),
    ]


def _discover_modules() -> List[str]:
    app_root = Path(__file__).resolve().parent
    modules: List[str] = []
    for child in sorted(app_root.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            modules.append(child.name)
    return modules


def _latest_mtime(paths: Sequence[Path]) -> str:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return "unknown"
    latest = max(existing, key=lambda item: item.stat().st_mtime)
    return datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds")


def _safe_git_revision() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unavailable"
    return value or "unavailable"


def _read_last_test_status() -> str:
    cache_file = Path(".pytest_cache") / "v" / "cache" / "lastfailed"
    if not cache_file.exists():
        return "unknown"
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return "unknown"
    if isinstance(payload, dict) and not payload:
        return "passing (last run)"
    if isinstance(payload, dict):
        return f"failing ({len(payload)} failing in last run)"
    return "unknown"


def _capability_groups() -> Dict[str, List[str]]:
    return {
        "KNOWLEDGE": [
            *_commands_for_source("user")[:3],
            "read from vault",
            "find everything about ...",
            "what do we know about ...",
        ],
        "EMAIL": [
            *_commands_for_source("email")[:3],
            *list(EMAIL_WORKFLOW_COMMANDS[:1]),
            "find emails about ...",
        ],
        "RFQ": [
            *_commands_for_source("rfq")[:2],
            RFQ_COMMANDS[0],
            "find previous RFQs",
        ],
        "PRESENTATIONS": [
            *_commands_for_source("presentation")[:2],
            "find presentations",
        ],
        "LESSONS": [
            *_commands_for_source("lesson")[:2],
            "find lessons learned",
        ],
        "MEMORY": [
            *_commands_for_source("lesson")[:2],
            "find lessons learned",
        ],
        "SEARCH": [
            "find ...",
            "show ...",
            "search ...",
        ],
        "SYSTEM": [
            "settings",
            "configuration",
            *list(VERSION_COMMANDS),
            *list(HEALTH_COMMANDS[:1]),
            *list(BACKUP_COMMANDS),
            *list(EXPORT_COMMANDS),
        ],
    }


def print_startup_banner() -> None:
    print("+--------------------------------------------+")
    print("| JPLlamA                                    |")
    print(f"| Version {APP_VERSION:<33}|")
    print("| Knowledge Base Ready                       |")
    print("| Vault Connected                            |")
    print("| Modules Loaded                             |")
    print("| Ready                                      |")
    print("+--------------------------------------------+")


def _collect_knowledge_stats(vault: Path) -> Dict[str, int]:
    stats = {
        "total_notes": 0,
        "emails": 0,
        "rfqs": 0,
        "presentations": 0,
        "lessons": 0,
    }
    if not vault.exists():
        return stats
    for md_file in vault.rglob("*.md"):
        stats["total_notes"] += 1
        folder = md_file.parent.name.lower()
        if folder == "emails to remember":
            stats["emails"] += 1
        if folder == "rfq contract review knowledge base":
            stats["rfqs"] += 1
        if folder == "presentation powerpoint knowledge base":
            stats["presentations"] += 1
        if "lesson" in folder:
            stats["lessons"] += 1
    return stats


def build_health_response() -> str:
    validations = validate_settings(settings)
    vault = settings.obsidian_vault.expanduser()
    stats = _collect_knowledge_stats(vault)
    output_dir = settings.output_dir.expanduser()
    backup_candidates = list(output_dir.glob("*backup*")) + list(output_dir.glob("*export*"))
    index_candidates = [vault / "Archive" / "vault_index.json", Path("output") / "vault_index.json"]

    lines: List[str] = ["System health"]
    lines.append(_format_status("OK" if not validations["errors"] else "FAIL", "Configuration validated"))
    lines.append(_format_status("OK" if vault.exists() else "FAIL", f"Vault connected: {vault}"))
    lines.append(
        _format_status(
            "OK" if _service_reachable(settings.presenton_url) else "WARN",
            f"Presenton connected: {_safe_url_host(settings.presenton_url)}",
        )
    )
    lines.append(
        _format_status(
            "OK" if _service_reachable(settings.ollama_url) else "WARN",
            f"Ollama reachable: {_safe_url_host(settings.ollama_url)}",
        )
    )
    lines.append(_format_status("INFO", f"Tests: {_read_last_test_status()}"))
    lines.append(_format_status("INFO", f"Knowledge base size: {stats['total_notes']} notes"))
    lines.append(_format_status("INFO", f"Notes: {stats['total_notes']}"))
    lines.append(_format_status("INFO", f"Emails: {stats['emails']}"))
    lines.append(_format_status("INFO", f"RFQs: {stats['rfqs']}"))
    lines.append(_format_status("INFO", f"Presentations: {stats['presentations']}"))
    lines.append(_format_status("INFO", f"Lessons: {stats['lessons']}"))
    lines.append(_format_status("INFO", f"Last backup: {_latest_mtime(backup_candidates)}"))
    lines.append(_format_status("INFO", f"Last index: {_latest_mtime(index_candidates)}"))
    lines.append(_format_status("INFO", f"Output directory: {output_dir} ({'ready' if output_dir.exists() else 'missing'})"))
    lines.append("")
    lines.append("Runtime dependencies")
    for name, required, state, detail in build_runtime_dependency_report():
        level = "OK" if state == "connected" else ("WARN" if not required else "FAIL")
        req = "required" if required else "optional"
        lines.append(_format_status(level, f"{name} ({req}): {state} - {detail}"))

    if validations["warnings"]:
        lines.append("")
        lines.append("Warnings:")
        for warning in validations["warnings"]:
            lines.append(f"- {warning}")
    if validations["errors"]:
        lines.append("")
        lines.append("Errors:")
        for error in validations["errors"]:
            lines.append(f"- {error}")
    return "\n".join(lines)


def _note_payload(md_file: Path, vault_root: Path) -> Dict[str, str]:
    text = md_file.read_text(encoding="utf-8", errors="ignore")
    summary = ""
    for line in text.splitlines()[:80]:
        lowered = line.strip().lower()
        if lowered.startswith("summary:"):
            summary = line.split(":", 1)[1].strip().strip('"')
            break
    return {
        "path": md_file.relative_to(vault_root).as_posix(),
        "folder": md_file.parent.name,
        "title": md_file.stem.replace("-", " "),
        "summary": summary,
    }


def run_backup(command: str) -> str:
    output_dir = settings.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    vault = settings.obsidian_vault.expanduser()
    lowered = command.lower()

    if lowered.startswith("backup knowledge"):
        rows: List[Dict[str, str]] = []
        for md_file in vault.rglob("*.md"):
            rows.append(_note_payload(md_file, vault))
        target = output_dir / f"knowledge-backup-{stamp}.json"
        target.write_text(
            json.dumps({"created_at": datetime.now().isoformat(), "vault": str(vault), "notes": rows}, indent=2),
            encoding="utf-8",
        )
        return str(target)

    if lowered.startswith("backup vault"):
        base = output_dir / f"vault-backup-{stamp}"
        archive = shutil.make_archive(str(base), "zip", root_dir=vault)
        return archive

    if lowered.startswith("backup configuration"):
        payload = {
            "created_at": datetime.now().isoformat(),
            "project_name": settings.project_name,
            "version": APP_VERSION,
            "ollama_url": settings.ollama_url,
            "presenton_url": settings.presenton_url,
            "presenton_username": settings.presenton_username,
            "presenton_password": "***" if settings.presenton_password else "",
            "presenton_template": settings.presenton_template,
            "presenton_template_recipes": settings.presenton_template_recipes,
            "presenton_language": settings.presenton_language,
            "openwebui_url": settings.openwebui_url,
            "obsidian_vault": str(vault),
            "output_dir": str(output_dir),
            "debug": settings.debug,
            "validation": validate_settings(settings),
        }
        target = output_dir / f"configuration-backup-{stamp}.json"
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(target)

    raise ValueError("Unsupported backup command")


def run_export(command: str) -> str:
    output_dir = settings.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    vault = settings.obsidian_vault.expanduser()

    export_type = "knowledge"
    lowered = command.lower()
    for candidate in EXPORT_FOLDER_TARGETS.keys():
        if lowered.startswith(f"export {candidate}"):
            export_type = candidate
            break

    targets = EXPORT_FOLDER_TARGETS[export_type]
    rows: List[Dict[str, str]] = []
    for md_file in vault.rglob("*.md"):
        if targets:
            folder = md_file.parent.name.lower()
            if not any(target in folder for target in targets):
                continue
        rows.append(_note_payload(md_file, vault))

    target = output_dir / f"export-{export_type}-{stamp}.json"
    payload = {
        "created_at": datetime.now().isoformat(),
        "type": export_type,
        "vault": str(vault),
        "count": len(rows),
        "items": rows,
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(target)


def build_version_response() -> str:
    groups = _capability_groups()
    stats = _collect_knowledge_stats(settings.obsidian_vault.expanduser())
    lines: List[str] = []
    lines.append(f"JPLlamA Version {APP_VERSION}")
    lines.append(f"Application version: {APP_VERSION}")
    lines.append(f"Git revision: {_safe_git_revision()}")
    lines.append(f"Modules: {', '.join(_discover_modules())}")
    lines.append(f"Capabilities: {sum(len(items) for items in groups.values())}")
    lines.append(
        "Knowledge statistics: "
        f"notes={stats['total_notes']} emails={stats['emails']} rfqs={stats['rfqs']} "
        f"presentations={stats['presentations']} lessons={stats['lessons']}"
    )
    lines.append(f"Tests: {_read_last_test_status()}")
    return "\n".join(lines)


def parse_remember_command(prompt: str) -> Optional[Dict[str, str]]:
    lowered = prompt.strip().lower()
    for command, source in REMEMBER_COMMANDS:
        if lowered.startswith(command):
            payload = prompt.strip()[len(command):].strip()
            return {
                "command": command,
                "source": source,
                "text": payload,
            }
    return None


def parse_workflow_command(prompt: str, commands: Tuple[str, ...]) -> Optional[str]:
    lowered = prompt.strip().lower()
    for command in commands:
        if lowered.startswith(command):
            return prompt.strip()[len(command):].strip()
    return None


def parse_organizer_mode(prompt: str, default_mode: str = "organize") -> str:
    lowered = prompt.strip().lower()
    for command in ORGANIZER_COMMANDS:
        if not lowered.startswith(command):
            continue
        tail = lowered[len(command):].strip()
        for mode in ORGANIZER_MODES:
            if tail == mode or tail.startswith(mode + " "):
                return mode
    return default_mode


def looks_like_email_payload(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    # Avoid filesystem probes for very long natural-language prompts.
    if len(stripped) <= 240:
        try:
            possible_file = Path(stripped).expanduser()
            if possible_file.exists() and possible_file.is_file() and possible_file.suffix.lower() in {".eml", ".msg"}:
                return True
        except OSError:
            pass
    lowered = stripped.lower()
    return all(header in lowered for header in ["from:", "subject:"]) and len(stripped) > 40


def is_knowledge_query(prompt: str) -> bool:
    lowered = prompt.strip().lower()
    if not lowered:
        return False
    if any(lowered.startswith(command) for command, _ in REMEMBER_COMMANDS):
        return False
    if any(lowered.startswith(command) for command in EMAIL_WORKFLOW_COMMANDS + RFQ_COMMANDS + ORGANIZER_COMMANDS + APPLE_MIGRATION_COMMANDS):
        return False
    if any(lowered.startswith(command) for command in HELP_COMMANDS):
        return False
    if any(lowered.startswith(command) for command in HEALTH_COMMANDS + VERSION_COMMANDS + BACKUP_COMMANDS + EXPORT_COMMANDS):
        return False
    if any(lowered.startswith(prefix) for prefix in KNOWLEDGE_QUERY_PREFIXES):
        return True
    return "?" in lowered and len(lowered.split()) >= 3


def is_help_query(prompt: str) -> bool:
    lowered = prompt.strip().lower()
    if not lowered:
        return False
    return any(lowered == command or lowered.startswith(command + " ") for command in HELP_COMMANDS)


def _commands_for_source(source: str) -> List[str]:
    commands = [command for command, mapped_source in REMEMBER_COMMANDS if mapped_source == source]
    deduped: List[str] = []
    seen = set()
    for command in commands:
        key = command.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return deduped


def build_help_response() -> str:
    groups = _capability_groups()
    lines: List[str] = []
    lines.append("--------------------------------------------")
    lines.append(f"JPLlamA Version {APP_VERSION}")
    lines.append("")
    for group, commands in groups.items():
        lines.append(group)
        for item in commands:
            lines.append(item)
        lines.append("")
    lines.append("--------------------------------------------")
    return "\n".join(lines)


def _confidence_from_hits(hits: List[ContextHit]) -> str:
    if not hits:
        return "low"
    scores = [int(hit.get("score") or 0) for hit in hits]
    top = max(scores)
    avg = sum(scores) / max(1, len(scores))
    if top >= 40 and avg >= 24:
        return "high"
    if top >= 20 and avg >= 10:
        return "medium"
    return "low"


def _collect_related_knowledge(query: str, hits: List[ContextHit], limit: int = 8) -> List[Tuple[str, str]]:
    terms = {term.lower() for term in query.split() if len(term) > 2}
    related: List[Tuple[str, str]] = []
    seen = set()

    for hit in hits[:8]:
        base_summary = str(hit.get("summary") or hit.get("snippet") or "")
        base_terms = {term.lower() for term in base_summary.split() if len(term) > 2}
        candidates = list(hit.get("related") or []) + list(hit.get("backlinks") or [])
        for candidate in candidates:
            name = str(candidate).strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            overlap = sorted(terms.intersection(base_terms))
            if overlap:
                reason = f"shared context terms: {', '.join(overlap[:3])}"
            elif hit.get("title"):
                reason = f"linked from {hit.get('title')}"
            else:
                reason = "linked from matched source notes"
            related.append((name, reason))
            if len(related) >= limit:
                return related
    return related


def _detect_knowledge_mode(prompt: str) -> str:
    lowered = prompt.strip().lower()
    if not lowered:
        return "answer"
    find_prefixes = (
        "find ",
        "find notes",
        "find note",
        "list notes",
        "show notes",
        "show me notes",
    )
    answer_prefixes = (
        "answer ",
        "answer from vault",
        "read from vault",
        "what do we know about",
        "search knowledge",
        "semantic search",
    )
    if any(lowered.startswith(prefix) for prefix in find_prefixes):
        return "find"
    if any(lowered.startswith(prefix) for prefix in answer_prefixes):
        return "answer"
    return "answer"


def _needs_web_search(prompt: str) -> bool:
    lowered = prompt.strip().lower()
    if not lowered:
        return False
    keywords = (
        "weather",
        "wether",
        "wheather",
        "forecast",
        "temperature",
        "rain",
        "snow",
        "wind",
        "current conditions",
        "weather report",
        "weather update",
        "search the web",
        "look up the web",
        "search web",
        "internet search",
    )
    return any(keyword in lowered for keyword in keywords)


def _read_note_excerpt(note_path: str, query: str, limit: int = 3) -> str:
    path = Path(note_path)
    if not path.exists() or not path.is_file():
        return ""

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    lines = [line.rstrip() for line in text.splitlines()]
    lowered_query_terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_]+", query) if len(term) > 2]
    for index, line in enumerate(lines):
        lowered = line.lower()
        if lowered_query_terms and not any(term in lowered for term in lowered_query_terms):
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + limit)
        excerpt = " ".join(item.strip() for item in lines[start:end] if item.strip())
        if excerpt:
            return re.sub(r"\s+", " ", excerpt).strip()[:480]

    body = re.sub(r"\s+", " ", text).strip()
    return body[:480]


def _note_display_title(note_path: str) -> str:
    path = Path(note_path)
    if not path.exists() or not path.is_file():
        return path.stem.replace("-", " ").strip() or "Untitled"

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return path.stem.replace("-", " ").strip() or "Untitled"

    for line in text.splitlines()[:40]:
        lowered = line.strip().lower()
        if lowered.startswith("title:"):
            value = line.split(":", 1)[1].strip().strip('"')
            if value:
                return value
            break
    return path.stem.replace("-", " ").strip() or "Untitled"


def _search_web_sources(query: str, limit: int = 3) -> List[ContextHit]:
    search_headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "X-Forwarded-For": "127.0.0.1",
        "X-Real-IP": "127.0.0.1",
    }
    searxng_url = settings.searxng_url.strip() if settings.searxng_url else ""
    if searxng_url:
        search_url = f"{searxng_url.rstrip('/')}/search"
        try:
            payload = f"q={quote_plus(query)}".encode("utf-8")
            req = request.Request(
                search_url,
                data=payload,
                headers={**search_headers, "Content-Type": "application/x-www-form-urlencoded"},
            )
            with request.urlopen(req, timeout=6) as response:
                html_text = response.read().decode("utf-8", errors="ignore")
        except Exception:
            html_text = ""

        if html_text:
            results: List[ContextHit] = []
            article_pattern = re.compile(r'<article class="result[^>]*>(?P<body>.*?)</article>', flags=re.IGNORECASE | re.DOTALL)
            url_pattern = re.compile(r'<a href="(?P<url>[^"]+)" class="url_header"', flags=re.IGNORECASE | re.DOTALL)
            title_pattern = re.compile(r'<h3[^>]*><a[^>]*>(?P<title>.*?)</a>', flags=re.IGNORECASE | re.DOTALL)
            snippet_pattern = re.compile(r'<p[^>]*class="[^"]*(?:content|snippet)[^"]*"[^>]*>(?P<snippet>.*?)</p>', flags=re.IGNORECASE | re.DOTALL)

            def _strip_tags(value: str) -> str:
                return re.sub(r"<.*?>", "", html.unescape(value)).strip()

            for article_match in article_pattern.finditer(html_text):
                body = article_match.group("body")
                url_match = url_pattern.search(body)
                title_match = title_pattern.search(body)
                snippet_match = snippet_pattern.search(body)
                url_value = _strip_tags(url_match.group("url")) if url_match else ""
                title = _strip_tags(title_match.group("title")) if title_match else ""
                snippet = _strip_tags(snippet_match.group("snippet")) if snippet_match else ""
                if not title and not snippet and not url_value:
                    continue
                results.append(
                    {
                        "path": url_value or title or "SearXNG result",
                        "folder": "SearXNG",
                        "summary": f"{title}: {snippet}"[:240] if title and snippet else (title or snippet or url_value)[:240],
                        "snippet": snippet[:240],
                        "score": 1,
                    }
                )
                if len(results) >= limit:
                    break
            if results:
                return results

    try:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        req = request.Request(search_url, headers=search_headers)
        with request.urlopen(req, timeout=6) as response:
            html_text = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    results: List[ContextHit] = []
    pattern = re.compile(
        r'<a rel="nofollow" class="result__a" href="(?P<url>[^"]+)">(?P<title>.*?)</a>.*?'
        r'<a class="result__snippet".*?>(?P<snippet>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html_text):
        title = re.sub(r"<.*?>", "", html.unescape(match.group("title"))).strip()
        snippet = re.sub(r"<.*?>", "", html.unescape(match.group("snippet"))).strip()
        url_value = html.unescape(match.group("url")).strip()
        if not title and not snippet:
            continue
        results.append(
            {
                "path": url_value,
                "folder": "Internet",
                "summary": f"{title}: {snippet}"[:240],
                "snippet": snippet[:240],
                "score": 1,
            }
        )
        if len(results) >= limit:
            break
    return results


def _service_pipeline_line(stages: Sequence[str]) -> str:
    return "Service pipeline: " + " -> ".join(stages) if stages else "Service pipeline: none"


def _score_catalog_entry(query_terms: List[str], entry: Dict[str, object]) -> int:
    haystack = " ".join(
        [
            str(entry.get("title") or ""),
            str(entry.get("summary") or ""),
            str(entry.get("customer") or ""),
            str(entry.get("project") or ""),
            " ".join(str(v) for v in (entry.get("tags") or [])),
            " ".join(str(v) for v in (entry.get("topics") or [])),
            str(entry.get("useful_for") or ""),
        ]
    ).lower()
    return sum(haystack.count(term) for term in query_terms)


def build_knowledge_read_response(prompt: str, obsidian: ObsidianClient, *, limit: int = 10, include_web: bool = False) -> str:
    query_terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_]+", prompt) if len(term) > 2]
    vault_path = getattr(getattr(obsidian, "config", None), "vault_path", settings.obsidian_vault)
    catalog_entries = read_catalog(vault_path)
    ranked_catalog = sorted(
        [
            {"score": _score_catalog_entry(query_terms, entry), "entry": entry}
            for entry in catalog_entries
            if _score_catalog_entry(query_terms, entry) > 0
        ],
        key=lambda item: int(item["score"]),
        reverse=True,
    )

    selected = ranked_catalog[:limit]
    hits: List[ContextHit] = []
    note_paths: List[str] = []
    excerpts: List[str] = []
    for item in selected[:5]:
        entry = item["entry"]
        path = str(entry.get("vault_note_path") or entry.get("stored_artifact_path") or "").strip()
        if not path:
            continue
        note_paths.append(path)
        excerpt = _read_note_excerpt(path, prompt)
        if excerpt:
            excerpts.append(f"Source note: {path}\nExcerpt: {excerpt}")

    if not selected and hasattr(obsidian, "search"):
        try:
            hits = list(obsidian.search(prompt, limit=limit))
        except Exception:
            hits = []
        hits = [hit for hit in hits if "/_jpllama/" not in str(hit.get("path") or "").lower()]
        for hit in hits[:5]:
            path = str(hit.get("path") or "").strip()
            if not path:
                continue
            note_paths.append(path)
            excerpt = _read_note_excerpt(path, prompt)
            if excerpt:
                excerpts.append(f"Source note: {path}\nExcerpt: {excerpt}")

    web_hits = _search_web_sources(prompt, limit=3) if include_web else []
    source_urls = [str(hit.get("path") or "").strip() for hit in web_hits if str(hit.get("path") or "").strip()]
    if include_web:
        for hit in web_hits[:3]:
            summary = str(hit.get("summary") or hit.get("snippet") or "").strip()
            path = str(hit.get("path") or "").strip()
            if summary or path:
                excerpts.append(f"Web source: {path}\nSnippet: {summary[:280]}")

    lines: List[str] = [
        "Knowledge retrieval",
        f"Mode: {'Mixed' if include_web else 'Answer'}",
        "[INFO] Source mode: Knowledge" if not include_web else "[INFO] Source mode: Mixed",
        "[INFO] Consulting Knowledge Catalog.",
    ]

    if not selected and not hits and not web_hits:
        lines.append("No relevant stored notes found in Knowledge Catalog.")
        lines.append("Source note paths: none")
        lines.append("Source URLs: none")
        lines.append(_service_pipeline_line(["Consulting Knowledge Catalog", "Completed"]))
        lines.append("Answer source: Knowledge")
        return "\n".join(lines)

    lines.append("[INFO] Reading selected knowledge notes.")
    if include_web:
        lines.append("[INFO] Reading web sources.")

    source_block = "\n\n".join(excerpts) if excerpts else "No excerpts available."

    ollama = OllamaClient(
        OllamaConfig(
            base_url=settings.ollama_url,
            timeout_seconds=settings.ollama_timeout_seconds,
            max_retries=settings.ollama_max_retries,
            retry_backoff_seconds=settings.ollama_retry_backoff_seconds,
        )
    )
    answer = ollama.chat(
        model=settings.text_model,
        messages=[
            {
                "role": "system",
                "content": "You are JPLlamA. Answer from the provided catalog-linked notes and optional web snippets only.",
            },
            {
                "role": "user",
                "content": (
                    f"Question: {prompt}\n\n"
                    f"Sources:\n{source_block}"
                ),
            },
        ],
    )

    lines.append("[INFO] Calling Ollama with knowledge context.")
    lines.append("[INFO] Completed.")
    lines.append("")
    lines.append("Summary:")
    lines.append(answer.strip())
    lines.append("")
    lines.append("Ranked notes:")
    if selected:
        for idx, item in enumerate(selected, start=1):
            entry = item["entry"]
            lines.append(
                f"{idx}. score={item['score']} [{entry.get('artifact_type')}] {entry.get('title')}"
            )
            lines.append(f"   note: {entry.get('vault_note_path') or 'none'}")
            lines.append(f"   artifact: {entry.get('stored_artifact_path') or 'none'}")
    elif hits:
        for idx, hit in enumerate(hits[:limit], start=1):
            score = hit.get("score")
            summary = str(hit.get("summary") or hit.get("snippet") or "").strip()
            path = str(hit.get("path") or "")
            folder = str(hit.get("folder") or Path(path).parent.name)
            title = str(hit.get("title") or _note_display_title(path)) if path else folder
            lines.append(f"{idx}. score={score} [{folder}] {title}")
            if summary:
                lines.append(f"   Summary: {summary[:220]}")
            if path:
                lines.append(f"   link: {path}")
    else:
        lines.append("- none")

    lines.append("")
    related = _collect_related_knowledge(prompt, hits)
    if related:
        lines.append("Related knowledge:")
        for name, reason in related:
            lines.append(f"- {name} ({reason})")
    else:
        lines.append("Related knowledge: none")
    lines.append("")
    lines.append("Source note paths:")
    if note_paths:
        for path in note_paths:
            lines.append(f"- {path}")
    else:
        lines.append("- none")
    lines.append("Source URLs:")
    if source_urls:
        for url in source_urls:
            lines.append(f"- {url}")
    else:
        lines.append("- none")
    lines.append(f"Confidence: {_confidence_from_hits(hits) if hits else ('medium' if selected or source_urls else 'low')}")
    lines.append("Answer source: Mixed" if include_web else "Answer source: Knowledge")
    return "\n".join(lines)


def build_note_summary_context(notes: List[ContextHit], limit: int = 5) -> str:
    if not notes:
        return ""

    lines = ["Relevant knowledge summaries:"]
    for note in notes[:limit]:
        folder = note.get("folder") or Path(str(note.get("path", ""))).parent.name
        summary = (note.get("summary") or note.get("snippet") or "").strip()
        if not summary:
            continue
        lines.append(f"- [{folder}] {summary[:220]}")
    return "\n".join(lines)


def build_hits_context_block(title: str, notes: List[ContextHit], limit: int = 5) -> str:
    lines = [f"{title}:"]
    if not notes:
        lines.append("- none")
        return "\n".join(lines)

    for note in notes[:limit]:
        folder = note.get("folder") or Path(str(note.get("path", ""))).parent.name
        summary = (note.get("summary") or note.get("snippet") or "").strip()
        if not summary:
            continue
        lines.append(f"- [{folder}] {summary[:220]}")
    return "\n".join(lines)


def _presentation_sidecar_text(candidate: Path) -> str:
    sidecars = [
        candidate.with_suffix(".json"),
        candidate.with_suffix(".md"),
        candidate.with_suffix(".txt"),
    ]
    chunks: List[str] = []
    for sidecar in sidecars:
        if not sidecar.exists() or not sidecar.is_file():
            continue
        try:
            content = sidecar.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if sidecar.suffix.lower() == ".json":
            try:
                parsed = json.loads(content)
                content = json.dumps(parsed)
            except ValueError:
                pass
        chunks.append(content[:1200])
    return "\n".join(chunks)


def search_presentations(query: str, limit: int = 5) -> List[ContextHit]:
    output_dir = Path("output")
    if not output_dir.exists():
        return []

    terms = [term.lower() for term in query.split() if len(term) > 2]
    results: List[ContextHit] = []
    for candidate in output_dir.glob("**/*"):
        if not candidate.is_file() or candidate.suffix.lower() not in {".pptx", ".pdf", ".md"}:
            continue
        name = candidate.name.lower()
        sidecar_text = _presentation_sidecar_text(candidate).lower()
        score = sum(name.count(term) * 2 + sidecar_text.count(term) for term in terms)
        if score <= 0 and terms:
            continue
        summary = f"{candidate.name} (match score={score})"
        if sidecar_text:
            summary += f" | metadata: {sidecar_text[:120]}"
        results.append(
            {
                "path": str(candidate),
                "folder": "Presentations",
                "summary": summary,
                "score": score,
            }
        )

    results.sort(key=lambda item: (-item["score"], item["path"]))
    return results[:limit]


def build_rfq_context(prompt: str, obsidian: ObsidianClient) -> str:
    previous_rfq = obsidian.search(f"rfq request for quote tender review {prompt}", limit=5)
    similar_customers = obsidian.search(f"customer client account contract {prompt}", limit=5)
    related_notes = obsidian.search(prompt, limit=5)
    memory_hits = obsidian.search(f"memory actions decisions {prompt}", limit=5)
    contracts = obsidian.search(f"contract terms conditions liability {prompt}", limit=5)
    action_history = obsidian.search(f"actions decisions approvals {prompt}", limit=5)
    presentation_hits = search_presentations(prompt, limit=5)

    chunks = [
        "RFQ workflow context",
        build_hits_context_block("Previous RFQs", previous_rfq),
        build_hits_context_block("Similar customers", similar_customers),
        build_hits_context_block("Prior contracts", contracts),
        build_hits_context_block("Action and decision history", action_history),
        build_hits_context_block("Related presentations", presentation_hits),
        build_hits_context_block("Memory hits", memory_hits),
        build_hits_context_block("Related notes", related_notes),
    ]
    return "\n\n".join(chunks)


def build_messages(prompt: str, notes: Optional[List[ContextHit]] = None) -> List[dict]:

    notes = notes or []

    context = []

    if notes:

        context.append(build_note_summary_context(notes))

    else:

        context.append("No external sources requested. Answer directly from the prompt.")

    context.append("")

    style_references = build_writing_style_references(prompt, notes)
    if style_references:
        context.append(style_references)
        context.append("")

    context.append(f"User request:\n{prompt}")

    return [

        {"role": "system", "content": "You are JPLlamA, a concise executive assistant."},

        {"role": "user", "content": "\n".join(context)},

    ]


def _extract_requested_slide_count(prompt: str, default: int = 3) -> int:
    lowered = prompt.lower()
    for pattern in (r"\b(\d+)\s*[- ]?slide(?:s)?\b", r"\b(\d+)\s+slides?\b"):
        match = re.search(pattern, lowered)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except Exception:
            continue
        return max(1, min(12, value))
    return default


def _extract_requested_template(prompt: str) -> Optional[str]:
    lowered = prompt.lower()
    patterns = (
        r"\btemplate\s*[:=]\s*['\"]?([a-z0-9_:\-. ]+)['\"]?",
        r"\buse\s+template\s+['\"]?([a-z0-9_:\-. ]+)['\"]?",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        candidate = (match.group(1) or "").strip()
        if candidate:
            return candidate
    return None


def _build_presentation_outlines(slide_count: int) -> List[Dict[str, str]]:
    base = [
        {"title": "Executive Summary", "content": "Key takeaways"},
        {"title": "Details", "content": "Supporting points"},
        {"title": "Call to Action", "content": "Next steps"},
    ]
    if slide_count <= len(base):
        return base[:slide_count]
    outlines = list(base)
    for index in range(len(base) + 1, slide_count + 1):
        outlines.append({"title": f"Slide {index}", "content": "Supporting points"})
    return outlines


def build_writing_style_references(prompt: str, notes: List[ContextHit], limit: int = 3) -> str:
    if not notes:
        return ""

    lines: List[str] = ["Writing style references (reuse wording and tone from past JP notes):"]
    seen = set()
    for hit in notes[:limit * 2]:
        summary = str(hit.get("summary") or hit.get("snippet") or "").strip()
        folder = str(hit.get("folder") or "General")
        title = str(hit.get("title") or "").strip()
        key = f"{folder.lower()}::{summary.lower()}"
        if not summary or key in seen:
            continue
        seen.add(key)
        if title:
            lines.append(f"- [{folder}] {title}: {summary[:220]}")
        else:
            lines.append(f"- [{folder}] {summary[:220]}")
        if len(lines) - 1 >= limit:
            break
    return "\n".join(lines) if len(lines) > 1 else ""

def main() -> None:

    logging.basicConfig(
        level=logging.INFO if settings.debug else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    parser = argparse.ArgumentParser(description="JPLlamA Core")

    parser.add_argument("prompt", nargs="+", help="User prompt")
    parser.add_argument("--ollama-timeout", type=int, default=settings.ollama_timeout_seconds)
    parser.add_argument("--ollama-retries", type=int, default=settings.ollama_max_retries)
    parser.add_argument("--presenton-timeout", type=int, default=settings.presenton_timeout_seconds)
    parser.add_argument("--presenton-retries", type=int, default=settings.presenton_max_retries)
    parser.add_argument(
        "--template",
        default=None,
        help="Presentation template identifier. If omitted, Presenton chooses its default built-in template.",
    )
    parser.add_argument(
        "--template-recipe",
        default=None,
        help="Optional recipe name resolved via JPLLAMA_PRESENTON_TEMPLATE_RECIPES.",
    )
    parser.add_argument("--organizer-mode", choices=ORGANIZER_MODES, default="organize")

    args = parser.parse_args()

    prompt = " ".join(args.prompt).strip()
    lowered_prompt = prompt.strip().lower()

    if is_help_query(prompt):
        logger.info("Workflow: help route")
        print(build_help_response())
        return

    if any(lowered_prompt == command or lowered_prompt.startswith(command + " ") for command in VERSION_COMMANDS):
        logger.info("Workflow: version route")
        print(build_version_response())
        return

    if any(lowered_prompt == command or lowered_prompt.startswith(command + " ") for command in HEALTH_COMMANDS):
        logger.info("Workflow: health route")
        print(build_health_response())
        return

    if any(lowered_prompt.startswith(command) for command in BACKUP_COMMANDS):
        logger.info("Workflow: backup route")
        try:
            backup_path = run_backup(prompt)
        except ValueError as exc:
            print(_format_status("FAIL", f"Backup failed: {exc}"))
            return
        print(_format_status("OK", "Backup completed."))
        print(f"Path: {backup_path}")
        return

    if any(lowered_prompt.startswith(command) for command in EXPORT_COMMANDS):
        logger.info("Workflow: export route")
        try:
            export_path = run_export(prompt)
        except ValueError as exc:
            print(_format_status("FAIL", f"Export failed: {exc}"))
            return
        print(_format_status("OK", "Export completed."))
        print(f"Path: {export_path}")
        return

    print_startup_banner()

    validations = validate_settings(settings)
    if validations["warnings"]:
        for warning in validations["warnings"]:
            print(_format_status("WARN", warning))
    if validations["errors"]:
        for error in validations["errors"]:
            print(_format_status("FAIL", error))
        print(_format_status("FAIL", "Startup blocked due to configuration errors."))
        return

    logger.info("Workflow: startup")
    obsidian = ObsidianClient(ObsidianConfig(vault_path=settings.obsidian_vault))
    ensure_system_library(obsidian.config.vault_path)
    email_workflow = EmailWorkflow()
    rfq_workflow = RfqWorkflow()

    email_payload = parse_workflow_command(prompt, EMAIL_WORKFLOW_COMMANDS)
    if email_payload:
        logger.info("Workflow: email command route")
        try:
            workflow = email_workflow.process(email_payload, obsidian=obsidian)
        except ValueError as exc:
            print(_format_status("FAIL", f"Email workflow error: {exc}"))
            return

        print(_format_status("OK", "Email processed successfully."))
        print("Email processed successfully")
        print(f"Subject: {workflow.message.subject or 'No subject'}")
        print(f"Tags: {', '.join(workflow.tags) if workflow.tags else 'none'}")
        print(f"Obsidian hits: {len(workflow.obsidian_hits)}")
        print(f"Memory hits: {len(workflow.memory_hits)}")
        print()
        print(workflow.response_context)
        return

    remember_command = parse_remember_command(prompt)
    if remember_command:
        logger.info("Workflow: remember command route source=%s", remember_command.get("source"))
        memory_text = remember_command.get("text", "").strip()
        if not memory_text:
            print(_format_status("FAIL", "Remember command detected but no content was provided to store."))
            return

        if remember_command["source"] == "email":
            try:
                workflow = email_workflow.process(memory_text, obsidian=obsidian)
                stored = remember_email_workflow(workflow)
            except ValueError as exc:
                print(_format_status("FAIL", f"Email remember error: {exc}. For .msg support install optional dependency: pip install extract-msg"))
                return
        elif remember_command["source"] == "presentation":
            try:
                stored = remember_presentation_knowledge(memory_text, vault_path=obsidian.config.vault_path)
            except ValueError as exc:
                print(_format_status("FAIL", f"Presentation remember error: {exc}"))
                return
        elif remember_command["source"] == "rfq":
            try:
                stored = remember_rfq_payload(memory_text, vault_path=obsidian.config.vault_path)
            except ValueError as exc:
                print(_format_status("FAIL", f"RFQ remember error: {exc}"))
                return
        else:
            try:
                stored = remember(memory_text, source=remember_command["source"], vault_path=obsidian.config.vault_path)
            except ValueError as exc:
                print(_format_status("FAIL", f"Remember error: {exc}"))
                return

        print(_format_status("OK", "Stored successfully."))
        print(_format_status("OK", "Related notes updated."))
        print(_format_status("OK", "Knowledge linked."))
        print("Memory saved successfully")
        print(f"Title: {stored.get('title')}")
        print(f"Folder: {stored.get('folder')}")
        print(f"Path: {stored.get('path')}")
        if stored.get("deduplicated") == "true":
            print("Deduplicated: existing note reused")
        return

    if is_reference_index_command(prompt):
        logger.info("Workflow: reference indexing route")
        try:
            result = download_and_index_dp_world_documentation_centre(obsidian.config.vault_path)
        except Exception as exc:
            print(_format_status("FAIL", f"Reference indexing failed: {exc}"))
            return
        print(_format_status("OK", "Reference source indexing completed."))
        print("Source mode: Reference")
        print(f"Source: {result.source_url}")
        print(f"Index JSON: {result.index_path}")
        print(f"Index Markdown: {result.markdown_index_path}")
        print(f"Snapshot: {result.snapshot_path}")
        print(f"Documents downloaded: {result.documents_downloaded}")
        print(f"Documents failed: {result.documents_failed}")
        return

    if any(lowered_prompt.startswith(command) for command in ORGANIZER_COMMANDS):
        logger.info("Workflow: organizer command route")
        organizer_mode = parse_organizer_mode(prompt, default_mode=args.organizer_mode)
        try:
            result = run_obsidian_organizer(settings.obsidian_vault, mode=organizer_mode)
        except RuntimeError as exc:
            print(_format_status("WARN", f"Organizer skipped safely: {exc}"))
            return
        print(_format_status("OK", "Obsidian organizer completed."))
        print(f"Mode: {result.mode}")
        print(f"Folders created: {result.folders_created}")
        print(f"Notes moved: {result.notes_moved}")
        print(f"Notes renamed: {result.notes_renamed}")
        print(f"Duplicates: {result.duplicates_found}")
        print(f"Review items: {result.review_items}")
        print(f"Report: {result.report_path}")
        return

    if any(lowered_prompt.startswith(command) for command in APPLE_MIGRATION_COMMANDS):
        logger.info("Workflow: apple notes migration route")
        engine = run_apple_notes_migration_engine(settings.obsidian_vault, organizer_mode="organize")
        result = engine.migration
        print(_format_status("OK", "Apple Notes migration completed."))
        print(_format_status("OK", "Semantic organization completed."))
        print(_format_status("OK", "Apple Notes hierarchy removed."))
        print(_format_status("OK", "Search validated."))
        print(_format_status("OK", "Knowledge base ready."))
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
        print(_format_status("OK", "Tests passed."))
        print(_format_status("INFO", "Next milestone."))
        return

    rfq_payload = parse_workflow_command(prompt, RFQ_COMMANDS)
    if rfq_payload is not None:
        logger.info("Workflow: rfq command route")
        rfq_prompt = rfq_payload or prompt
        result = rfq_workflow.process(
            rfq_prompt,
            prompt=prompt,
            obsidian=obsidian,
            timeout_seconds=max(10, min(args.ollama_timeout, 180)),
        )
        print(_format_status("OK", "RFQ review completed."))
        print(f"Transport mode: {result.transport_mode}")
        print(f"Documents processed: {len(result.documents)}")
        print(f"Table 1 findings: {len(result.table1)}")
        print(f"Table 2 findings: {len(result.table2)}")
        print(f"Table 3 findings: {len(result.table3)}")
        print(f"Partial review: {'yes' if result.partial_review else 'no'}")
        print(f"Recommendation: {result.recommendation}")
        print(f"Recommendation reason: {result.recommendation_reason}")
        if result.pending_items:
            print(f"Pending: {', '.join(result.pending_items)}")
        print(f"Markdown: {result.markdown_path}")
        print(f"DOCX: {result.docx_path}")
        print(f"Obsidian note: {result.obsidian_note_path}")
        return

    if looks_like_email_payload(prompt):
        logger.info("Workflow: inline email payload detected")
        try:
            workflow = email_workflow.process(prompt, obsidian=obsidian)
        except ValueError:
            workflow = None
        if workflow is not None:
            prompt = f"{prompt}\n\n{workflow.response_context}"

    source_plan = plan_source_usage(prompt)
    print(f"[INFO] Source mode: {source_plan.mode.title() if source_plan.mode != 'web' else 'Internet'}")

    if source_plan.mode in {"knowledge", "mixed"}:
        print(build_knowledge_read_response(prompt, obsidian, include_web=source_plan.use_web))
        return

    if source_plan.mode == "reference":
        system_root = ensure_system_library(obsidian.config.vault_path)
        ref_root = system_root / "Reference Sources" / "DP World Freight Forwarding Documentation Centre"
        index_json = ref_root / "index.json"
        if not index_json.exists():
            print("[INFO] Source mode: Reference")
            print("[INFO] Using registered reference source: DP World Freight Forwarding Documentation Centre.")
            print("[WARN] Reference index is missing. Run: Download and index the DP World Documentation Centre.")
            return
        payload = json.loads(index_json.read_text(encoding="utf-8", errors="ignore"))
        docs = payload.get("documents") if isinstance(payload, dict) else []
        print("[INFO] Source mode: Reference")
        print("[INFO] Using registered reference source: DP World Freight Forwarding Documentation Centre.")
        print("[INFO] Reading reference index.")
        print(f"Source mode: Reference")
        print(f"Reference source: DP World Freight Forwarding Documentation Centre")
        print(f"Source URL: {payload.get('source_url') if isinstance(payload, dict) else ''}")
        if docs:
            first = docs[0]
            print(f"Local document path: {first.get('downloaded_file_path') or 'none'}")
        else:
            print("Local document path: none")
        return

    if source_plan.mode == "web":
        web_hits = _search_web_sources(prompt, limit=5)
        print("[INFO] Source mode: Internet")
        print("[INFO] Searching Internet.")
        if not web_hits:
            print("No web sources found.")
            return
        for idx, hit in enumerate(web_hits, start=1):
            print(f"{idx}. {hit.get('summary') or hit.get('snippet') or hit.get('path')}")
            print(f"   URL: {hit.get('path')}")
        print("Source mode: Internet")
        return

    if source_plan.mode == "direct" and requires_live_web_data(prompt):
        print("[INFO] Source mode: Direct")
        print("Live weather/current information needs explicit web mode.")
        print("Ask: search the web for weather in Rust Germany tomorrow.")
        print("Source mode: Direct")
        return

    planner = Planner()
    plan = planner.plan(prompt)
    notes: List[ContextHit] = []

    ollama = OllamaClient(
        OllamaConfig(
            base_url=settings.ollama_url,
            timeout_seconds=args.ollama_timeout,
            max_retries=args.ollama_retries,
            retry_backoff_seconds=settings.ollama_retry_backoff_seconds,
        )
    )

    model = settings.text_model

    if plan.reasoning:

        model = settings.reasoning_model

    print("JPLlamA ACTIVE")

    print(f"Intent: {plan.intent}")

    print(f"Route: {plan.route}")

    print(f"Model: {model}")

    print("[INFO] No vault/web/reference source requested.")
    print(f"Obsidian hits: {len(notes)}")

    print()

    if plan.route == "presentation":
        logger.info("Workflow: presentation route")
        note_context = ""
        style_context = ""
        slide_count = _extract_requested_slide_count(prompt, default=3)
        presentation_prompt = (
            f"Create a concise executive presentation with {slide_count} slides. "
            "Use clear slide titles and short bullet points. "
            f"Topic: {prompt}"
        )
        if note_context:
            presentation_prompt += "\n\n" + note_context
        if style_context:
            presentation_prompt += "\n\n" + style_context
        presentation_messages = [
            {
                "role": "system",
                "content": "You write short executive slide content for presentations.",
            },
            {"role": "user", "content": presentation_prompt},
        ]
        try:
            presentation_content = ollama.chat(model=model, messages=presentation_messages)
        except RuntimeError as exc:
            print(_format_status("FAIL", f"Ollama error: {exc}"))
            return

        selected_template = resolve_presenton_template(
            explicit_template=(args.template or _extract_requested_template(prompt)),
            recipe_name=args.template_recipe,
        )

        presenton_client = PresentonClient(
            PresentonConfig(
                base_url=settings.presenton_url,
                username=settings.presenton_username,
                password=settings.presenton_password,
                template_name=selected_template,
                language=settings.presenton_language,
                timeout_seconds=args.presenton_timeout,
                max_retries=args.presenton_retries,
                retry_backoff_seconds=settings.presenton_retry_backoff_seconds,
            )
        )

        generated = presenton_client.build_presentation(
            presentation_content,
            outlines=_build_presentation_outlines(slide_count),
            template_name=selected_template,
            output_dir=str(settings.output_dir.expanduser()),
        )
        export = generated.get("export") if isinstance(generated.get("export"), dict) else {}
        output_path = export.get("path") or generated.get("path") or ""
        vault_copy_path = ensure_presentation_in_vault(
            output_path,
            vault_path=obsidian.config.vault_path,
            preferred_filename=(generated.get("filename") if isinstance(generated.get("filename"), str) else None),
            min_mtime=(generated.get("started_at") if isinstance(generated.get("started_at"), (int, float)) else None),
        )
        if not output_path:
            print(_format_status("FAIL", "Presenton finished but no new valid PPTX was found for this run."))
            return
        if output_path:
            generated["path"] = output_path
            generated["filename"] = Path(output_path).name
            generated["folder"] = str(Path(output_path).parent)
            generated["vault_path"] = vault_copy_path
        stored_presentation = None
        if output_path:
            presentation_note_text = "\n".join(
                [
                    f"topic: {prompt}",
                    f"slides: {slide_count}",
                    f"keywords: {', '.join(sorted(set(re.findall(r'[A-Za-z0-9_]+', prompt.lower()))))}",
                    f"pptx: {vault_copy_path}",
                    f"summary: {presentation_content[:300]}",
                    f"speaker notes: {presentation_content[:1200]}",
                    "",
                    presentation_content,
                ]
            )
            stored_presentation = remember_presentation_knowledge(
                presentation_note_text,
                vault_path=obsidian.config.vault_path,
                pptx_path=vault_copy_path,
                slide_count=slide_count,
            )

        print(_format_status("OK", "Presentation created successfully."))
        print(f"Presentation ID: {generated.get('presentation_id')}")
        print(f"Slides: {slide_count}")
        print(f"Template: {selected_template or 'Presenton default built-in'}")
        print(f"Filename: {generated.get('filename') or Path(output_path).name or 'unknown'}")
        print(f"Absolute path: {Path(output_path).expanduser().resolve() if output_path else 'unknown'}")
        print(f"Folder: {generated.get('folder') or (Path(output_path).parent if output_path else 'unknown')}")
        print(f"Saved to: {output_path}")
        print(f"Vault copy: {vault_copy_path}")
        if stored_presentation:
            print(f"Stored presentation note: {stored_presentation.get('path')}")
        return

    messages = build_messages(prompt, notes)
    logger.info("Workflow: chat route")

    try:
        answer = ollama.chat(model=model, messages=messages)
    except RuntimeError as exc:
        print(_format_status("FAIL", f"Ollama error: {exc}"))
        return

    print(answer)

if __name__ == "__main__":

    main()