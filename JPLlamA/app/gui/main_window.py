from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import html
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib import request as urllib_request

try:
    import resource
except Exception:  # pragma: no cover
    resource = None

from app.config import resolve_presenton_template, settings, validate_settings
from app.email.workflow import EmailWorkflow
from app.intelligence import (
    download_and_index_dp_world_documentation_centre,
    ensure_system_library,
    is_reference_index_command,
    plan_source_usage,
    requires_live_web_data,
)
from app.main import (
    APP_VERSION,
    EMAIL_WORKFLOW_COMMANDS,
    RFQ_COMMANDS,
    build_health_response,
    build_help_response,
    build_knowledge_read_response,
    build_messages,
    build_version_response,
    looks_like_email_payload,
    parse_remember_command,
    parse_workflow_command,
    service_status_text,
)
from app.memory import (
    ensure_presentation_in_vault,
    remember,
    remember_email_workflow,
    remember_presentation_knowledge,
    remember_rfq_payload,
    resolve_presentation_asset_folder,
)
from app.obsidian.client import ObsidianClient, ObsidianConfig
from app.ollama.client import OllamaClient, OllamaConfig
from app.planner.planner import Planner
from app.presenton.client import PresentonClient, PresentonConfig
from app.rfq.workflow import RfqWorkflow

logger = logging.getLogger(__name__)
OPEN_WEBUI_REQUIRED = False

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PNG = ASSETS_DIR / "jpllama-logo-1024.png"
LOGO_ICNS = ASSETS_DIR / "jpllama-logo.icns"

BUTTON_TO_COMMAND: Dict[str, str] = {
    "Help": "help",
    "Health": "health",
    "Version": "version",
    "Remember This": "remember this",
    "Store Email": "store this email",
    "Review RFQ": "review this rfq",
    "Store Presentation": "store this presentation",
    "Read from Vault": "read from vault",
}

FILE_TYPE_ACTIONS: Dict[str, List[str]] = {
    "rfq": ["Review RFQ", "Store RFQ", "Find Similar RFQs"],
    "email": ["Store Email", "Summarize Email", "Remember", "Find Related Emails"],
    "presentation": ["Store Presentation", "Summarize Presentation", "Find Similar Presentations"],
    "knowledge": ["Remember", "Search Knowledge", "Store Document"],
    "image": ["Remember", "Search Knowledge"],
    "document": ["Remember", "Store Document", "Search Knowledge"],
}

MODERN_STYLESHEET = """
QMainWindow { background: #050a12; color: #d7e7ff; }
QWidget { font-family: "SF Pro Display", "Segoe UI", "Helvetica Neue", sans-serif; color: #d7e7ff; font-size: 13px; }
QFrame#MainPanel { border: 1px solid #1a3556; border-radius: 16px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #081222, stop:1 #0c1524); }
QFrame#SidebarPanel { border: 1px solid #18324f; border-radius: 16px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #07111d, stop:1 #0a1320); }
QFrame#PromptPanel { border: 1px solid #1f3f66; border-radius: 16px; background: rgba(6, 14, 25, 0.94); }
QFrame#ArtifactCard { border: 1px solid #22446c; border-radius: 14px; background: #09131f; }
QFrame#ArtifactCard:hover { border-color: #41c8ff; }
QLabel#SectionTitle { color: #eaf4ff; font-size: 12px; font-weight: 700; letter-spacing: 1px; }
QLabel#SmallMuted { color: #89a3c5; }
QTextBrowser, QPlainTextEdit { background: #09131f; border: 1px solid #224669; border-radius: 12px; color: #e7f3ff; padding: 10px; }
QListWidget { background: #09131f; border: 1px solid #224669; border-radius: 12px; }
QListWidget::item { padding: 7px 9px; border-radius: 8px; }
QListWidget::item:selected { background: #17375b; }
QPushButton { background: #0d1f33; border: 1px solid #2a5a8f; color: #dff2ff; border-radius: 10px; padding: 8px 14px; font-weight: 600; }
QPushButton:hover { background: #163554; border-color: #41c8ff; }
QPushButton#RunButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #11b08f, stop:1 #33c45c); border: 1px solid #56ef97; color: #ffffff; }
QPushButton#RunButton:hover { background: #24bf89; }
QPushButton#StopButton { background: #2a1520; border: 1px solid #c64f5f; color: #ffd8dd; }
QPushButton#StopButton:hover { background: #43202e; }
QToolButton { background: #0d1f33; border: 1px solid #2a5a8f; color: #dff2ff; border-radius: 10px; padding: 7px 10px; }
QToolButton:hover { background: #163554; border-color: #41c8ff; }
QLineEdit, QPlainTextEdit { background: #09131f; border: 1px solid #224669; border-radius: 12px; color: #e7f3ff; padding: 10px; }
QProgressBar { border: 1px solid #2f6a73; border-radius: 8px; background: #08131b; text-align: center; color: #dff6ff; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y1:0, stop:0 #24b2bd, stop:1 #43d982); border-radius: 6px; }
QStatusBar { background: #050911; border-top: 1px solid #1f3c57; color: #b7cbde; }
QFrame#DropZone { border: 2px dashed #2d7ab9; border-radius: 14px; background: #071426; }
QFrame#DropZone[dragging="true"] { border: 2px solid #39d6ff; background: #0b223d; }
QScrollArea { border: none; background: transparent; }
"""

RETRO_STYLESHEET = """
QMainWindow { background: #060b12; color: #baf7ea; }
QWidget { font-family: Menlo, Monaco, "Courier New", monospace; font-size: 13px; color: #baf7ea; }
QFrame#MainPanel { border: 1px solid #1f6a77; border-radius: 8px; background: #0a121b; }
QFrame#SidebarPanel { border: 1px solid #1c4f59; border-radius: 8px; background: #081119; }
QLabel#SectionTitle { color: #7fe8d5; font-size: 12px; font-weight: 700; letter-spacing: 1px; }
QLabel#SmallMuted { color: #88b8c1; }
QTextBrowser, QPlainTextEdit, QLineEdit { background: #0d1823; color: #d9fff7; border: 1px solid #2aaeb7; border-radius: 6px; padding: 8px; }
QListWidget { background: #0b1620; border: 1px solid #235a65; border-radius: 6px; }
QPushButton { background: #102836; color: #cffcf3; border: 1px solid #2aaeb7; border-radius: 6px; padding: 7px 10px; }
QPushButton#RunButton { background: #16a085; border: 1px solid #6ef0d4; color: #042c26; }
QProgressBar { border: 1px solid #29727f; border-radius: 6px; background: #0a141d; color: #d9fff7; text-align: center; }
QProgressBar::chunk { background: #21bca2; }
QStatusBar { background: #050a10; color: #ffbf6f; border-top: 1px solid #2aaeb7; }
QFrame#DropZone { border: 2px dashed #2aaeb7; border-radius: 10px; background: #08111b; }
QFrame#DropZone[dragging="true"] { border: 2px solid #7df4e2; background: #103246; }
"""

CLASSIC_STYLESHEET = """
QMainWindow { background: #111111; color: #e7e7e7; }
QWidget { font-family: Menlo, Monaco, "Courier New", monospace; font-size: 13px; color: #e7e7e7; }
QFrame#MainPanel, QFrame#SidebarPanel { border: 1px solid #3f3f3f; border-radius: 8px; background: #1a1a1a; }
QLabel#SectionTitle { color: #f2f2f2; font-size: 12px; font-weight: 700; }
QLabel#SmallMuted { color: #b9b9b9; }
QTextBrowser, QPlainTextEdit, QLineEdit { background: #141414; color: #f2f2f2; border: 1px solid #4b4b4b; border-radius: 6px; padding: 8px; }
QListWidget { background: #141414; border: 1px solid #4b4b4b; border-radius: 6px; }
QPushButton { background: #262626; color: #f2f2f2; border: 1px solid #5e5e5e; border-radius: 6px; padding: 7px 10px; }
QPushButton#RunButton { background: #2f5f2f; border: 1px solid #6ea86e; }
QProgressBar { border: 1px solid #4f4f4f; border-radius: 6px; background: #121212; color: #f2f2f2; text-align: center; }
QProgressBar::chunk { background: #57a757; }
QStatusBar { background: #0f0f0f; color: #dfdfdf; border-top: 1px solid #3f3f3f; }
QFrame#DropZone { border: 2px dashed #5d5d5d; border-radius: 10px; background: #151515; }
QFrame#DropZone[dragging="true"] { border: 2px solid #9d9d9d; background: #202020; }
"""

THEME_STYLES = {
    "Modern": MODERN_STYLESHEET,
    "Retro Futuristic": RETRO_STYLESHEET,
    "Classic Console": CLASSIC_STYLESHEET,
}


def _configure_qt_plugin_path() -> None:
    existing_platform = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH", "").strip()
    if existing_platform:
        return
    try:
        from PySide6 import __file__ as pyside_file  # type: ignore
    except Exception:
        return

    qt_plugins = Path(pyside_file).resolve().parent / "Qt" / "plugins"
    source_platforms = qt_plugins / "platforms"
    if not source_platforms.exists():
        return

    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(source_platforms)
    os.environ["QT_PLUGIN_PATH"] = str(qt_plugins)


def detect_content_type(payload: str) -> str:
    value = payload.strip()
    if not value:
        return "document"
    lower = value.lower()
    if lower.startswith("from:") or lower.endswith(".eml") or lower.endswith(".msg"):
        return "email"
    if any(word in lower for word in ("rfq", "tender", "proposal", "bid")):
        return "rfq"
    if any(lower.endswith(ext) for ext in (".ppt", ".pptx", ".key")):
        return "presentation"
    if any(lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".tiff")):
        return "image"
    if any(lower.endswith(ext) for ext in (".md", ".txt", ".doc", ".docx", ".pdf", ".xlsx", ".xls", ".zip")):
        return "document"
    if Path(value).exists() and Path(value).is_dir():
        return "knowledge"
    if lower.startswith("http://") or lower.startswith("https://"):
        return "knowledge"
    return "document"


def suggest_actions_for_type(content_type: str) -> List[str]:
    return FILE_TYPE_ACTIONS.get(content_type, ["Remember", "Search Knowledge"])


def detect_drop_primary_type(items: Sequence[str]) -> str:
    if not items:
        return "document"
    hits = {"rfq": 0, "email": 0, "presentation": 0, "knowledge": 0, "image": 0, "document": 0}
    for value in items:
        hits[detect_content_type(value)] += 1
    ordered = sorted(hits.items(), key=lambda pair: pair[1], reverse=True)
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1] and ordered[0][1] > 0:
        return "document"
    return ordered[0][0]


def compose_prompt(button_label: str, payload: str) -> str:
    command = BUTTON_TO_COMMAND.get(button_label, "").strip()
    if not command:
        raise ValueError(f"Unsupported button action: {button_label}")
    clean_payload = payload.strip()
    if command in {"help", "health", "version"}:
        return command
    if not clean_payload:
        raise ValueError(f"{button_label} requires input in the search box.")
    return f"{command} {clean_payload}"


def _extract_customer_project(text: str) -> Tuple[str, str]:
    customer = "Unknown"
    project = "Unknown"

    customer_match = re.search(r"\bcustomer\s*[:\-]\s*([^\n,]+)", text, flags=re.IGNORECASE)
    project_match = re.search(r"\bproject\s*[:\-]\s*([^\n,]+)", text, flags=re.IGNORECASE)
    if customer_match:
        customer = customer_match.group(1).strip()[:80]
    if project_match:
        project = project_match.group(1).strip()[:80]

    if customer == "Unknown":
        known_customers = ("dp world", "bayer", "cargo partner", "rkc", "tdk", "apple", "acme")
        lower = text.lower()
        for name in known_customers:
            if name in lower:
                customer = name.title()
                break

    if project == "Unknown":
        project_terms = re.findall(
            r"\b(project|rfq|tender|migration|rollout|presentation)\s+([A-Za-z0-9\- ]{2,50})",
            text,
            flags=re.IGNORECASE,
        )
        if project_terms:
            project = project_terms[0][1].strip().title()

    return customer or "Unknown", project or "Unknown"


def _safe_git_revision() -> str:
    repo_root = Path(__file__).resolve().parents[2]
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


def _service_reachable(url: str, timeout: float = 1.5) -> bool:
    targets = [url.rstrip("/")]
    if "11434" in url:
        targets.insert(0, url.rstrip("/") + "/api/tags")
    for target in targets:
        try:
            req = urllib_request.Request(target, method="GET")
            with urllib_request.urlopen(req, timeout=timeout) as response:
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


def _extract_requested_slide_count(prompt: str, default: int = 3) -> int:
    lower = prompt.lower()
    patterns = [
        r"\b(\d+)\s*[- ]?slide(?:s)?\b",
        r"\b(\d+)\s+slides?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
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


def _discover_modules() -> List[str]:
    app_root = Path(__file__).resolve().parents[1]
    modules: List[str] = []
    for child in sorted(app_root.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            modules.append(child.name)
    return modules


@dataclass
class GuiBackend:
    obsidian: ObsidianClient
    email_workflow: EmailWorkflow
    rfq_workflow: RfqWorkflow


@dataclass
class ExecutionHooks:
    on_status: Optional[Callable[[str, Dict[str, Any]], None]] = None
    on_log: Optional[Callable[[str, str], None]] = None
    cancel_check: Optional[Callable[[], bool]] = None


def _emit_status(hooks: Optional[ExecutionHooks], stage: str, **payload: Any) -> None:
    if hooks and hooks.on_status:
        hooks.on_status(stage, payload)


def _emit_log(hooks: Optional[ExecutionHooks], service: str, message: str) -> None:
    if hooks and hooks.on_log:
        hooks.on_log(service, message)


def _raise_if_cancelled(hooks: Optional[ExecutionHooks]) -> None:
    if hooks and hooks.cancel_check and hooks.cancel_check():
        raise RuntimeError("Operation cancelled by user.")


def create_backend() -> GuiBackend:
    obsidian = ObsidianClient(ObsidianConfig(vault_path=settings.obsidian_vault))
    ensure_system_library(obsidian.config.vault_path)
    return GuiBackend(obsidian=obsidian, email_workflow=EmailWorkflow(), rfq_workflow=RfqWorkflow())


def _render_stored_response(stored: Dict[str, str]) -> str:
    lines = [
        "[OK] Stored successfully.",
        "[OK] Related notes updated.",
        "[OK] Knowledge linked.",
        f"Title: {stored.get('title', '')}",
        f"Folder: {stored.get('folder', '')}",
        f"Path: {stored.get('path', '')}",
    ]
    if stored.get("deduplicated") == "true":
        lines.append("Deduplicated: existing note reused")
    return "\n".join(lines)


def _render_email_response(workflow) -> str:
    lines = [
        "[OK] Email processed successfully.",
        f"Subject: {workflow.message.subject or 'No subject'}",
        f"Tags: {', '.join(workflow.tags) if workflow.tags else 'none'}",
        f"Detected customers: {', '.join(workflow.entities.customers) if workflow.entities.customers else 'none'}",
        f"Detected projects: {', '.join(workflow.entities.projects) if workflow.entities.projects else 'none'}",
        f"Detected deadlines: {', '.join(workflow.entities.deadlines) if workflow.entities.deadlines else 'none'}",
        f"Obsidian hits: {len(workflow.obsidian_hits)}",
        f"Memory hits: {len(workflow.memory_hits)}",
        "",
        workflow.response_context.strip(),
    ]
    return "\n".join(lines)


def _run_general_chat(prompt: str, backend: GuiBackend, hooks: Optional[ExecutionHooks] = None) -> str:
    _emit_status(hooks, "source_mode", service="system", progress=12, mode="Direct")
    notes: List[Dict[str, Any]] = []
    plan = Planner().plan(prompt)
    model = settings.reasoning_model if plan.reasoning else settings.text_model
    _emit_status(hooks, "building_context", service="system", progress=24)
    _emit_log(hooks, "system", "Source mode: Direct. No vault/web/reference source requested.")

    ollama = OllamaClient(
        OllamaConfig(
            base_url=settings.ollama_url,
            timeout_seconds=settings.ollama_timeout_seconds,
            max_retries=settings.ollama_max_retries,
            retry_backoff_seconds=settings.ollama_retry_backoff_seconds,
        )
    )
    messages = build_messages(prompt, notes)
    _emit_status(hooks, "calling_ollama", service="ollama", progress=42)

    def _on_ollama_status(stage: str, payload: Dict[str, Any]) -> None:
        stage_to_progress = {
            "connecting": 46,
            "loading_model": 52,
            "generating_response": 62,
            "streaming_tokens": 74,
            "completed": 88,
        }
        mapped = stage_to_progress.get(stage, 62)
        safe_payload = dict(payload or {})
        safe_payload.pop("service", None)
        _emit_status(hooks, stage, service="ollama", progress=mapped, **safe_payload)
        if stage == "streaming_tokens":
            token_count = int(payload.get("token_count") or 0)
            if token_count > 0 and token_count % 30 == 0:
                _emit_log(hooks, "ollama", f"Streaming tokens: {token_count}")

    answer = ollama.chat(
        model=model,
        messages=messages,
        stream=True,
        on_status=_on_ollama_status,
        cancel_check=(hooks.cancel_check if hooks else None),
    )
    _emit_status(hooks, "completed", service="ollama", progress=100)
    return "\n".join([
        "Source mode: Direct",
        "[OK] AI response generated.",
        f"Model: {model}",
        f"Obsidian hits: {len(notes)}",
        "",
        answer,
    ])


def _presenton_error_message(exc: Exception) -> str:
    reason = str(exc).strip() or "Unknown error"
    return "\n".join(
        [
            "[FAIL] Presentation service unavailable.",
            "Service: Presenton",
            "Attempt: create -> prepare -> generate -> export",
            f"Reason: {reason}",
            "Possible solution: Ensure Presenton is running and reachable.",
            "Retry: Click Retry.",
            "Open Presenton: Verify the service endpoint in browser.",
            "Open Settings: Verify Presenton URL and credentials.",
        ]
    )


def _run_presentation_route(prompt: str, backend: GuiBackend, hooks: Optional[ExecutionHooks] = None) -> str:
    _emit_status(hooks, "source_mode", service="system", progress=12, mode="Direct")
    _emit_status(hooks, "building_context", service="system", progress=20)
    slide_count = _extract_requested_slide_count(prompt, default=3)
    outlines = _build_presentation_outlines(slide_count)
    try:
        ollama = OllamaClient(
            OllamaConfig(
                base_url=settings.ollama_url,
                timeout_seconds=settings.ollama_timeout_seconds,
                max_retries=settings.ollama_max_retries,
                retry_backoff_seconds=settings.ollama_retry_backoff_seconds,
            )
        )

        _emit_status(hooks, "calling_ollama", service="ollama", progress=30)
        presentation_messages = [
            {"role": "system", "content": "You write short executive slide content for presentations."},
            {
                "role": "user",
                "content": (
                    f"Create a concise executive presentation with {slide_count} slides. "
                    "Use clear slide titles and short bullets.\n"
                    f"Topic: {prompt}\n"
                ),
            },
        ]

        def _on_presentation_ollama_status(stage: str, payload: Dict[str, Any]) -> None:
            safe_payload = dict(payload or {})
            safe_payload.pop("service", None)
            _emit_status(
                hooks,
                stage,
                service="ollama",
                progress={
                    "connecting": 34,
                    "loading_model": 40,
                    "generating_response": 48,
                    "streaming_tokens": 56,
                    "completed": 60,
                }.get(stage, 48),
                **safe_payload,
            )

        presentation_content = ollama.chat(
            model=settings.text_model,
            messages=presentation_messages,
            stream=True,
            on_status=_on_presentation_ollama_status,
            cancel_check=(hooks.cancel_check if hooks else None),
        )

        selected_template = resolve_presenton_template(
            explicit_template=_extract_requested_template(prompt),
        )

        presenton = PresentonClient(
            PresentonConfig(
                base_url=settings.presenton_url,
                username=settings.presenton_username,
                password=settings.presenton_password,
                template_name=selected_template,
                language=settings.presenton_language,
                timeout_seconds=settings.presenton_timeout_seconds,
                max_retries=settings.presenton_max_retries,
                retry_backoff_seconds=settings.presenton_retry_backoff_seconds,
            )
        )
        _emit_status(hooks, "calling_presenton", service="presenton", progress=66)
        presenton_stage_map = {
            "connecting": 70,
            "accepted": 74,
            "generating": 80,
            "rendering": 86,
            "exporting": 92,
            "finished": 100,
        }

        def _on_presenton_status(stage: str, payload: Dict[str, Any]) -> None:
            safe_payload = dict(payload or {})
            safe_payload.pop("service", None)
            _emit_status(
                hooks,
                stage,
                service="presenton",
                progress=presenton_stage_map.get(stage, 84),
                **safe_payload,
            )

        generated = presenton.build_presentation(
            presentation_content,
            outlines=outlines,
            template_name=selected_template,
            output_dir=str(settings.output_dir.expanduser()),
            on_status=_on_presenton_status,
            cancel_check=(hooks.cancel_check if hooks else None),
        )
        export = generated.get("export") if isinstance(generated.get("export"), dict) else {}
        output_path = export.get("path") or generated.get("path") or ""
        vault_copy_path = ensure_presentation_in_vault(
            output_path,
            vault_path=settings.obsidian_vault,
            preferred_filename=(generated.get("filename") if isinstance(generated.get("filename"), str) else None),
            min_mtime=(generated.get("started_at") if isinstance(generated.get("started_at"), (int, float)) else None),
        )
        if not output_path:
            raise RuntimeError("Presenton finished but no new valid PPTX was found for this run.")
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
                vault_path=settings.obsidian_vault,
                pptx_path=vault_copy_path,
                slide_count=slide_count,
            )
        _emit_status(hooks, "completed", service="presenton", progress=100)
        return "\n".join(
            [
                "[OK] Presentation created successfully.",
                f"Presentation ID: {generated.get('presentation_id')}",
                f"Slides: {slide_count}",
                f"Filename: {generated.get('filename') or Path(out_path).name or 'unknown'}",
                f"Absolute path: {Path(output_path).expanduser().resolve() if output_path else 'unknown'}",
                f"Folder: {generated.get('folder') or (Path(output_path).parent if output_path else 'unknown')}",
                f"Path: {output_path}",
                f"Vault copy: {vault_copy_path}",
                *( [f"Stored presentation note: {stored_presentation.get('path')}"] if stored_presentation else [] ),
                "Source mode: Direct",
                "Source notes considered: 0",
            ]
        )
    except Exception as exc:
        _emit_status(hooks, "failed", service="presenton", progress=100, reason=str(exc))
        return _presenton_error_message(exc)


def _is_explicit_knowledge_prompt(prompt: str) -> bool:
    lowered = prompt.strip().lower()
    if not lowered:
        return False
    explicit_prefixes = (
        "read from vault",
        "search knowledge",
        "what do we know about",
        "semantic search",
        "find lessons learned",
        "find presentations",
        "find emails",
    )
    if any(lowered.startswith(prefix) for prefix in explicit_prefixes):
        return True
    return " vault" in f" {lowered}" or "knowledge" in lowered


def _is_sensitive_vault_lookup_prompt(prompt: str) -> bool:
    lowered = prompt.lower()
    if not any(token in lowered for token in ("password", "passcode", "credential", "credentials", "pwd")):
        return False
    return any(token in lowered for token in ("note", "notes", "vault", "obsidian", "find", "search"))


def _run_sensitive_vault_lookup(prompt: str, backend: GuiBackend, hooks: Optional[ExecutionHooks] = None) -> str:
    _emit_status(hooks, "searching_vault", service="vault", progress=20)
    lowered = prompt.lower()
    target_match = re.search(r"\bfor\s+([a-z0-9 _'\-]{2,80}?)(?:\s+in\b|[?.!,]|$)", lowered)
    target = target_match.group(1).strip(" .?!") if target_match else ""
    query = f"{target} password credentials".strip()
    hits = backend.obsidian.search(query if query else prompt, limit=12)
    _emit_status(hooks, "searching_related_notes", service="vault", progress=42)

    patterns = [
        re.compile(r"\bpassword\b\s*[:=\-]\s*(.+)", flags=re.IGNORECASE),
        re.compile(r"\bpasscode\b\s*[:=\-]\s*(.+)", flags=re.IGNORECASE),
        re.compile(r"\bpwd\b\s*[:=\-]\s*(.+)", flags=re.IGNORECASE),
    ]

    for hit in hits:
        path_value = str(hit.get("path") or "").strip()
        if not path_value:
            continue
        note_path = Path(path_value).expanduser()
        if not note_path.exists() or not note_path.is_file():
            continue
        try:
            text = note_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        text_lower = text.lower()
        if target and target not in text_lower and target not in note_path.name.lower():
            continue
        for line in text.splitlines():
            for pattern in patterns:
                match = pattern.search(line)
                if not match:
                    continue
                value = match.group(1).strip()
                if not value:
                    continue
                _emit_status(hooks, "completed", service="vault", progress=100)
                return "\n".join(
                    [
                        "[OK] Vault credential lookup completed.",
                        f"Result: {value}",
                        f"Source note path: {note_path}",
                        "Confidence: high",
                    ]
                )

    _emit_status(hooks, "completed", service="vault", progress=100)
    return "\n".join(
        [
            "[INFO] Vault credential lookup completed.",
            "Result: not found in vault notes.",
            "Source note path: none",
            "Confidence: low",
        ]
    )


def execute_prompt(prompt: str, backend: GuiBackend, hooks: Optional[ExecutionHooks] = None) -> str:
    lowered = prompt.strip().lower()
    if not lowered:
        raise ValueError("Please enter a request.")

    _raise_if_cancelled(hooks)

    if lowered == "help" or lowered.startswith("help "):
        _emit_status(hooks, "completed", service="system", progress=100)
        return build_help_response()
    if lowered == "health" or lowered.startswith("health "):
        _emit_status(hooks, "completed", service="system", progress=100)
        return build_health_response()
    if lowered == "version" or lowered.startswith("version "):
        _emit_status(hooks, "completed", service="system", progress=100)
        return build_version_response()

    remember_command = parse_remember_command(prompt)
    if remember_command:
        _emit_status(hooks, "writing_memory", service="memory", progress=44)
        memory_text = remember_command.get("text", "").strip()
        if not memory_text:
            raise ValueError("Remember command detected but no content was provided to store.")

        source = remember_command.get("source", "user")
        if source == "email":
            workflow = backend.email_workflow.process(memory_text, obsidian=backend.obsidian)
            stored = remember_email_workflow(workflow, vault_path=backend.obsidian.config.vault_path)
        elif source == "presentation":
            stored = remember_presentation_knowledge(memory_text, vault_path=backend.obsidian.config.vault_path)
        elif source == "rfq":
            stored = remember_rfq_payload(memory_text, vault_path=backend.obsidian.config.vault_path)
        else:
            stored = remember(memory_text, source=source, vault_path=backend.obsidian.config.vault_path)
        _emit_status(hooks, "completed", service="memory", progress=100)
        return _render_stored_response(stored)

    email_payload = parse_workflow_command(prompt, EMAIL_WORKFLOW_COMMANDS)
    if email_payload is not None:
        _emit_status(hooks, "reading_email", service="email", progress=24)
        workflow = backend.email_workflow.process(email_payload or prompt, obsidian=backend.obsidian)
        _emit_status(hooks, "completed", service="email", progress=100)
        return _render_email_response(workflow)

    rfq_payload = parse_workflow_command(prompt, RFQ_COMMANDS)
    if rfq_payload is not None:
        _emit_status(hooks, "reading_pdf", service="rfq", progress=18)
        result = backend.rfq_workflow.process(
            rfq_payload or prompt,
            prompt=prompt,
            obsidian=backend.obsidian,
            timeout_seconds=max(10, min(settings.ollama_timeout_seconds, 180)),
        )
        _emit_status(hooks, "completed", service="rfq", progress=100)
        lines = [
            "[OK] RFQ review completed.",
            f"Transport mode: {result.transport_mode}",
            f"Documents processed: {len(result.documents)}",
            f"Table 1 findings: {len(result.table1)}",
            f"Table 2 findings: {len(result.table2)}",
            f"Table 3 findings: {len(result.table3)}",
            f"Partial review: {'yes' if result.partial_review else 'no'}",
            f"Recommendation: {result.recommendation}",
            f"Recommendation reason: {result.recommendation_reason}",
            f"Markdown: {result.markdown_path}",
            f"DOCX: {result.docx_path}",
            f"Obsidian note: {result.obsidian_note_path}",
        ]
        if result.pending_items:
            lines.append(f"Pending: {', '.join(result.pending_items)}")
        return "\n".join(lines)

    if _is_sensitive_vault_lookup_prompt(prompt):
        return _run_sensitive_vault_lookup(prompt, backend, hooks=hooks)

    if is_reference_index_command(prompt):
        _emit_status(hooks, "source_mode", service="reference", progress=20, mode="Reference")
        result = download_and_index_dp_world_documentation_centre(backend.obsidian.config.vault_path)
        _emit_status(hooks, "completed", service="reference", progress=100)
        return "\n".join(
            [
                "Source mode: Reference",
                "[OK] Reference source indexing completed.",
                f"Index JSON: {result.index_path}",
                f"Index Markdown: {result.markdown_index_path}",
                f"Snapshot: {result.snapshot_path}",
                f"Documents downloaded: {result.documents_downloaded}",
                f"Documents failed: {result.documents_failed}",
            ]
        )

    source_plan = plan_source_usage(prompt)
    if source_plan.mode in {"knowledge", "mixed"}:
        _emit_status(hooks, "source_mode", service="knowledge", progress=20, mode="Knowledge")
        include_web = source_plan.use_web
        response = build_knowledge_read_response(prompt, backend.obsidian, include_web=include_web)
        _emit_status(hooks, "completed", service="knowledge", progress=100)
        mode_label = "Mixed" if include_web else "Knowledge"
        return f"Source mode: {mode_label}\n" + response

    if source_plan.mode == "reference":
        system_root = ensure_system_library(backend.obsidian.config.vault_path)
        index_path = system_root / "Reference Sources" / "DP World Freight Forwarding Documentation Centre" / "index.json"
        _emit_status(hooks, "source_mode", service="reference", progress=20, mode="Reference")
        if not index_path.exists():
            return "\n".join(
                [
                    "Source mode: Reference",
                    "[WARN] DP World reference index is missing.",
                    "Run: Download and index the DP World Documentation Centre.",
                ]
            )
        return "\n".join(
            [
                "Source mode: Reference",
                "[INFO] Using registered reference source: DP World Freight Forwarding Documentation Centre.",
                f"Reference index: {index_path}",
            ]
        )

    if source_plan.mode == "web":
        _emit_status(hooks, "source_mode", service="knowledge", progress=20, mode="Internet")
        response = build_knowledge_read_response(prompt, backend.obsidian, include_web=True)
        _emit_status(hooks, "completed", service="knowledge", progress=100)
        return "Source mode: Internet\n" + response

    if source_plan.mode == "direct" and requires_live_web_data(prompt):
        return "\n".join(
            [
                "Source mode: Direct",
                "Live weather/current information requires explicit web mode.",
                "Ask: search the web for weather in Rust Germany tomorrow.",
            ]
        )

    plan = Planner().plan(prompt)
    if plan.route == "presentation":
        return _run_presentation_route(prompt, backend) if hooks is None else _run_presentation_route(prompt, backend, hooks=hooks)

    if looks_like_email_payload(prompt):
        _emit_status(hooks, "reading_email", service="email", progress=24)
        workflow = backend.email_workflow.process(prompt, obsidian=backend.obsidian)
        _emit_status(hooks, "completed", service="email", progress=100)
        return _render_email_response(workflow)

    return _run_general_chat(prompt, backend) if hooks is None else _run_general_chat(prompt, backend, hooks=hooks)


def _timeout_threshold_for_workflow(route: str, service: str, web_search: bool = False) -> int:
    if route == "presentation" or service == "presenton":
        # Measured workflow runs show multi-minute waits during model generation
        # and Presenton prepare/render phases.
        return 420
    if web_search:
        return 90
    return 30


try:
    _configure_qt_plugin_path()

    from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, Qt, QTimer, QUrl, Signal
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap, QTextCursor, QTextDocument
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGraphicsOpacityEffect,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QScrollArea,
        QPushButton,
        QSizePolicy,
        QSplitter,
        QStatusBar,
        QTextBrowser,
        QVBoxLayout,
        QToolButton,
        QWidget,
    )

    class WorkerSignals(QObject):
        progress = Signal(str, int, int, str, object)
        stream = Signal(str, str, object)
        success = Signal(str, str, object)
        error = Signal(str, object)

    class CommandWorker(QRunnable):
        def __init__(self, run_id: str, prompt: str, backend: GuiBackend, cancel_event: threading.Event):
            super().__init__()
            self.run_id = run_id
            self.prompt = prompt
            self.backend = backend
            self.cancel_event = cancel_event
            self.signals = WorkerSignals()

        def _is_cancelled(self) -> bool:
            return self.cancel_event.is_set()

        def run(self) -> None:
            try:
                self.signals.progress.emit("Preparing prompt", 10, 0, "~5s", {"run_id": self.run_id, "service": "system"})

                def _on_status(stage: str, payload: Dict[str, Any]) -> None:
                    service = str(payload.get("service") or "system")
                    progress = int(payload.get("progress") or 50)
                    files_processed = int(payload.get("files_processed") or 0)
                    eta = str(payload.get("eta") or "--")
                    self.signals.progress.emit(stage, progress, files_processed, eta, {"run_id": self.run_id, **payload})
                    if stage in {
                        "searching_vault",
                        "searching_obsidian",
                        "searching_related_notes",
                        "calling_ollama",
                        "calling_presenton",
                        "reading_email",
                        "reading_pdf",
                        "writing_memory",
                        "knowledge_found",
                        "no_relevant_knowledge",
                        "completed",
                        "failed",
                    }:
                        msg = _stage_to_human(stage, payload)
                        self.signals.stream.emit(service, msg, {"run_id": self.run_id, **payload})

                def _on_log(service: str, message: str) -> None:
                    self.signals.stream.emit(service, message, {"run_id": self.run_id, "log": True})

                hooks = ExecutionHooks(on_status=_on_status, on_log=_on_log, cancel_check=self._is_cancelled)
                result = execute_prompt(self.prompt, self.backend, hooks=hooks)
                if self._is_cancelled():
                    raise RuntimeError("Operation cancelled by user.")
                self.signals.progress.emit("Rendering response", 92, 0, "~1s", {"run_id": self.run_id, "service": "system"})
                self.signals.success.emit(self.prompt, result, {"run_id": self.run_id})
            except Exception as exc:
                self.signals.error.emit(str(exc), {"run_id": self.run_id})

    class CommandInput(QPlainTextEdit):
        submitRequested = Signal()
        historyNavigate = Signal(int)

        def keyPressEvent(self, event: QKeyEvent) -> None:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (event.modifiers() & Qt.ControlModifier):
                self.submitRequested.emit()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() == Qt.NoModifier:
                self.submitRequested.emit()
                return
            if event.key() == Qt.Key_Up and (event.modifiers() & Qt.AltModifier):
                self.historyNavigate.emit(-1)
                return
            if event.key() == Qt.Key_Down and (event.modifiers() & Qt.AltModifier):
                self.historyNavigate.emit(1)
                return
            super().keyPressEvent(event)

        def insertFromMimeData(self, source) -> None:  # type: ignore[override]
            if source and source.hasUrls():
                paths = []
                for url in source.urls():
                    if url.isLocalFile():
                        paths.append(url.toLocalFile())
                if paths:
                    self.insertPlainText("\n".join(paths))
                    return
            super().insertFromMimeData(source)

    def _stage_to_human(stage: str, payload: Optional[Dict[str, Any]] = None) -> str:
        payload = payload or {}
        mapping = {
            "preparing_prompt": "Preparing prompt.",
            "searching_internet": "Searching the web.",
            "searching_vault": "Searching vault.",
            "searching_obsidian": "Searching Obsidian.",
            "searching_memory": "Searching memory.",
            "searching_related_notes": "Searching related notes.",
            "ranking_results": "Ranking results.",
            "building_context": "Building context.",
            "reading_email": "Reading email.",
            "reading_pdf": "Reading PDF.",
            "calling_ollama": "Calling Ollama.",
            "connecting": "Connecting.",
            "loading_model": "Loading model.",
            "generating_response": "Generating response.",
            "streaming_tokens": "Streaming tokens.",
            "calling_presenton": "Calling Presenton.",
            "accepted": "Accepted.",
            "generating": "Generating presentation content (this can take a few minutes).",
            "rendering": "Rendering slide output (usually the longest wait).",
            "exporting": "Writing PowerPoint.",
            "writing_memory": "Saving note.",
            "knowledge_found": "Knowledge found.",
            "no_relevant_knowledge": "No relevant knowledge found.",
            "completed": "Completed.",
        }
        base = mapping.get(stage, stage.replace("_", " ").capitalize() + ".")
        current_stage = str(payload.get("current_stage") or "").strip().lower()
        if current_stage == "prepare":
            base = "Preparing slide structure on Presenton (can take 1-3 min)."
        elif current_stage == "stream-timeout":
            base = "Finalizing presentation export (waiting for file handoff)."
        elif current_stage == "template":
            base = "Loading presentation template."
        current_slide = payload.get("current_slide")
        if current_slide not in (None, ""):
            base = f"{base} Slide {current_slide}."
        return base

    def build_logo_pixmap(size: int) -> QPixmap:
        if LOGO_PNG.exists():
            return QPixmap(str(LOGO_PNG)).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        bg = QColor("#09131f")
        cyan = QColor("#34d8d4")
        amber = QColor("#f0b25f")

        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(0, 0, size, size, size * 0.15, size * 0.15)

        trace_pen = QPen(cyan, max(1, size // 40))
        painter.setPen(trace_pen)
        painter.drawLine(int(size * 0.17), int(size * 0.2), int(size * 0.48), int(size * 0.2))
        painter.drawLine(int(size * 0.17), int(size * 0.78), int(size * 0.48), int(size * 0.78))
        painter.drawLine(int(size * 0.82), int(size * 0.35), int(size * 0.62), int(size * 0.35))
        painter.drawLine(int(size * 0.82), int(size * 0.64), int(size * 0.62), int(size * 0.64))

        painter.setBrush(cyan)
        node_r = max(2, int(size * 0.03))
        for x, y in ((0.17, 0.2), (0.17, 0.78), (0.82, 0.35), (0.82, 0.64), (0.48, 0.2), (0.48, 0.78)):
            painter.drawEllipse(int(size * x) - node_r, int(size * y) - node_r, node_r * 2, node_r * 2)

        head = QPainterPath()
        head.moveTo(size * 0.40, size * 0.75)
        head.lineTo(size * 0.40, size * 0.30)
        head.lineTo(size * 0.46, size * 0.16)
        head.lineTo(size * 0.52, size * 0.30)
        head.lineTo(size * 0.66, size * 0.30)
        head.quadTo(size * 0.77, size * 0.36, size * 0.76, size * 0.47)
        head.quadTo(size * 0.75, size * 0.62, size * 0.63, size * 0.67)
        head.closeSubpath()

        painter.setPen(QPen(cyan, max(2, size // 60)))
        painter.setBrush(QColor("#0f2333"))
        painter.drawPath(head)
        painter.setBrush(amber)
        painter.drawEllipse(int(size * 0.64), int(size * 0.45), int(size * 0.08), int(size * 0.08))

        painter.end()
        return pixmap

    def build_logo_icon() -> QIcon:
        icon = QIcon()
        if LOGO_PNG.exists():
            icon.addFile(str(LOGO_PNG))
        else:
            for size in (32, 64, 128, 256, 512, 1024):
                icon.addPixmap(build_logo_pixmap(size))
        return icon

    def markdown_to_html(text: str) -> str:
        doc = QTextDocument()
        doc.setMarkdown(text)
        return doc.toHtml()

    def result_to_markdown(result: str) -> str:
        status_map = {
            "[OK]": "<span style='color:#49e4c8; font-weight:700'>[OK]</span>",
            "[WARN]": "<span style='color:#f0b25f; font-weight:700'>[WARN]</span>",
            "[FAIL]": "<span style='color:#ff7b72; font-weight:700'>[FAIL]</span>",
            "[INFO]": "<span style='color:#7fd8ff; font-weight:700'>[INFO]</span>",
        }

        lines: List[str] = []
        for raw in result.splitlines():
            line = html.escape(raw)
            for marker, token in status_map.items():
                escaped = html.escape(marker)
                if line.startswith(escaped):
                    line = line.replace(escaped, token, 1)
                    break

            if ":" in raw:
                key, value = raw.split(":", 1)
                path = Path(value.strip()).expanduser()
                if value.strip() and path.exists():
                    uri = path.resolve().as_uri()
                    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                        line = f"{html.escape(key)}: [open]({uri})\n\n![asset]({uri})"
                    else:
                        line = f"{html.escape(key)}: [open]({uri})"

            lines.append(line)
        return "\n".join(lines)

    def detect_drop_primary_type(items: Sequence[str]) -> str:
        if not items:
            return "document"
        hits = {"rfq": 0, "email": 0, "presentation": 0, "knowledge": 0, "image": 0, "document": 0}
        for value in items:
            hits[detect_content_type(value)] += 1
        ordered = sorted(hits.items(), key=lambda pair: pair[1], reverse=True)
        if len(ordered) > 1 and ordered[0][1] == ordered[1][1] and ordered[0][1] > 0:
            return "document"
        return ordered[0][0]

    def _drop_reason(item: str, detected_type: str) -> str:
        lower = item.lower()
        if detected_type == "email":
            matched = [token for token in ("from:", "subject:", ".eml", ".msg", "outlook", "mail", "bid") if token in lower]
            return f"Email markers: {', '.join(matched) if matched else 'email format signals'}"
        if detected_type == "rfq":
            matched = [token for token in ("rfq", "tender", "bid", "proposal", "review", "invitation") if token in lower]
            return f"RFQ markers: {', '.join(matched) if matched else 'contract-review language'}"
        if detected_type == "presentation":
            return "Presentation extension and deck context markers detected."
        if detected_type == "knowledge":
            return "Folder/link payload suited for vault retrieval workflow."
        if detected_type == "image":
            return "Image detected and ready for future vision workflow handling."
        return "General document signals detected for flexible processing."

    class DropZone(QFrame):
        dropped = Signal(list)

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setAcceptDrops(True)
            self.setObjectName("DropZone")
            self.setMinimumHeight(88)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(4)

            title = QLabel("DROP ANYTHING HERE", self)
            title.setObjectName("SectionTitle")
            title.setAlignment(Qt.AlignCenter)

            subtitle = QLabel(
                "Supported: Email, PDF, DOCX, PPTX, XLSX, TXT, Images, Folders, ZIP\n"
                "Finder, Outlook, Apple Mail, Desktop screenshots, mixed bundles",
                self,
            )
            subtitle.setObjectName("SmallMuted")
            subtitle.setAlignment(Qt.AlignCenter)

            layout.addWidget(title)
            layout.addWidget(subtitle)

        def _set_drag_state(self, dragging: bool) -> None:
            self.setProperty("dragging", dragging)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

        def dragEnterEvent(self, event) -> None:  # type: ignore[override]
            if event.mimeData().hasUrls() or event.mimeData().hasText() or event.mimeData().hasImage():
                self._set_drag_state(True)
                event.acceptProposedAction()
            else:
                event.ignore()

        def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
            self._set_drag_state(False)
            event.accept()

        def dropEvent(self, event) -> None:  # type: ignore[override]
            self._set_drag_state(False)
            items: List[str] = []
            mime = event.mimeData()

            for url in mime.urls():
                if url.isLocalFile():
                    items.append(url.toLocalFile())

            if mime.hasText() and not items:
                text_payload = mime.text().strip()
                if text_payload:
                    items.append(text_payload)

            if mime.hasImage() and not items:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                image_path = settings.output_dir.expanduser() / f"dropped-image-{stamp}.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image = mime.imageData()
                if hasattr(image, "save"):
                    image.save(str(image_path), "PNG")
                    items.append(str(image_path))

            if items:
                self.dropped.emit(items)
                event.acceptProposedAction()
            else:
                event.ignore()

    class HelpDialog(QDialog):
        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Help")
            self.resize(760, 580)

            root = QVBoxLayout(self)
            self.search = QLineEdit(self)
            self.search.setPlaceholderText("Search help...")
            self.search.textChanged.connect(self._render)
            root.addWidget(self.search)

            self.viewer = QTextBrowser(self)
            root.addWidget(self.viewer, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.reject)
            root.addWidget(buttons)

            self._render("")

        def _render(self, query: str) -> None:
            groups: Dict[str, List[str]] = {
                "Knowledge": ["read from vault <topic>", "what do we know about <customer>?"],
                "Email": ["store this email <payload>", "summarize email <payload>"],
                "RFQ": ["review this rfq <payload>", "find similar rfqs"],
                "Presentations": ["create presentation about <topic>", "store this presentation"],
                "General AI": ["How many calories are on this plate?", "Translate this PDF"],
                "System": ["health", "version", "backup knowledge", "export knowledge"],
            }
            q = query.strip().lower()
            lines: List[str] = ["# Help", "Grouped commands and examples:"]
            for name, entries in groups.items():
                matched = [item for item in entries if not q or q in item.lower() or q in name.lower()]
                if not matched:
                    continue
                lines.append(f"\n## {name}")
                lines.extend([f"- {item}" for item in matched])
            self.viewer.setMarkdown("\n".join(lines))

    class SettingsDialog(QDialog):
        def __init__(self, current_theme: str, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Settings")
            self.resize(680, 420)

            root = QVBoxLayout(self)
            form = QFormLayout()

            self.vault_path = QLineEdit(str(settings.obsidian_vault), self)
            browse = QPushButton("Browse")
            browse.clicked.connect(self._pick_vault)
            vault_row = QHBoxLayout()
            vault_row.addWidget(self.vault_path)
            vault_row.addWidget(browse)
            vault_wrap = QWidget(self)
            vault_wrap.setLayout(vault_row)

            self.ollama_url = QLineEdit(settings.ollama_url, self)
            self.presenton_url = QLineEdit(settings.presenton_url, self)
            self.output_dir = QLineEdit(str(settings.output_dir), self)
            self.theme = QComboBox(self)
            self.theme.addItems(["Modern", "Retro Futuristic", "Classic Console"])
            self.theme.setCurrentText(current_theme)
            self.enable_exports = QCheckBox("Enable export shortcuts", self)
            self.enable_exports.setChecked(True)
            self.enable_backups = QCheckBox("Enable backup shortcuts", self)
            self.enable_backups.setChecked(True)

            form.addRow("Vault location", vault_wrap)
            form.addRow("Ollama endpoint", self.ollama_url)
            form.addRow("Presenton endpoint", self.presenton_url)
            form.addRow("Export directory", self.output_dir)
            form.addRow("Theme", self.theme)
            form.addRow("", self.enable_exports)
            form.addRow("", self.enable_backups)
            root.addLayout(form)

            self.validation = QLabel("", self)
            root.addWidget(self.validation)

            buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            root.addWidget(buttons)

        def _pick_vault(self) -> None:
            selected = QFileDialog.getExistingDirectory(self, "Choose Obsidian Vault", str(settings.obsidian_vault))
            if selected:
                self.vault_path.setText(selected)

        def apply(self) -> Tuple[str, Dict[str, List[str]]]:
            settings.obsidian_vault = Path(self.vault_path.text().strip()).expanduser()
            settings.ollama_url = self.ollama_url.text().strip()
            settings.presenton_url = self.presenton_url.text().strip()
            settings.output_dir = Path(self.output_dir.text().strip()).expanduser()
            issues = validate_settings(settings)
            if issues["errors"]:
                self.validation.setText("Errors: " + "; ".join(issues["errors"]))
            elif issues["warnings"]:
                self.validation.setText("Warnings: " + "; ".join(issues["warnings"]))
            else:
                self.validation.setText("Configuration valid.")
            return self.theme.currentText(), issues

    class AboutDialog(QDialog):
        def __init__(self, note_count: int, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("About JPLlamA")
            self.resize(680, 520)
            root = QVBoxLayout(self)

            logo = QLabel(self)
            logo.setPixmap(build_logo_pixmap(180))
            logo.setAlignment(Qt.AlignCenter)

            app_path = Path(__file__).resolve().parents[2]
            info = QTextBrowser(self)
            info.setMarkdown(
                "\n".join(
                    [
                        "# JPLlamA",
                        f"Version: {APP_VERSION}",
                        f"Git revision: {_safe_git_revision()}",
                        "",
                        "## Capabilities",
                        "- Natural language command interface",
                        "- Smart drop workflow for mixed assets",
                        "- RFQ, email, presentation and memory workflows",
                        "- Vault-centered search with Ollama fallback",
                        "",
                        "## Runtime",
                        f"- Modules: {', '.join(_discover_modules())}",
                        f"- Knowledge notes detected: {note_count}",
                        f"- Application path: {app_path}",
                        f"- Vault path: {settings.obsidian_vault.expanduser()}",
                    ]
                )
            )

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.reject)

            root.addWidget(logo)
            root.addWidget(info, 1)
            root.addWidget(buttons)

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.backend = create_backend()
            self.thread_pool = QThreadPool.globalInstance()
            self._conversation_history: List[Dict[str, str]] = []
            self._last_artifacts: List[Path] = []
            self._last_dropped: List[str] = []
            self._command_history: List[str] = []
            self._history_index = -1
            self._running = False
            self._auto_follow = True
            self._run_id = ""
            self._cancel_event = threading.Event()
            self._active_prompt = ""
            self._last_error = ""
            self._last_stage = "Idle"
            self._last_service = "system"
            self._current_route = "chat"
            self._web_search_active = False
            self._last_progress_ts = time.monotonic()
            self._running_since = 0.0
            self._timeout_dialog_open = False
            self._service_states: Dict[str, str] = {
                "Vault": "connected",
                "Ollama": "waiting",
                "Presenton": "waiting",
                "SearXNG": "waiting",
                "Open WebUI": "waiting",
                "Docker": "waiting",
                "Knowledge": "waiting",
            }
            self._service_stage: Dict[str, str] = {name: "idle" for name in self._service_states}
            self._service_message: Dict[str, str] = {name: "" for name in self._service_states}
            now = time.monotonic()
            self._service_last_update: Dict[str, float] = {
                "Vault": now,
                "Ollama": now,
                "Presenton": now,
                "SearXNG": now,
                "Open WebUI": now,
                "Docker": now,
                "Knowledge": now,
            }

            self.settings_store = QSettings("JPLlamA", "Desktop")
            self.theme_name = self.settings_store.value("theme", "Modern")
            if not isinstance(self.theme_name, str):
                self.theme_name = "Modern"

            self.setWindowTitle(f"JPLlamA {APP_VERSION} - Desktop Console")
            self.resize(1520, 940)
            self.setMinimumSize(1024, 700)
            self.setMaximumSize(16777215, 16777215)
            self.setWindowIcon(build_logo_icon())
            self.setStyleSheet(THEME_STYLES.get(self.theme_name, MODERN_STYLESHEET))

            self._build_ui()
            self._refresh_side_panels()
            self._set_status("Ready")

            self._elapsed_timer = QTimer(self)
            self._elapsed_timer.setInterval(1000)
            self._elapsed_timer.timeout.connect(self._tick_elapsed)
            self._elapsed_timer.start()

            self._watchdog_timer = QTimer(self)
            self._watchdog_timer.setInterval(1000)
            self._watchdog_timer.timeout.connect(self._check_timeout_watchdog)
            self._watchdog_timer.start()

            QTimer.singleShot(60, self.command_input.setFocus)

        def _build_ui(self) -> None:
            root_widget = QWidget(self)
            root_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            root_layout = QVBoxLayout(root_widget)
            root_layout.setContentsMargins(14, 14, 14, 12)
            root_layout.setSpacing(12)

            header_panel = QFrame(self)
            header_panel.setObjectName("MainPanel")
            header_layout = QHBoxLayout(header_panel)
            header_layout.setContentsMargins(12, 10, 12, 10)
            header_layout.setSpacing(12)

            logo_label = QLabel(self)
            logo_label.setPixmap(build_logo_pixmap(54))
            logo_label.setFixedSize(58, 58)

            header_copy = QVBoxLayout()
            title = QLabel(f"JPLlamA {APP_VERSION}", self)
            title.setStyleSheet("font-size:24px; font-weight:800; letter-spacing:0.4px; color:#f0f7ff;")
            subtitle = QLabel("AI Operations Assistant", self)
            subtitle.setObjectName("SmallMuted")
            subtitle.setStyleSheet("font-size:11px; font-weight:600; letter-spacing:1.4px; text-transform:uppercase;")
            header_copy.addWidget(title)
            header_copy.addWidget(subtitle)

            header_layout.addWidget(logo_label)
            header_layout.addLayout(header_copy)
            header_layout.addStretch(1)

            meta_copy = QVBoxLayout()
            meta_title = QLabel("DESKTOP UI REDESIGN", self)
            meta_title.setObjectName("SectionTitle")
            meta_subtitle = QLabel("Clean. Focused. Conversation-First.", self)
            meta_subtitle.setObjectName("SmallMuted")
            meta_subtitle.setStyleSheet("font-size:12px;")
            meta_copy.addWidget(meta_title)
            meta_copy.addWidget(meta_subtitle)
            header_layout.addLayout(meta_copy)

            root_layout.addWidget(header_panel)

            prompt_panel = QFrame(self)
            prompt_panel.setObjectName("PromptPanel")
            prompt_layout = QVBoxLayout(prompt_panel)
            prompt_layout.setContentsMargins(12, 12, 12, 12)
            prompt_layout.setSpacing(10)

            prompt_row = QHBoxLayout()
            prompt_row.setSpacing(10)
            self.command_input = CommandInput(self)
            self.command_input.setPlaceholderText("Ask anything. Drop files or folders here...")
            self.command_input.setMaximumHeight(66)
            self.command_input.submitRequested.connect(self.run_command_from_input)
            self.command_input.historyNavigate.connect(self._navigate_history)
            prompt_row.addWidget(self.command_input, 1)

            controls = QVBoxLayout()
            controls.setSpacing(8)
            top_controls = QHBoxLayout()
            top_controls.setSpacing(8)

            self.run_button = QPushButton("Run", self)
            self.run_button.setObjectName("RunButton")
            self.run_button.clicked.connect(self.run_command_from_input)
            top_controls.addWidget(self.run_button)

            self.stop_button = QPushButton("Stop", self)
            self.stop_button.setObjectName("StopButton")
            self.stop_button.clicked.connect(lambda: self._request_stop("Stop requested by user."))
            self.stop_button.setEnabled(False)
            top_controls.addWidget(self.stop_button)

            self.settings_button = QPushButton("Settings", self)
            self.settings_button.clicked.connect(self.open_settings)
            top_controls.addWidget(self.settings_button)

            self.help_button = QPushButton("Help", self)
            self.help_button.clicked.connect(self.open_help)
            top_controls.addWidget(self.help_button)

            controls.addLayout(top_controls)
            prompt_row.addLayout(controls)
            prompt_layout.addLayout(prompt_row)

            self.drop_zone = DropZone(self)
            self.drop_zone.dropped.connect(self.handle_drop)
            prompt_layout.addWidget(self.drop_zone)

            self.smart_group = QGroupBox("SMART WORKFLOW", self)
            smart_layout = QVBoxLayout(self.smart_group)
            self.smart_summary = QLabel("Detected: none. Recommended workflow actions will appear here.", self)
            self.smart_summary.setObjectName("SmallMuted")
            self.smart_summary.setWordWrap(True)
            smart_layout.addWidget(self.smart_summary)
            self.smart_buttons = QHBoxLayout()
            smart_layout.addLayout(self.smart_buttons)
            prompt_layout.addWidget(self.smart_group)

            root_layout.addWidget(prompt_panel)

            splitter = QSplitter(Qt.Horizontal, self)
            splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            left = QFrame(self)
            left.setObjectName("SidebarPanel")
            left.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(10, 10, 10, 10)
            left_layout.setSpacing(8)

            left_layout.addWidget(self._section("CONVERSATION HISTORY"))
            self.recent_activity = QListWidget(self)
            self.recent_activity.setMaximumHeight(184)
            left_layout.addWidget(self.recent_activity)

            left_layout.addWidget(self._section("RECENT FILES"))
            self.recent_files = QListWidget(self)
            self.recent_files.setMaximumHeight(206)
            left_layout.addWidget(self.recent_files)

            left_layout.addWidget(self._section("VAULT"))
            self.current_vault = QLabel("", self)
            self.current_vault.setWordWrap(True)
            self.current_vault.setObjectName("SmallMuted")
            left_layout.addWidget(self.current_vault)

            vault_actions = QHBoxLayout()
            self.open_vault_btn = QPushButton("Open Vault Folder", self)
            self.open_vault_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.obsidian_vault.expanduser()))))
            vault_actions.addWidget(self.open_vault_btn)
            vault_actions.addStretch(1)
            left_layout.addLayout(vault_actions)

            self.favorites = QListWidget(self)
            self.favorites.setVisible(False)
            for label in (
                "review this rfq",
                "store this email",
                "remember this",
                "read from vault",
                "create presentation",
                "health",
                "version",
            ):
                self.favorites.addItem(label)
            self.favorites.itemDoubleClicked.connect(self._run_favorite)

            center = QFrame(self)
            center.setObjectName("MainPanel")
            center.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            center_layout = QVBoxLayout(center)
            center_layout.setContentsMargins(10, 10, 10, 10)
            center_layout.setSpacing(10)

            convo_panel = QFrame(self)
            convo_panel.setObjectName("MainPanel")
            convo_layout = QVBoxLayout(convo_panel)
            convo_layout.setContentsMargins(10, 10, 10, 10)
            convo_layout.setSpacing(8)

            convo_header = QHBoxLayout()
            convo_header.addWidget(self._section("CONVERSATION"))
            convo_header.addStretch(1)
            self.retry_btn = QPushButton("Retry", self)
            self.retry_btn.clicked.connect(self._retry_last_prompt)
            self.retry_btn.setEnabled(False)
            convo_header.addWidget(self.retry_btn)
            clear_btn = QPushButton("Clear", self)
            clear_btn.clicked.connect(self._clear_conversation)
            convo_header.addWidget(clear_btn)
            convo_layout.addLayout(convo_header)

            self.conversation = QTextBrowser(self)
            self.conversation.setOpenExternalLinks(True)
            self.conversation.setHtml("<h3>Conversation</h3><p>No messages yet.</p>")
            self.conversation.verticalScrollBar().valueChanged.connect(self._on_conversation_scroll)
            convo_layout.addWidget(self.conversation, 1)

            result_row = QHBoxLayout()
            self.open_btn = QPushButton("Open", self)
            self.open_btn.clicked.connect(self.open_latest_result)
            self.reveal_btn = QPushButton("Reveal", self)
            self.reveal_btn.clicked.connect(self.reveal_latest_result)
            self.copy_btn = QPushButton("Copy Path", self)
            self.copy_btn.clicked.connect(self.copy_latest_result_path)
            self.copy_error_btn = QPushButton("Copy Error", self)
            self.copy_error_btn.clicked.connect(self._copy_last_error)
            self.copy_error_btn.setEnabled(False)
            self.dev_details_btn = QPushButton("Developer Details", self)
            self.dev_details_btn.clicked.connect(self._show_developer_details)
            self.dev_details_btn.setEnabled(False)
            result_row.addWidget(self.open_btn)
            result_row.addWidget(self.reveal_btn)
            result_row.addWidget(self.copy_btn)
            result_row.addWidget(self.copy_error_btn)
            result_row.addWidget(self.dev_details_btn)
            result_row.addStretch(1)
            convo_layout.addLayout(result_row)

            center_layout.addWidget(convo_panel, 3)

            artifacts_panel = QFrame(self)
            artifacts_panel.setObjectName("MainPanel")
            artifacts_panel.setMaximumHeight(170)
            artifacts_layout = QVBoxLayout(artifacts_panel)
            artifacts_layout.setContentsMargins(10, 10, 10, 10)
            artifacts_layout.setSpacing(8)

            artifacts_header = QHBoxLayout()
            artifacts_header.addWidget(self._section("GENERATED ARTIFACTS"))
            artifacts_header.addStretch(1)
            artifacts_hint = QLabel("Latest files and quick actions", self)
            artifacts_hint.setObjectName("SmallMuted")
            artifacts_header.addWidget(artifacts_hint)
            artifacts_layout.addLayout(artifacts_header)

            self.artifact_scroll = QScrollArea(self)
            self.artifact_scroll.setWidgetResizable(True)
            self.artifact_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.artifact_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.artifact_scroll.setFrameShape(QFrame.NoFrame)
            self.artifact_scroll.setMinimumHeight(92)
            self.artifact_scroll.setMaximumHeight(108)

            self.artifact_strip = QWidget(self.artifact_scroll)
            self.artifact_strip_layout = QHBoxLayout(self.artifact_strip)
            self.artifact_strip_layout.setContentsMargins(2, 2, 2, 2)
            self.artifact_strip_layout.setSpacing(10)
            self.artifact_strip_layout.addStretch(1)
            self.artifact_scroll.setWidget(self.artifact_strip)
            artifacts_layout.addWidget(self.artifact_scroll)
            center_layout.addWidget(artifacts_panel)

            right = QFrame(self)
            right.setObjectName("SidebarPanel")
            right.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            right_layout = QVBoxLayout(right)
            right_layout.setContentsMargins(10, 10, 10, 10)
            right_layout.setSpacing(8)

            right_layout.addWidget(self._section("SERVICES"))
            self.vault_status = QLabel(self)
            self.vault_status.setWordWrap(True)
            self.vault_status.setObjectName("SmallMuted")
            self.vault_status.setMinimumHeight(64)
            self.vault_status.setMaximumHeight(96)
            right_layout.addWidget(self.vault_status)

            right_layout.addWidget(self._section("CURRENT JOB"))
            current_job = QFrame(self)
            current_job.setObjectName("MainPanel")
            current_job.setMinimumHeight(280)
            current_job_layout = QGridLayout(current_job)
            current_job_layout.setContentsMargins(10, 10, 10, 10)
            current_job_layout.setHorizontalSpacing(8)
            current_job_layout.setVerticalSpacing(5)

            self.progress = QProgressBar(self)
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("%p%")
            self.phase_label = QLabel("Current Stage: Idle", self)
            self.service_label = QLabel("Current Service: waiting", self)
            self.elapsed_label = QLabel("Elapsed Time: 0s", self)
            self.eta_label = QLabel("ETA: --", self)
            self.files_label = QLabel("Files Processed: 0", self)
            self.customer_label = QLabel("Current Customer: Unknown", self)
            self.project_label = QLabel("Current Project: Unknown", self)
            self.customer_label.setVisible(False)
            self.project_label.setVisible(False)
            self.job_label = QLabel("Current Job ID: --", self)
            self.current_task_label = QLabel("Current Task: idle", self)
            self.guidance_label = QLabel("Operator Guidance: Ready. Press Run to start.", self)
            self.guidance_label.setWordWrap(True)
            self.guidance_label.setObjectName("SmallMuted")
            self.phase_label.setWordWrap(True)
            self.service_label.setWordWrap(True)

            current_job_layout.addWidget(self.job_label, 0, 0, 1, 2)
            current_job_layout.addWidget(self.progress, 1, 0, 1, 2)
            current_job_layout.addWidget(self.phase_label, 2, 0, 1, 2)
            current_job_layout.addWidget(self.service_label, 3, 0, 1, 2)
            current_job_layout.addWidget(self.elapsed_label, 4, 0)
            current_job_layout.addWidget(self.eta_label, 4, 1)
            current_job_layout.addWidget(self.files_label, 5, 0)
            current_job_layout.addWidget(self.current_task_label, 5, 1)
            current_job_layout.addWidget(self.guidance_label, 6, 0, 1, 2)
            self.view_job_details_btn = QPushButton("View Job Details", self)
            self.view_job_details_btn.clicked.connect(self._show_job_details)
            current_job_layout.addWidget(self.view_job_details_btn, 7, 0, 1, 2)
            right_layout.addWidget(current_job)

            related_header = QHBoxLayout()
            related_header.addWidget(self._section("RELATED KNOWLEDGE"))
            related_header.addStretch(1)
            self.related_toggle_btn = QToolButton(self)
            self.related_toggle_btn.setText("Show")
            self.related_toggle_btn.clicked.connect(self._toggle_related_knowledge)
            related_header.addWidget(self.related_toggle_btn)
            right_layout.addLayout(related_header)

            self.related_panel = QWidget(self)
            related_panel_layout = QVBoxLayout(self.related_panel)
            related_panel_layout.setContentsMargins(0, 0, 0, 0)
            related_panel_layout.setSpacing(6)

            self.related_notes = QListWidget(self)
            self.related_notes.itemDoubleClicked.connect(self._open_related)
            self.related_notes.setMaximumHeight(118)
            related_panel_layout.addWidget(self.related_notes)

            search_row = QHBoxLayout()
            self.search_vault_btn = QToolButton(self)
            self.search_vault_btn.setText("Search Vault")
            self.search_vault_btn.setFixedHeight(27)
            self.search_vault_btn.clicked.connect(lambda: self.command_input.setPlainText("read from vault "))
            search_row.addWidget(self.search_vault_btn)
            search_row.addStretch(1)
            related_panel_layout.addLayout(search_row)
            right_layout.addWidget(self.related_panel)

            self._related_expanded = False
            self._set_related_expanded(False)

            self.current_vault = QLabel("", self)
            self.current_vault.setWordWrap(False)
            self.current_vault.setObjectName("SmallMuted")
            self.current_vault.setMaximumHeight(20)
            right_layout.addWidget(self.current_vault)

            self.context_info = QTextBrowser(self)
            self.context_info.setVisible(False)

            self.service_monitor = QTextBrowser(self)
            self.service_monitor.setMaximumHeight(120)
            self.service_monitor.setVisible(False)

            self.system_health = QTextBrowser(self)
            self.system_health.setMaximumHeight(110)
            self.system_health.setVisible(False)

            self.developer_mode = QCheckBox("Developer mode", self)
            self.developer_mode.toggled.connect(self._toggle_developer_mode)
            right_layout.addWidget(self.developer_mode)

            self.log_panel = QPlainTextEdit(self)
            self.log_panel.setReadOnly(True)
            self.log_panel.document().setMaximumBlockCount(2000)
            self.log_panel.setVisible(False)
            self.log_panel.setPlaceholderText("Live logs (Ollama / Presenton / Vault / Memory / Timing / Errors)")
            right_layout.addWidget(self.log_panel)
            right_layout.setStretch(0, 0)
            right_layout.setStretch(1, 0)
            right_layout.setStretch(2, 1)

            splitter.addWidget(left)
            splitter.addWidget(center)
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setStretchFactor(2, 0)
            splitter.setSizes([240, 980, 320])
            root_layout.addWidget(splitter, 1)

            self.setCentralWidget(root_widget)

            status = QStatusBar(self)
            self.setStatusBar(status)
            self.status_vault = QLabel("Vault: unknown", self)
            self.status_ollama = QLabel("Ollama: unknown", self)
            self.status_presenton = QLabel("Presentation: unknown", self)
            self.status_knowledge = QLabel("Knowledge: 0", self)
            self.status_task = QLabel("Task: Ready", self)
            for widget in (self.status_vault, self.status_ollama, self.status_presenton, self.status_knowledge, self.status_task):
                status.addPermanentWidget(widget)

            app_menu = self.menuBar().addMenu("Application")
            for title, callback in (("Interactive Help", self.open_help), ("Settings", self.open_settings), ("About", self.open_about)):
                action = QAction(title, self)
                action.triggered.connect(callback)
                app_menu.addAction(action)
            self._render_artifact_strip()

        def _section(self, title: str) -> QLabel:
            label = QLabel(title, self)
            label.setObjectName("SectionTitle")
            return label

        def _set_related_expanded(self, expanded: bool) -> None:
            self._related_expanded = expanded
            self.related_panel.setVisible(expanded)
            self.related_toggle_btn.setText("Hide" if expanded else "Show")

        def _toggle_related_knowledge(self) -> None:
            self._set_related_expanded(not self._related_expanded)

        def _count_notes(self, vault: Path) -> int:
            try:
                return sum(1 for _ in vault.rglob("*.md")) if vault.exists() else 0
            except Exception:
                return 0

        def _set_status(self, task: str) -> None:
            vault = settings.obsidian_vault.expanduser()
            notes = self._count_notes(vault)
            self.status_vault.setText(f"Vault: {'connected' if vault.exists() else 'missing'}")
            self.status_ollama.setText(f"Ollama: {settings.ollama_url}")
            self.status_presenton.setText(f"Presentation: {settings.presenton_url}")
            self.status_knowledge.setText(f"Knowledge: {notes} notes")
            self.status_task.setText(f"Task: {task}")

            if vault.exists():
                self.status_vault.setStyleSheet("color:#46d27b;")
            else:
                self.status_vault.setStyleSheet("color:#ff7b72;")
            lowered_task = task.lower()
            if "failed" in lowered_task or "error" in lowered_task:
                task_color = "#ff7b72"
            elif "busy" in lowered_task:
                task_color = "#56a0ff"
            elif "working" in lowered_task or "processing" in lowered_task:
                task_color = "#f0b25f"
            elif self._running:
                task_color = "#f0b25f"
            else:
                task_color = "#46d27b"
            self.status_task.setStyleSheet(f"color:{task_color};")
            self.status_ollama.setStyleSheet("color:#46d27b;" if "127.0.0.1" in settings.ollama_url else "color:#f0b25f;")
            self.status_presenton.setStyleSheet("color:#46d27b;" if "127.0.0.1" in settings.presenton_url else "color:#f0b25f;")

        def _refresh_side_panels(self) -> None:
            vault = settings.obsidian_vault.expanduser()
            notes = self._count_notes(vault)
            ollama_connected = _service_reachable(settings.ollama_url)
            presenton_connected = _service_reachable(settings.presenton_url)
            openwebui_connected = _service_reachable(settings.openwebui_url) if settings.openwebui_url else False
            searxng_connected = _service_reachable(settings.searxng_url) if settings.searxng_url else False
            docker_connected = _docker_reachable()
            self.current_vault.setText(str(vault))
            self.current_vault.setToolTip(str(vault))
            self.vault_status.setText(
                "\n".join(
                    [
                        f"Vault: {service_status_text('Vault', vault.exists())}",
                        f"Ollama: {service_status_text('Ollama', ollama_connected)}",
                        f"Presenton: {service_status_text('Presenton', presenton_connected)}",
                        f"Docker: {service_status_text('Docker', docker_connected)}",
                        f"Open WebUI: {service_status_text('Open WebUI', openwebui_connected)}",
                        f"SearXNG: {service_status_text('SearXNG', searxng_connected)}",
                    ]
                )
            )
            self.system_health.setMarkdown(
                "\n".join(
                    [
                        f"- Ollama: {'connected' if ollama_connected else 'unavailable'}",
                        f"- Presenton: {'connected' if presenton_connected else 'unavailable'}",
                        f"- Open WebUI: {'connected' if openwebui_connected else 'disconnected'} ({'optional' if not OPEN_WEBUI_REQUIRED else 'required'})",
                        f"- SearXNG: {'connected' if searxng_connected else 'unavailable'}",
                        f"- Docker: {'connected' if docker_connected else 'unavailable'}",
                        f"- Vault: {'connected' if vault.exists() else 'unavailable'}",
                        f"- Diagnostics: {self._runtime_diagnostics_summary()}",
                    ]
                )
            )
            self._set_service_state("vault", "connected" if vault.exists() else "unavailable", stage="check", message=str(vault))
            self._set_service_state("knowledge", "waiting", stage="idle", message="Awaiting command")
            self._set_service_state(
                "ollama",
                "connected" if ollama_connected else "unavailable",
                stage="check",
                message=settings.ollama_url,
            )
            self._set_service_state(
                "presenton",
                "connected" if presenton_connected else "unavailable",
                stage="check",
                message=settings.presenton_url,
            )
            self._set_service_state(
                "openwebui",
                "connected" if openwebui_connected else "disconnected",
                stage="optional",
                message=("Used by upload watcher only" if not OPEN_WEBUI_REQUIRED else settings.openwebui_url),
            )
            self._set_service_state(
                "searxng",
                "connected" if searxng_connected else "unavailable",
                stage="check",
                message=settings.searxng_url,
            )
            self._set_service_state(
                "docker",
                "connected" if docker_connected else "unavailable",
                stage="runtime",
                message="Container runtime for Presenton deployments",
            )
            self._render_service_monitor()
            self.context_info.setMarkdown("Customer\nUnknown\n\nProject\nUnknown")
            self._set_operator_guidance("Ready. Press Run to start, Stop while running.", "#46d27b")
            self._set_status("Ready")

        def _render_service_monitor(self) -> None:
            color_map = {
                "connected": "#46d27b",
                "busy": "#56a0ff",
                "waiting": "#f0b25f",
                "unavailable": "#ff7b72",
                "error": "#ff7b72",
                "disconnected": "#9baec4",
            }
            lines = ["### Services"]
            for service in ("Vault", "Ollama", "Presenton", "Docker", "Open WebUI", "SearXNG", "Knowledge"):
                state = self._service_states.get(service, "waiting")
                color = color_map.get(state, "#9baec4")
                stage = self._service_stage.get(service, "idle")
                message = self._service_message.get(service, "")
                age_seconds = int(max(0.0, time.monotonic() - float(self._service_last_update.get(service, time.monotonic()))))
                lines.append(
                    f"- <span style='color:{color}'><b>{service}</b>: {state}</span> | stage: {html.escape(stage)} | "
                    f"updated: {age_seconds}s ago"
                )
                if message:
                    lines.append(f"  - {html.escape(message)}")
            self.service_monitor.setMarkdown("\n".join(lines))

        def _set_service_state(self, service: str, state: str, *, stage: str = "", message: str = "") -> None:
            service_map = {
                "ollama": "Ollama",
                "presenton": "Presenton",
                "openwebui": "Open WebUI",
                "open webui": "Open WebUI",
                "searxng": "SearXNG",
                "docker": "Docker",
                "knowledge": "Knowledge",
                "vault": "Vault",
                "memory": "Knowledge",
                "email": "Knowledge",
                "rfq": "Knowledge",
                "system": "Knowledge",
            }
            key = service_map.get(service.lower(), service.title())
            normalized_state = (state or "waiting").strip().lower()
            if normalized_state not in {"connected", "busy", "waiting", "unavailable", "error", "disconnected"}:
                normalized_state = "waiting"
            self._service_states[key] = normalized_state
            if stage:
                self._service_stage[key] = stage
            if message or key not in self._service_message:
                self._service_message[key] = message
            self._service_last_update[key] = time.monotonic()
            self._render_service_monitor()

        def _set_operator_guidance(self, message: str, color: str = "#86a3c5") -> None:
            safe = html.escape(message)
            self.guidance_label.setTextFormat(Qt.RichText)
            self.guidance_label.setText(f"<span style='color:{color}'>{safe}</span>")

        def _set_progress(self, phase: str, value: int, files_processed: int = 0, eta: str = "--") -> None:
            self.phase_label.setText(f"Current Stage: {phase}")
            self.progress.setValue(value)
            self.files_label.setText(f"Files Processed: {files_processed}")
            self.eta_label.setText(f"ETA: {eta}")
            self.current_task_label.setText(f"Current Task: {phase.lower()}")
            lowered = phase.lower()
            if lowered in {"completed", "idle"}:
                self._set_operator_guidance("Done. You can run the next command.", "#46d27b")
            elif lowered in {"failed", "cancelled"}:
                self._set_operator_guidance("Action needed: Retry, adjust settings, or inspect error details.", "#ff7b72")
            elif "waiting" in lowered or "connecting" in lowered or "generating" in lowered or "rendering" in lowered:
                if self._last_service == "presenton":
                    self._set_operator_guidance("Presenton is building slides. This phase can run for several minutes.", "#f0b25f")
                else:
                    self._set_operator_guidance("Service is active. Wait if progressing, Stop if urgent.", "#f0b25f")
            elif "search" in lowered or "building" in lowered or "reading" in lowered:
                self._set_operator_guidance("Working on context. Wait for ranked results.", "#56a0ff")

        def _append_live_log(self, service: str, message: str) -> None:
            stamp = datetime.now().strftime("%H:%M:%S")
            line = f"[{stamp}] [{service.upper()}] {message}"
            if self.developer_mode.isChecked():
                self.log_panel.appendPlainText(line)

        def _set_running_controls(self, running: bool) -> None:
            self._running = running
            if running:
                self.run_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                self.smart_group.setEnabled(False)
                self.favorites.setEnabled(False)
                self.command_input.setEnabled(True)
                self.retry_btn.setEnabled(False)
            else:
                self.run_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self.smart_group.setEnabled(True)
                self.favorites.setEnabled(True)
                self.command_input.setEnabled(True)
                self.retry_btn.setEnabled(bool(self._active_prompt))

        def _tick_elapsed(self) -> None:
            if not self._running or self._running_since <= 0:
                self.elapsed_label.setText("Elapsed Time: 0s")
                return
            elapsed = int(max(0.0, time.monotonic() - self._running_since))
            self.elapsed_label.setText(f"Elapsed Time: {elapsed}s")
            if self.developer_mode.isChecked() and elapsed % 5 == 0:
                self._append_live_log("timing", self._runtime_diagnostics_summary())

        def _runtime_diagnostics_summary(self) -> str:
            try:
                cpu_load = os.getloadavg()[0]
            except Exception:
                cpu_load = 0.0
            if resource is not None:
                try:
                    rss_kb = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                except Exception:
                    rss_kb = 0
            else:
                rss_kb = 0
            if rss_kb > 0:
                rss_mb = rss_kb / 1024.0
                return f"CPU load {cpu_load:.2f}, RAM {rss_mb:.1f} MB"
            return f"CPU load {cpu_load:.2f}"

        def _timeout_threshold_seconds(self) -> int:
            return _timeout_threshold_for_workflow(self._current_route, self._last_service, self._web_search_active)

        def _format_timeout_label(self, seconds: int) -> str:
            minutes, remainder = divmod(max(0, int(seconds)), 60)
            if minutes:
                return f"{minutes}:{remainder:02d}"
            return f"{remainder}s"

        def _check_timeout_watchdog(self) -> None:
            if not self._running:
                return
            idle = time.monotonic() - self._last_progress_ts
            threshold = self._timeout_threshold_seconds()
            if idle < threshold or self._timeout_dialog_open:
                return
            timeout_label = self._format_timeout_label(threshold)
            self._timeout_dialog_open = True
            self._append_message(
                "JPLlamA",
                result_to_markdown("\n".join([
                    "[WARN] Waiting...",
                    f"No response for {timeout_label}.",
                    "Continue waiting / Retry / Cancel",
                ])),
                "timeout",
            )
            self._set_operator_guidance(
                f"No response for {timeout_label}. Choose Continue, Retry, or Stop.",
                "#ff7b72",
            )
            box = QMessageBox(self)
            box.setWindowTitle("Service timeout")
            box.setText(
                f"No response for {timeout_label} during {self._last_stage} ({self._last_service}). Continue waiting?"
            )
            continue_btn = box.addButton("Continue", QMessageBox.AcceptRole)
            retry_btn = box.addButton("Retry", QMessageBox.ActionRole)
            cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            self._timeout_dialog_open = False
            self._last_progress_ts = time.monotonic()
            if clicked == cancel_btn:
                self._request_stop("Cancelled after timeout prompt.")
            elif clicked == retry_btn:
                self._request_stop("Retry requested after timeout prompt.")
                QTimer.singleShot(150, self._retry_last_prompt)
            elif clicked == continue_btn:
                self._append_live_log("system", "User chose to keep waiting after timeout detection.")
                self._set_operator_guidance("Continuing to wait. You can Stop anytime.", "#f0b25f")

        def _append_message(self, role: str, content: str, status: str) -> None:
            self._conversation_history.append(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "role": role,
                    "status": status,
                    "content": content,
                }
            )
            self._render_conversation()

        def _render_conversation(self) -> None:
            if not self._conversation_history:
                self.conversation.setHtml("<h3>Conversation</h3><p>No messages yet.</p>")
                return

            scroll = self.conversation.verticalScrollBar()
            was_bottom = self._auto_follow or scroll.value() >= (scroll.maximum() - 6)

            parts = [
                "<html><head><style>"
                "body{font-family:'SF Pro Display','Segoe UI',sans-serif;background:transparent;color:#dcecff;}"
                ".turn{margin:10px 0;padding:10px 12px;border-radius:10px;border:1px solid #254664;background:#0b1826;}"
                ".user{border-color:#2f3f58;background:#101820;color:#9fb0c8;}"
                ".assistant{border-color:#1f6ca8;background:#091a2e;color:#eaf4ff;}"
                ".meta{font-size:11px;opacity:0.8;margin-bottom:6px;}"
                "</style></head><body>"
            ]

            for item in self._conversation_history:
                role = item["role"]
                cls = "assistant" if role == "JPLlamA" else "user"
                content_html = markdown_to_html(item["content"]) if role == "JPLlamA" else f"<p>{html.escape(item['content']).replace(chr(10), '<br>')}</p>"
                parts.append(
                    f"<div class='turn {cls}'>"
                    f"<div class='meta'>{item['time']} | {html.escape(role)} | {html.escape(item['status'])}</div>"
                    f"{content_html}</div>"
                )

            parts.append("</body></html>")
            self.conversation.setHtml("".join(parts))
            if was_bottom:
                scroll.setValue(scroll.maximum())

        def _on_conversation_scroll(self) -> None:
            bar = self.conversation.verticalScrollBar()
            self._auto_follow = bar.value() >= (bar.maximum() - 8)

        def _extract_artifact_paths(self, text: str) -> List[Path]:
            artifacts: List[Path] = []
            for line in text.splitlines():
                if not re.search(r"(Path|Markdown|DOCX|Obsidian note|Folder|Saved to|Filename):", line, flags=re.IGNORECASE):
                    continue
                if ":" not in line:
                    continue
                value = line.split(":", 1)[1].strip()
                if not value:
                    continue
                p = Path(value).expanduser()
                if p.exists():
                    artifacts.append(p)
            return artifacts

        def _artifact_label(self, path: Path) -> str:
            suffix = path.suffix.lower()
            mapping = {
                ".pptx": "PPTX",
                ".ppt": "PPT",
                ".docx": "DOCX",
                ".pdf": "PDF",
                ".md": "MD",
                ".txt": "TXT",
                ".xlsx": "XLSX",
                ".xls": "XLS",
                ".csv": "CSV",
                ".json": "JSON",
            }
            return mapping.get(suffix, suffix.lstrip(".").upper() or "FILE")

        def _make_artifact_card(self, path: Path) -> QFrame:
            card = QFrame(self)
            card.setObjectName("ArtifactCard")
            card.setFixedWidth(260)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)

            top_row = QHBoxLayout()
            badge = QLabel(self._artifact_label(path), self)
            badge.setStyleSheet("font-size:11px; font-weight:700; color:#7fe8d5;")
            top_row.addWidget(badge)
            top_row.addStretch(1)
            layout.addLayout(top_row)

            name = QLabel(path.name, self)
            name.setWordWrap(True)
            name.setStyleSheet("font-size:13px; font-weight:700; color:#f0f7ff;")
            layout.addWidget(name)

            meta = QLabel(str(path.parent), self)
            meta.setWordWrap(True)
            meta.setObjectName("SmallMuted")
            layout.addWidget(meta)

            button_row = QHBoxLayout()
            button_row.setSpacing(6)
            open_btn = QToolButton(self)
            open_btn.setText("Open")
            open_btn.clicked.connect(lambda _checked=False, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
            reveal_btn = QToolButton(self)
            reveal_btn.setText("Reveal")
            reveal_btn.clicked.connect(lambda _checked=False, p=path: subprocess.Popen(["open", "-R", str(p)]) if sys.platform == "darwin" else QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent))))
            copy_btn = QToolButton(self)
            copy_btn.setText("Copy")
            copy_btn.clicked.connect(lambda _checked=False, p=path: QApplication.clipboard().setText(str(p)))
            button_row.addWidget(open_btn)
            button_row.addWidget(reveal_btn)
            button_row.addWidget(copy_btn)
            button_row.addStretch(1)
            layout.addLayout(button_row)

            return card

        def _render_artifact_strip(self) -> None:
            while self.artifact_strip_layout.count():
                item = self.artifact_strip_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()

            if not self._last_artifacts:
                empty = QLabel("No generated artifacts yet.", self.artifact_strip)
                empty.setObjectName("SmallMuted")
                self.artifact_strip_layout.addWidget(empty)
                self.artifact_strip_layout.addStretch(1)
                return

            for artifact in self._last_artifacts[:8]:
                self.artifact_strip_layout.addWidget(self._make_artifact_card(artifact))
            self.artifact_strip_layout.addStretch(1)

        def _show_job_details(self) -> None:
            details = "\n".join(
                [
                    f"Job ID: {self._run_id or 'idle'}",
                    f"Stage: {self._last_stage}",
                    f"Service: {self._last_service}",
                    f"Progress: {self.progress.value()}%",
                    f"Elapsed: {self.elapsed_label.text().replace('Elapsed Time: ', '')}",
                    f"ETA: {self.eta_label.text().replace('ETA: ', '')}",
                    f"Active prompt: {self._active_prompt or 'none'}",
                ]
            )
            QMessageBox.information(self, "Current Job", details)

        def _sync_related_notes(self, query: str) -> None:
            self.related_notes.clear()
            hits = self.backend.obsidian.search(query, limit=8)
            if not hits:
                item = QListWidgetItem("No related knowledge found.")
                item.setData(Qt.UserRole, "")
                self.related_notes.addItem(item)
                return

            for hit in hits:
                path = str(hit.get("path") or "").strip()
                summary = str(hit.get("summary") or hit.get("snippet") or "").strip()
                label = f"{path} | {summary[:80]}" if path else summary[:100]
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, path)
                self.related_notes.addItem(item)

        def _update_context(self, text: str) -> None:
            customer, project = _extract_customer_project(text)
            self.context_info.setMarkdown(f"Customer\n{customer}\n\nProject\n{project}")
            self.customer_label.setText(f"Current Customer: {customer}")
            self.project_label.setText(f"Current Project: {project}")

        def _run_or_stop(self) -> None:
            if self._running:
                self._request_stop("Stop requested by user.")
                return
            self.run_command_from_input()

        def _request_stop(self, reason: str) -> None:
            if not self._running:
                return
            self._cancel_event.set()
            self._run_id = ""
            self._append_live_log("system", reason)
            self._append_message("JPLlamA", result_to_markdown("[WARN] Operation cancelled by user."), "cancelled")
            self._set_service_state("ollama", "waiting", stage="cancelled", message=reason)
            self._set_service_state("presenton", "waiting", stage="cancelled", message=reason)
            self._set_service_state("knowledge", "waiting", stage="cancelled", message=reason)
            self._set_progress("Cancelled", 0, 0, "--")
            self._set_operator_guidance("Stopped. Review partial output or Retry when ready.", "#f0b25f")
            self._set_status("ready")
            self._set_running_controls(False)
            self._web_search_active = False

        def _retry_last_prompt(self) -> None:
            if not self._active_prompt:
                return
            if self._running:
                return
            self.command_input.setPlainText(self._active_prompt)
            self.run_command_from_input()

        def _copy_last_error(self) -> None:
            if not self._last_error:
                return
            QApplication.clipboard().setText(self._last_error)
            self.statusBar().showMessage("Error copied", 1300)

        def _show_developer_details(self) -> None:
            if not self._last_error:
                QMessageBox.information(self, "Developer Details", "No error details available.")
                return
            QMessageBox.information(self, "Developer Details", self._last_error)

        def _toggle_developer_mode(self, enabled: bool) -> None:
            self.log_panel.setVisible(enabled)

        def run_command_from_input(self) -> None:
            if self._running:
                return
            prompt = self.command_input.toPlainText().strip()
            if not prompt:
                return

            plan = Planner().plan(prompt)

            self.command_input.clear()
            self._active_prompt = prompt
            self._current_route = plan.route
            self._web_search_active = _needs_web_search(prompt)
            self._cancel_event = threading.Event()
            self._run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
            self.job_label.setText(f"Current Job ID: {self._run_id[-8:]}")
            self._command_history.append(prompt)
            self._history_index = len(self._command_history)
            self._append_message("User", prompt, "submitted")
            self.recent_activity.insertItem(0, f"{datetime.now().strftime('%H:%M:%S')} {prompt[:100]}")
            self.recent_searches = getattr(self, "recent_searches", None)
            self._set_progress("Preparing prompt", 4, len(self._last_dropped), "~6s")
            self._set_operator_guidance("Starting run. Stop is available immediately.", "#56a0ff")
            self.service_label.setText("Current Service: system")
            self._set_status("processing")
            self._set_running_controls(True)
            self._running_since = time.monotonic()
            self._last_progress_ts = self._running_since
            self.copy_error_btn.setEnabled(False)
            self.dev_details_btn.setEnabled(False)
            self._last_error = ""

            worker = CommandWorker(self._run_id, prompt, self.backend, self._cancel_event)
            worker.signals.progress.connect(self._on_worker_progress)
            worker.signals.stream.connect(self._on_worker_stream)
            worker.signals.success.connect(self._on_worker_success)
            worker.signals.error.connect(self._on_worker_error)
            self.thread_pool.start(worker)

        def _on_worker_progress(self, phase: str, value: int, files_processed: int, eta: str, meta: object) -> None:
            payload = meta if isinstance(meta, dict) else {}
            if str(payload.get("run_id") or "") != self._run_id:
                return
            self._last_progress_ts = time.monotonic()
            self._last_stage = phase
            service = str(payload.get("service") or "system")
            self._last_service = service
            self._set_progress(phase.replace("_", " ").title(), value, files_processed, eta)
            self.service_label.setText(f"Current Service: {service}")
            if service in {"ollama", "presenton"}:
                self._set_status("busy")
            else:
                self._set_status("working")
            if service in {"ollama", "presenton"}:
                self._set_service_state(service, "busy", stage=phase, message=_stage_to_human(phase, payload))
            elif service in {"knowledge", "vault", "memory", "email", "rfq"}:
                self._set_service_state("knowledge", "busy", stage=phase, message=_stage_to_human(phase, payload))
            if phase.lower() in {"completed", "knowledge_found"}:
                self._set_service_state("knowledge", "connected", stage=phase, message="Completed")
            if phase.lower() == "no_relevant_knowledge":
                self._set_service_state("knowledge", "waiting", stage=phase, message="No relevant note found")

        def _on_worker_stream(self, service: str, message: str, meta: object) -> None:
            payload = meta if isinstance(meta, dict) else {}
            if str(payload.get("run_id") or "") != self._run_id:
                return
            self._last_progress_ts = time.monotonic()
            if bool(payload.get("log")):
                self._append_live_log(service, message)
                return
            service_display = {
                "ollama": "Ollama",
                "presenton": "Presenton",
                "openwebui": "Open WebUI",
                "open webui": "Open WebUI",
                "docker": "Docker",
                "knowledge": "Knowledge",
                "vault": "Vault",
                "memory": "Knowledge",
                "email": "Knowledge",
                "rfq": "Knowledge",
                "system": "Knowledge",
            }.get(service.lower(), service.title())
            current_state = self._service_states.get(service_display, "waiting")
            self._set_service_state(service, current_state, stage=self._last_stage, message=message)
            self._append_message("JPLlamA", result_to_markdown(f"[INFO] {message}"), "live")
            self._append_live_log(service, message)

        def _on_worker_success(self, prompt: str, result: str, meta: object) -> None:
            payload = meta if isinstance(meta, dict) else {}
            if str(payload.get("run_id") or "") != self._run_id:
                return
            rendered = result_to_markdown(result)
            self._append_message("JPLlamA", rendered, "completed")
            self._last_artifacts = self._extract_artifact_paths(result)
            self._render_artifact_strip()
            self._sync_related_notes(prompt)
            self._update_context(f"{prompt}\n{result}")
            self._set_progress("Completed", 100, len(self._last_dropped), "0s")
            self.service_label.setText("Current Service: completed")
            self._set_service_state(
                "ollama",
                "connected" if _service_reachable(settings.ollama_url, timeout=0.4) else "unavailable",
                stage="completed",
                message=settings.ollama_url,
            )
            self._set_service_state(
                "presenton",
                "connected" if _service_reachable(settings.presenton_url, timeout=0.4) else "unavailable",
                stage="completed",
                message=settings.presenton_url,
            )
            self._set_service_state(
                "openwebui",
                "connected" if (settings.openwebui_url and _service_reachable(settings.openwebui_url, timeout=0.4)) else "disconnected",
                stage="optional",
                message=("Used by upload watcher only" if not OPEN_WEBUI_REQUIRED else settings.openwebui_url),
            )
            self._set_service_state(
                "docker",
                "connected" if _docker_reachable(timeout=0.8) else "unavailable",
                stage="runtime",
                message="Container runtime",
            )
            self._set_service_state("knowledge", "connected", stage="completed", message="Command completed")
            self._set_status("ready")
            self._set_operator_guidance("Completed successfully. Safe to continue.", "#46d27b")
            self._set_running_controls(False)
            self._web_search_active = False
            self._run_id = ""
            QTimer.singleShot(1100, lambda: self._set_progress("Idle", 0, 0, "--"))

        def _on_worker_error(self, error: str, meta: object) -> None:
            payload = meta if isinstance(meta, dict) else {}
            if str(payload.get("run_id") or "") != self._run_id:
                return
            self._last_error = error
            self.copy_error_btn.setEnabled(True)
            self.dev_details_btn.setEnabled(True)
            guidance = "\n".join(
                [
                    "[FAIL] Operation failed.",
                    f"Service: {self._last_service}",
                    f"Stage: {self._last_stage}",
                    f"Reason: {error}",
                    "Possible solution: Verify service availability and configuration.",
                    "Retry: Use Retry button.",
                    "Open Settings: Use Settings button to verify endpoints.",
                    "Copy Error: Use Copy Error button.",
                    "Developer Details: Use Developer Details button.",
                ]
            )
            self._append_message("JPLlamA", result_to_markdown(guidance), "failed")
            self._set_progress("Failed", 100, len(self._last_dropped), "0s")
            self._set_operator_guidance("Failed. Retry now, or open Settings if service endpoints changed.", "#ff7b72")
            self._set_status("failed")
            if self._last_service in {"ollama", "presenton"}:
                self._set_service_state(self._last_service, "error", stage=self._last_stage, message=error)
            else:
                self._set_service_state("knowledge", "error", stage=self._last_stage, message=error)
            if self._last_service != "ollama":
                self._set_service_state(
                    "ollama",
                    "connected" if _service_reachable(settings.ollama_url, timeout=0.4) else "unavailable",
                    stage="check",
                    message=settings.ollama_url,
                )
            if self._last_service != "presenton":
                self._set_service_state(
                    "presenton",
                    "connected" if _service_reachable(settings.presenton_url, timeout=0.4) else "unavailable",
                    stage="check",
                    message=settings.presenton_url,
                )
            self._set_service_state(
                "searxng",
                "connected" if _service_reachable(settings.searxng_url, timeout=0.4) else "unavailable",
                stage="check",
                message=settings.searxng_url,
            )
            self._set_service_state(
                "docker",
                "connected" if _docker_reachable(timeout=0.8) else "unavailable",
                stage="runtime",
                message="Container runtime",
            )
            self._set_running_controls(False)
            self._web_search_active = False
            self._run_id = ""

        def _navigate_history(self, direction: int) -> None:
            if not self._command_history:
                return
            self._history_index = max(0, min(len(self._command_history) - 1, self._history_index + direction))
            self.command_input.setPlainText(self._command_history[self._history_index])
            cursor = self.command_input.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.command_input.setTextCursor(cursor)

        def _clear_smart_buttons(self) -> None:
            while self.smart_buttons.count():
                item = self.smart_buttons.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()

        def _render_smart_actions(self, content_type: str) -> None:
            self._clear_smart_buttons()
            actions = suggest_actions_for_type(content_type)
            self.smart_summary.setText(f"Detected {content_type}. Recommended workflow actions:")
            for action in actions:
                btn = QPushButton(action, self)
                btn.clicked.connect(lambda _checked=False, a=action: self._run_smart_action(a))
                self.smart_buttons.addWidget(btn)
            self.smart_buttons.addStretch(1)

        def _action_to_prompt(self, action: str, payload: str) -> str:
            mapping = {
                "Review RFQ": "review this rfq",
                "Store RFQ": "store this rfq",
                "Find Similar RFQs": "read from vault similar rfq",
                "Store Email": "store this email",
                "Summarize Email": "process email",
                "Remember": "remember this",
                "Find Related Emails": "read from vault related emails",
                "Store Presentation": "store this presentation",
                "Summarize Presentation": "remember this presentation",
                "Find Similar Presentations": "read from vault similar presentations",
                "Search Knowledge": "read from vault",
                "Store Document": "remember this",
            }
            return f"{mapping.get(action, 'read from vault')} {payload}".strip()

        def _run_smart_action(self, action: str) -> None:
            payload = "\n".join(self._last_dropped).strip()
            self.command_input.setPlainText(self._action_to_prompt(action, payload))
            self.run_command_from_input()

        def handle_drop(self, items: List[str]) -> None:
            self._last_dropped = items
            for item in items:
                self.recent_files.insertItem(0, item)

            detected = detect_drop_primary_type(items)
            actions = suggest_actions_for_type(detected)
            customer, project = _extract_customer_project("\n".join(items))
            confidence = max(0.35, min(0.99, 0.45 + 0.12 * len([x for x in items if detect_content_type(x) == detected])))
            reason = _drop_reason(items[0], detected)

            self._render_smart_actions(detected)
            self.command_input.setPlainText(items[0])
            self._update_context(f"Customer: {customer}\nProject: {project}")

            markdown = "\n".join(
                [
                    "# Drop analysis",
                    f"- Detected type: {detected}",
                    f"- Customer: {customer}",
                    f"- Project: {project}",
                    f"- Confidence: {confidence:.0%}",
                    f"- Suggested workflow: {actions[0] if actions else 'Remember'}",
                    f"- Reason: {reason}",
                    "",
                    "## Next actions",
                    *[f"- {a}" for a in actions],
                ]
            )
            self._append_message("JPLlamA", markdown, "analysis")
            self._set_status(f"drop:{detected}")
            self._animate_drop_success()

        def _animate_drop_success(self) -> None:
            effect = QGraphicsOpacityEffect(self.drop_zone)
            self.drop_zone.setGraphicsEffect(effect)
            effect.setOpacity(0.55)
            QTimer.singleShot(170, lambda: effect.setOpacity(1.0))
            QTimer.singleShot(300, lambda: self.drop_zone.setGraphicsEffect(None))

        def _run_favorite(self, item: QListWidgetItem) -> None:
            self.command_input.setPlainText(item.text())
            self.run_command_from_input()

        def _open_related(self, item: QListWidgetItem) -> None:
            path = str(item.data(Qt.UserRole) or "").strip()
            if not path:
                return
            p = Path(path)
            if p.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

        def open_latest_result(self) -> None:
            target = self._last_artifacts[0] if self._last_artifacts else None
            if not target:
                QMessageBox.information(self, "Open", "No result file available.")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

        def reveal_latest_result(self) -> None:
            target = self._last_artifacts[0] if self._last_artifacts else None
            if not target:
                QMessageBox.information(self, "Reveal", "No result file available.")
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

        def copy_latest_result_path(self) -> None:
            target = self._last_artifacts[0] if self._last_artifacts else None
            if not target:
                QMessageBox.information(self, "Copy Path", "No result file available.")
                return
            QApplication.clipboard().setText(str(target))
            self.statusBar().showMessage("Result path copied", 1200)

        def open_help(self) -> None:
            HelpDialog(self).exec()

        def open_settings(self) -> None:
            dialog = SettingsDialog(self.theme_name, self)
            if dialog.exec() == QDialog.Accepted:
                selected_theme, issues = dialog.apply()
                self.theme_name = selected_theme
                self.settings_store.setValue("theme", selected_theme)
                self.settings_store.sync()
                self.setStyleSheet(THEME_STYLES.get(selected_theme, MODERN_STYLESHEET))
                self.backend = create_backend()
                self._refresh_side_panels()
                if issues["errors"]:
                    QMessageBox.warning(self, "Settings", "Configuration has errors. Open Health for details.")

        def open_about(self) -> None:
            AboutDialog(note_count=self._count_notes(settings.obsidian_vault.expanduser()), parent=self).exec()

        def _clear_conversation(self) -> None:
            self._conversation_history.clear()
            self._render_conversation()

    def main() -> None:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
        plugin_root = os.environ.get("QT_PLUGIN_PATH", "").strip()
        if plugin_root:
            from PySide6.QtCore import QCoreApplication

            QCoreApplication.setLibraryPaths([plugin_root])

        app = QApplication([])
        app.setWindowIcon(build_logo_icon())
        window = MainWindow()
        window.show()
        app.exec()

except ImportError:
    def main() -> None:
        raise RuntimeError("PySide6 is required for the GUI. Install with: pip install PySide6")


if __name__ == "__main__":
    main()
