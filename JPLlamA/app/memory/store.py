from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil
import zipfile
from typing import Dict, List, Optional, Sequence, Tuple

from app.config import settings
from app.email.models import EmailWorkflowResult
from app.intelligence.knowledge_library import ensure_system_library, upsert_catalog_entry


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}

EMAILS_FOLDER = "eMails to Remember"
PRESENTATIONS_FOLDER_CANDIDATES: Tuple[str, ...] = (
    "PPTX to Remember",
    "Presentation Powerpoint Knowledge Base",
)
RFQ_FOLDER = "RFQ Contract Review Knowledge Base"

SPECIAL_FOLDERS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("DP World", ("dp world", "dpworld")),
    ("Cargo Partner", ("cargo partner",)),
    ("CIQ AWK recovery", ("ciq", "awk recovery")),
    ("RKC Cumbria", ("rkc", "cumbria")),
    ("HandNotes", ("handwritten", "handnotes", "hand notes")),
)

FOLDER_KEYWORDS = {
    "lessons learned": {"lesson", "lessons", "learned", "outcome", "decision", "retrospective"},
    "customers": {"customer", "client", "account", "stakeholder"},
    "projects": {"project", "roadmap", "milestone", "delivery", "plan", "launch"},
    "meetings": {"meeting", "agenda", "minutes", "sync", "workshop", "standup"},
    "ideas": {"idea", "brainstorm", "concept", "draft", "proposal"},
    "personal": {"personal", "journal", "reflection", "habit", "health", "family"},
    "reference": {"reference", "note", "documentation", "guide", "manual"},
    "hifi": {"hifi", "audio", "speaker", "amplifier", "dac", "headphone"},
    "ai": {"ai", "ollama", "llm", "model", "prompt", "machine", "learning"},
    "dp world": {"dpworld", "dp", "port", "shipping", "logistics", "terminal"},
}

LESSON_FOLDER_CANDIDATES: Tuple[str, ...] = ("Lessons Learned", "Lessons", "Learning")

def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> List[str]:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def _generate_title(text: str) -> str:
    sents = _sentences(text)
    if sents:
        title_words = sents[0].split()[:8]
        raw_title = " ".join(title_words)
    else:
        words = _normalize_whitespace(text).split()[:8]
        raw_title = " ".join(words)

    raw_title = raw_title.strip(" .:-")
    if not raw_title:
        return "New Memory"
    return raw_title[:80]


def _generate_summary(text: str) -> str:
    sents = _sentences(text)
    if not sents:
        return ""
    summary = " ".join(sents[:2])
    return summary[:300]


def _generate_tags(text: str, limit: int = 5) -> List[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9_]+", text)]
    counts: Dict[str, int] = {}
    for word in words:
        if len(word) < 3 or word in STOP_WORDS:
            continue
        counts[word] = counts.get(word, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:limit]]


def _extract_aliases(title: str, text: str, limit: int = 6) -> List[str]:
    aliases: List[str] = []
    title_alias = title.strip()
    if title_alias:
        aliases.append(title_alias)

    first_sentence = _sentences(text)
    if first_sentence:
        aliases.append(first_sentence[0][:80].strip(" .:-"))

    acronym_tokens = re.findall(r"\b[A-Z][A-Za-z0-9]+\b", text)
    if acronym_tokens:
        aliases.extend(acronym_tokens[:3])

    deduped: List[str] = []
    seen = set()
    for item in aliases:
        clean = item.strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        deduped.append(clean)
        if len(deduped) >= limit:
            break
    return deduped


def _resolve_existing_folder(target_vault: Path, folder_name: str) -> Optional[Path]:
    target = re.sub(r"\s+", " ", folder_name).strip().lower()
    if not target_vault.exists() or not target:
        return None

    exact_top = target_vault / folder_name
    if exact_top.exists() and exact_top.is_dir():
        return exact_top

    matches: List[Path] = []
    for directory in target_vault.rglob("*"):
        normalized_name = re.sub(r"\s+", " ", directory.name).strip().lower()
        if directory.is_dir() and normalized_name == target:
            matches.append(directory)
    if not matches:
        return None
    matches.sort(key=lambda path: len(path.parts))
    return matches[0]


def _choose_existing_folder(text: str, source: str, target_vault: Path) -> Path:
    lowered_text = text.lower()

    if source.lower() == "lesson":
        for candidate in LESSON_FOLDER_CANDIDATES:
            lesson_folder = _resolve_existing_folder(target_vault, candidate)
            if lesson_folder is not None:
                return lesson_folder

    for folder_name, patterns in SPECIAL_FOLDERS:
        if any(pattern in lowered_text for pattern in patterns):
            folder_path = _resolve_existing_folder(target_vault, folder_name)
            if folder_path is not None:
                return folder_path

    if "email" in source.lower():
        folder_path = _resolve_existing_folder(target_vault, EMAILS_FOLDER)
        if folder_path is not None:
            return folder_path

    words = {w.lower() for w in re.findall(r"[A-Za-z0-9_]+", text)}
    best_match: Optional[Path] = None
    best_score = -1
    for child in target_vault.iterdir() if target_vault.exists() else []:
        if not child.is_dir():
            continue
        if "jpllama" in child.name.lower():
            continue
        folder_name = child.name.strip().lower()
        keyword_score = len(words.intersection(FOLDER_KEYWORDS.get(folder_name, set())))
        token_score = sum(1 for token in folder_name.split() if token in words)
        score = keyword_score * 2 + token_score
        if score > best_score:
            best_score = score
            best_match = child

    if best_match is None:
        raise ValueError("No existing folders found in vault. User must create folders before storing knowledge.")
    return best_match


def _slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug or "memory"


def _yaml_escape(value: str) -> str:
    return value.replace('"', "'")


def _tokenize(text: str) -> List[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z0-9_]+", text) if len(w) > 2 and w.lower() not in STOP_WORDS]


def _build_markdown(
    title: str,
    summary: str,
    tags: List[str],
    aliases: List[str],
    related: List[str],
    backlinks: List[str],
    text: str,
    created_at: datetime,
    source: str,
) -> str:
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)
    aliases_yaml = "\n".join(f"  - \"{_yaml_escape(alias)}\"" for alias in aliases)
    related_yaml = "\n".join(f"  - \"{_yaml_escape(item)}\"" for item in related)
    backlinks_yaml = "\n".join(f"  - \"{_yaml_escape(item)}\"" for item in backlinks)
    aliases_block = aliases_yaml if aliases_yaml else '  - "memory"'
    related_block = related_yaml if related_yaml else '  - "none"'
    backlinks_block = backlinks_yaml if backlinks_yaml else '  - "none"'
    related_section = "\n".join(f"- [[{item}]]" for item in related) if related else "- none"
    return (
        "---\n"
        f"title: \"{_yaml_escape(title)}\"\n"
        f"created: {created_at.isoformat()}\n"
        "tags:\n"
        f"{tags_yaml if tags_yaml else '  - memory'}\n"
        "aliases:\n"
        f"{aliases_block}\n"
        f"summary: \"{_yaml_escape(summary or 'No summary available.')}\"\n"
        "related:\n"
        f"{related_block}\n"
        "backlinks:\n"
        f"{backlinks_block}\n"
        f"source: \"{_yaml_escape(source)}\"\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Summary\n"
        f"{summary or 'No summary available.'}\n\n"
        "## Related Notes\n"
        + related_section
        + "\n\n"
        "## Details\n"
        f"{text.strip()}\n"
    )


def _note_title_from_path(path: Path) -> str:
    return path.stem.replace("-", " ").strip() or "Untitled"


def _render_related_links(related_notes: Sequence[Dict[str, str]]) -> str:
    if not related_notes:
        return "- none\n"
    lines = []
    for item in related_notes[:8]:
        path = str(item.get("path") or "")
        if not path:
            continue
        title = _note_title_from_path(Path(path))
        lines.append(f"- [[{title}]]")
    return "\n".join(lines) + ("\n" if lines else "- none\n")


def _render_actions_section(result: EmailWorkflowResult) -> str:
    actions = result.actions
    sections = [
        ("To Do", actions.todos),
        ("Deadlines", actions.deadlines),
        ("Follow-ups", actions.follow_ups),
        ("Risks", actions.risks),
        ("Decisions", actions.decisions),
    ]
    lines: List[str] = []
    for header, values in sections:
        lines.append(f"### {header}")
        if values:
            for value in values[:8]:
                lines.append(f"- {value}")
        else:
            lines.append("- none")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _append_unique_line(path: Path, line: str) -> None:
    if not path.exists() or not path.is_file():
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    if line in text:
        return

    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _append_backlink(note_path: Path, email_title: str) -> None:
    if not note_path.exists() or note_path.suffix.lower() != ".md":
        return
    text = note_path.read_text(encoding="utf-8", errors="ignore")
    backlink = f"- [[{email_title}]]"
    if backlink in text:
        return

    section = "\n## Linked Emails\n"
    if "\n## Linked Emails\n" not in text:
        text = text.rstrip() + section + backlink + "\n"
    else:
        text = text.rstrip() + "\n" + backlink + "\n"
    note_path.write_text(text, encoding="utf-8")


def _score_note(query_terms: Sequence[str], text: str, path: Path) -> int:
    if not query_terms:
        return 0
    lower = text.lower()
    basename = path.stem.lower()
    score = 0
    for term in query_terms:
        score += lower.count(term) * 3
        score += basename.count(term) * 2
    return score


def _resolve_related_titles(items: Sequence[Dict[str, str]]) -> List[str]:
    titles: List[str] = []
    seen = set()
    for item in items:
        path_value = str(item.get("path") or "").strip()
        if not path_value:
            continue
        title = _note_title_from_path(Path(path_value))
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles


def _find_duplicate_note(target_vault: Path, text: str) -> Optional[Path]:
    needle = _normalize_whitespace(text).lower()
    if not needle:
        return None
    for md_file in target_vault.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if needle and needle in _normalize_whitespace(content).lower():
            return md_file
    return None


def _ensure_existing_required_folder(target_vault: Path, folder_name: str) -> Path:
    folder_path = _resolve_existing_folder(target_vault, folder_name)
    if folder_path is None:
        raise ValueError(
            f"Required folder '{folder_name}' does not exist in vault. User must create this folder before storing knowledge."
        )
    return folder_path


def _resolve_presentation_folder(target_vault: Path) -> Path:
    for candidate in PRESENTATIONS_FOLDER_CANDIDATES:
        folder_path = _resolve_existing_folder(target_vault, candidate)
        if folder_path is not None:
            return folder_path
    raise ValueError(
        "Required folder 'PPTX to Remember' does not exist in vault. User must create this folder before storing knowledge."
    )


def resolve_presentation_asset_folder(*, vault_path: Optional[Path] = None) -> Path:
    target_vault = (vault_path or settings.obsidian_vault).expanduser()
    return _resolve_presentation_folder(target_vault)


def _is_valid_pptx(candidate: Path) -> bool:
    if not candidate.exists() or not candidate.is_file():
        return False
    if candidate.suffix.lower() != ".pptx":
        return False
    if candidate.stat().st_size < 128:
        return False
    try:
        with zipfile.ZipFile(candidate, "r") as archive:
            names = set(archive.namelist())
    except Exception:
        return False

    has_types = "[Content_Types].xml" in names
    has_presentation = "ppt/presentation.xml" in names
    has_slide = any(name.startswith("ppt/slides/slide") and name.endswith(".xml") for name in names)
    return has_types and has_presentation and has_slide


def ensure_presentation_in_vault(
    pptx_path: Optional[str],
    *,
    vault_path: Optional[Path] = None,
    preferred_filename: Optional[str] = None,
    min_mtime: Optional[float] = None,
) -> str:
    target_dir = resolve_presentation_asset_folder(vault_path=vault_path)

    def _fresh_enough(candidate: Path) -> bool:
        if min_mtime is None:
            return True
        try:
            return candidate.stat().st_mtime >= min_mtime
        except Exception:
            return False

    if preferred_filename:
        preferred_candidate = target_dir / preferred_filename
        if _is_valid_pptx(preferred_candidate) and _fresh_enough(preferred_candidate):
            return str(preferred_candidate)

    source = Path(str(pptx_path or "")).expanduser()
    if _is_valid_pptx(source) and _fresh_enough(source):
        if source.parent.resolve() == target_dir.resolve():
            return str(source)
        destination = target_dir / source.name
        shutil.copy2(source, destination)
        if _is_valid_pptx(destination):
            return str(destination)
        destination.unlink(missing_ok=True)

    candidates = [
        candidate
        for candidate in target_dir.glob("*.pptx")
        if candidate.is_file() and _is_valid_pptx(candidate) and _fresh_enough(candidate)
    ]
    if not candidates:
        output_dir = settings.output_dir.expanduser()
        if output_dir.exists():
            candidates = [candidate for candidate in output_dir.rglob("*.pptx") if candidate.is_file()]
            candidates = [
                candidate
                for candidate in candidates
                if not candidate.name.startswith("~$") and _is_valid_pptx(candidate) and _fresh_enough(candidate)
            ]
            if candidates:
                candidates.sort(key=lambda item: (item.stat().st_mtime, item.stat().st_size, str(item)))
                source = candidates[-1]
                destination = target_dir / source.name
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                if _is_valid_pptx(destination):
                    return str(destination)
                destination.unlink(missing_ok=True)
        return ""
    candidates.sort(key=lambda item: (item.stat().st_mtime, item.stat().st_size, str(item)))
    return str(candidates[-1])


def _extract_label_value(text: str, label: str) -> str:
    match = re.search(rf"\b{re.escape(label)}\s*[:\-]\s*([^\n]+)", text, flags=re.IGNORECASE)
    return (match.group(1).strip() if match else "")[:180]


def _extract_lesson_metadata(text: str) -> Dict[str, str]:
    return {
        "situation": _extract_label_value(text, "Situation"),
        "decision": _extract_label_value(text, "Decision"),
        "outcome": _extract_label_value(text, "Outcome"),
        "customer": _extract_label_value(text, "Customer"),
        "project": _extract_label_value(text, "Project"),
        "keywords": _extract_label_value(text, "Keywords"),
    }


def _build_lesson_markdown(
    title: str,
    summary: str,
    tags: List[str],
    aliases: List[str],
    related: List[str],
    backlinks: List[str],
    text: str,
    created_at: datetime,
    source: str,
) -> str:
    fields = _extract_lesson_metadata(text)
    related_section = "\n".join(f"- [[{item}]]" for item in related) if related else "- none"
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags) if tags else "  - lesson"
    aliases_yaml = "\n".join(f"  - \"{_yaml_escape(alias)}\"" for alias in aliases) if aliases else '  - "lesson"'
    related_yaml = "\n".join(f"  - \"{_yaml_escape(item)}\"" for item in related) if related else '  - "none"'
    backlinks_yaml = "\n".join(f"  - \"{_yaml_escape(item)}\"" for item in backlinks) if backlinks else '  - "none"'

    return (
        "---\n"
        f"title: \"{_yaml_escape(title)}\"\n"
        f"created: {created_at.isoformat()}\n"
        "tags:\n"
        f"{tags_yaml}\n"
        "aliases:\n"
        f"{aliases_yaml}\n"
        f"summary: \"{_yaml_escape(summary or 'Lesson learned')}\"\n"
        f"customer: \"{_yaml_escape(fields.get('customer') or 'unknown')}\"\n"
        f"project: \"{_yaml_escape(fields.get('project') or 'unknown')}\"\n"
        f"situation: \"{_yaml_escape(fields.get('situation') or 'not specified')}\"\n"
        f"decision: \"{_yaml_escape(fields.get('decision') or 'not specified')}\"\n"
        f"outcome: \"{_yaml_escape(fields.get('outcome') or 'not specified')}\"\n"
        f"keywords: \"{_yaml_escape(fields.get('keywords') or 'not specified')}\"\n"
        "related:\n"
        f"{related_yaml}\n"
        "backlinks:\n"
        f"{backlinks_yaml}\n"
        f"source: \"{_yaml_escape(source)}\"\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Summary\n"
        f"{summary or 'Lesson learned'}\n\n"
        "## Situation\n"
        f"{fields.get('situation') or 'not specified'}\n\n"
        "## Decision\n"
        f"{fields.get('decision') or 'not specified'}\n\n"
        "## Outcome\n"
        f"{fields.get('outcome') or 'not specified'}\n\n"
        "## Context\n"
        f"- Customer: {fields.get('customer') or 'unknown'}\n"
        f"- Project: {fields.get('project') or 'unknown'}\n"
        f"- Keywords: {fields.get('keywords') or 'not specified'}\n\n"
        "## Related Notes\n"
        f"{related_section}\n\n"
        "## Details\n"
        f"{text.strip()}\n"
    )


def _find_duplicate_note_by_signals(target_vault: Path, signals: Sequence[str], *, search_root: Optional[Path] = None) -> Optional[Path]:
    normalized = [_normalize_whitespace(item).lower() for item in signals if item and len(_normalize_whitespace(item)) >= 12]
    token_sets = [set(_tokenize(item)) for item in normalized]
    if not normalized:
        return None
    root = search_root or target_vault
    for md_file in root.rglob("*.md"):
        try:
            content = _normalize_whitespace(md_file.read_text(encoding="utf-8", errors="ignore")).lower()
        except Exception:
            continue
        content_tokens = set(_tokenize(content))
        substring_match = any(signal in content for signal in normalized)
        token_overlap_match = any(len(tokens.intersection(content_tokens)) >= 3 for tokens in token_sets if tokens)
        if substring_match or token_overlap_match:
            return md_file
    return None


def remember(
    text: str,
    *,
    vault_path: Optional[Path] = None,
    folder: Optional[str] = None,
    source: str = "user",
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    if not text or not text.strip():
        raise ValueError("remember() requires non-empty text")

    target_vault = (vault_path or settings.obsidian_vault).expanduser()
    if not target_vault.exists():
        raise ValueError(f"Vault does not exist: {target_vault}")
    ensure_system_library(target_vault)

    duplicate_path = _find_duplicate_note(target_vault, text)
    if duplicate_path is not None:
        duplicate_summary = _generate_summary(duplicate_path.read_text(encoding="utf-8", errors="ignore"))
        return {
            "title": _note_title_from_path(duplicate_path),
            "summary": duplicate_summary,
            "path": str(duplicate_path),
            "folder": duplicate_path.parent.name,
            "tags": "",
            "source": source,
            "deduplicated": "true",
        }

    if folder:
        target_dir = _ensure_existing_required_folder(target_vault, folder)
    else:
        target_dir = _choose_existing_folder(text, source, target_vault)

    created_at = now or datetime.now()
    title = _generate_title(text)
    tags = _generate_tags(text)
    summary = _generate_summary(text)
    folder_name = target_dir.name
    if folder_name.lower() not in tags:
        tags = [folder_name.lower(), *tags][:6]

    related_hits = search_memory_notes(summary or text, vault_path=target_vault, limit=8)
    related_titles = _resolve_related_titles(related_hits)
    aliases = _extract_aliases(title, text)
    backlinks = related_titles[:8]

    file_stem = f"{created_at.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}"
    note_path = target_dir / f"{file_stem}.md"
    markdown = _build_markdown(
        title=title,
        summary=summary,
        tags=tags,
        aliases=aliases,
        related=related_titles,
        backlinks=backlinks,
        text=text,
        created_at=created_at,
        source=source,
    )
    if source.lower() == "lesson":
        markdown = _build_lesson_markdown(
            title=title,
            summary=summary,
            tags=tags,
            aliases=aliases,
            related=related_titles,
            backlinks=backlinks,
            text=text,
            created_at=created_at,
            source=source,
        )
    note_path.write_text(markdown, encoding="utf-8")

    upsert_catalog_entry(
        target_vault,
        {
            "title": title,
            "artifact_type": "lesson" if source.lower() == "lesson" else "document",
            "source_folder": folder_name,
            "vault_note_path": str(note_path),
            "original_path": "",
            "stored_artifact_path": "",
            "summary": summary,
            "tags": tags,
            "quality_marker": "useful_example",
            "confidence": "medium",
        },
    )

    for item in related_hits:
        linked = Path(str(item.get("path") or ""))
        if linked.exists() and linked.suffix.lower() == ".md" and linked != note_path:
            _append_backlink(linked, title)

    return {
        "title": title,
        "summary": summary,
        "path": str(note_path),
        "folder": folder_name,
        "tags": ",".join(tags),
        "source": source,
    }


def search_memory_notes(
    query: str,
    *,
    vault_path: Optional[Path] = None,
    limit: int = 5,
) -> List[Dict[str, str]]:
    target_vault = (vault_path or settings.obsidian_vault).expanduser()
    if not target_vault.exists():
        return []

    terms = _tokenize(query)
    if not terms:
        return []

    hits: List[Dict[str, str]] = []
    for md_file in target_vault.rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        score = _score_note(terms, text, md_file)
        if score <= 0:
            continue

        summary_match = re.search(r"^summary:\s*\"?([^\n\"]+)\"?", text, flags=re.IGNORECASE | re.MULTILINE)
        if summary_match:
            summary = summary_match.group(1).strip()
        else:
            body = _normalize_whitespace(text)
            summary = body[:220]

        hits.append(
            {
                "path": str(md_file),
                "folder": md_file.parent.name,
                "summary": summary,
                "score": str(score),
            }
        )

    hits.sort(key=lambda item: (-int(item.get("score") or 0), item.get("path") or ""))
    return hits[:limit]


def remember_email_workflow(
    workflow: EmailWorkflowResult,
    *,
    vault_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    target_vault = (vault_path or settings.obsidian_vault).expanduser()
    ensure_system_library(target_vault)
    target_dir = _ensure_existing_required_folder(target_vault, EMAILS_FOLDER)

    duplicate_note = _find_duplicate_note_by_signals(
        target_vault,
        [workflow.message.subject or "", workflow.summary.summary or "", workflow.message.body_text[:600]],
        search_root=target_dir,
    )
    if duplicate_note is not None:
        return {
            "title": _note_title_from_path(duplicate_note),
            "summary": _generate_summary(duplicate_note.read_text(encoding="utf-8", errors="ignore")),
            "path": str(duplicate_note),
            "folder": duplicate_note.parent.name,
            "tags": "",
            "source": "email",
            "deduplicated": "true",
        }

    created_at = now or datetime.now()
    subject = workflow.message.subject or "Email"
    title = _generate_title(subject)
    if not title.lower().startswith("email"):
        title = f"Email - {title}"

    tags = ["email", *workflow.tags[:5]]
    tags = list(dict.fromkeys([tag.lower() for tag in tags if tag]))
    aliases = _extract_aliases(title, workflow.message.subject or workflow.message.body_text)

    file_stem = f"{created_at.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}"
    note_path = target_dir / f"{file_stem}.md"

    related: List[Dict[str, str]] = []
    seen_paths = set()
    for item in [*workflow.obsidian_hits, *workflow.memory_hits]:
        path = str(item.get("path") or "")
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        related.append(item)
    related_links = _render_related_links(related)
    related_titles = _resolve_related_titles(related)
    actions_md = _render_actions_section(workflow)
    body = workflow.message.body_text.strip() or "No email body available."
    deadlines = list(dict.fromkeys([*workflow.actions.deadlines, *workflow.entities.deadlines]))
    people = workflow.entities.people or []
    organizations = workflow.entities.organizations or []
    customers = workflow.entities.customers or []
    projects = workflow.entities.projects or []
    meetings = workflow.entities.meetings or []
    recipients_to = workflow.message.to or []
    recipients_cc = workflow.message.cc or []
    recipients_bcc = workflow.message.bcc or []
    attachments = workflow.message.attachments or []
    metadata_lines = [f"- {key}: {value}" for key, value in sorted((workflow.message.metadata or {}).items())]
    if not metadata_lines:
        metadata_lines = ["- none"]
    attachment_lines = [
        f"- {item.filename} ({item.content_type}, {item.size_bytes} bytes)"
        for item in attachments
    ] or ["- none"]

    markdown = (
        "---\n"
        f"title: \"{_yaml_escape(title)}\"\n"
        f"created: {created_at.isoformat()}\n"
        "tags:\n"
        + "\n".join(f"  - {tag}" for tag in tags)
        + "\n"
        "aliases:\n"
        + "\n".join(f"  - \"{_yaml_escape(alias)}\"" for alias in aliases)
        + "\n"
        f"summary: \"{_yaml_escape(workflow.summary.summary or 'No summary available.')}\"\n"
        "related:\n"
        + ("\n".join(f"  - \"{_yaml_escape(item)}\"" for item in related_titles) if related_titles else "  - \"none\"")
        + "\n"
        "backlinks:\n"
        + ("\n".join(f"  - \"{_yaml_escape(item)}\"" for item in related_titles) if related_titles else "  - \"none\"")
        + "\n"
        "source: \"email\"\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Summary\n"
        f"{workflow.summary.summary or 'No summary available.'}\n\n"
        "## Email Metadata\n"
        f"- Subject: {workflow.message.subject or 'No subject'}\n"
        f"- Sender: {workflow.message.sender or 'Unknown sender'}\n"
        f"- To: {', '.join(recipients_to) if recipients_to else 'none'}\n"
        f"- Cc: {', '.join(recipients_cc) if recipients_cc else 'none'}\n"
        f"- Bcc: {', '.join(recipients_bcc) if recipients_bcc else 'none'}\n"
        f"- Received: {workflow.message.received_at.isoformat() if workflow.message.received_at else 'Unknown'}\n"
        f"- Provider: {workflow.message.provider or 'generic'}\n"
        f"- Provider message id: {workflow.message.provider_message_id or 'unknown'}\n"
        f"- Source path: {workflow.message.source_path or 'unknown'}\n\n"
        "## Attachments\n"
        + "\n".join(attachment_lines)
        + "\n\n"
        "## Metadata\n"
        + "\n".join(metadata_lines)
        + "\n\n"
        "## Deadlines\n"
        + ("\n".join(f"- {item}" for item in deadlines) if deadlines else "- none")
        + "\n\n"
        "## Entities\n"
        f"- Customers: {', '.join(customers) if customers else 'none'}\n"
        f"- Projects: {', '.join(projects) if projects else 'none'}\n"
        f"- Meetings: {', '.join(meetings) if meetings else 'none'}\n"
        f"- People: {', '.join(people) if people else 'none'}\n"
        f"- Organizations: {', '.join(organizations) if organizations else 'none'}\n\n"
        "## Email Metadata\n"
        f"- Subject: {workflow.message.subject or 'No subject'}\n"
        f"- Sender: {workflow.message.sender or 'Unknown sender'}\n"
        f"- Received: {workflow.message.received_at.isoformat() if workflow.message.received_at else 'Unknown'}\n"
        f"- Attachments: {len(workflow.message.attachments)}\n\n"
        "## Detected Entities\n"
        f"- Customers: {', '.join(workflow.entities.customers) if workflow.entities.customers else 'none'}\n"
        f"- Projects: {', '.join(workflow.entities.projects) if workflow.entities.projects else 'none'}\n"
        f"- Meetings: {', '.join(workflow.entities.meetings) if workflow.entities.meetings else 'none'}\n"
        f"- Action items: {', '.join(workflow.entities.action_items) if workflow.entities.action_items else 'none'}\n"
        f"- Deadlines: {', '.join(workflow.entities.deadlines) if workflow.entities.deadlines else 'none'}\n"
        f"- People: {', '.join(workflow.entities.people) if workflow.entities.people else 'none'}\n\n"
        "## Actions\n"
        f"{actions_md}\n"
        "## Related Notes\n"
        f"{related_links}\n"
        "## Original Email\n"
        f"Subject: {workflow.message.subject or 'No subject'}\n"
        f"From: {workflow.message.sender or 'Unknown sender'}\n"
        f"To: {', '.join(recipients_to) if recipients_to else 'none'}\n"
        f"Cc: {', '.join(recipients_cc) if recipients_cc else 'none'}\n"
        f"Bcc: {', '.join(recipients_bcc) if recipients_bcc else 'none'}\n"
        f"Date: {workflow.message.received_at.isoformat() if workflow.message.received_at else 'Unknown'}\n\n"
        f"{body}\n"
    )

    note_path.write_text(markdown, encoding="utf-8")

    upsert_catalog_entry(
        target_vault,
        {
            "title": title,
            "artifact_type": "email",
            "source_folder": target_dir.name,
            "vault_note_path": str(note_path),
            "original_path": workflow.message.source_path or "",
            "stored_artifact_path": str(note_path),
            "summary": workflow.summary.summary,
            "entities": list(dict.fromkeys([*customers, *projects, *people, *organizations])),
            "tags": tags,
            "quality_marker": "useful_example",
            "confidence": "high",
        },
    )

    for item in related:
        linked_path = Path(str(item.get("path") or ""))
        if linked_path.exists() and linked_path != note_path:
            _append_backlink(linked_path, title)

    return {
        "title": title,
        "summary": workflow.summary.summary,
        "path": str(note_path),
        "folder": target_dir.name,
        "tags": ",".join(tags),
        "source": "email",
    }


def remember_rfq_review(
    *,
    title: str,
    summary: str,
    markdown_body: str,
    tags: Sequence[str],
    related_paths: Sequence[str],
    vault_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    target_vault = (vault_path or settings.obsidian_vault).expanduser()
    ensure_system_library(target_vault)
    target_dir = _ensure_existing_required_folder(target_vault, RFQ_FOLDER)

    duplicate_note = _find_duplicate_note_by_signals(
        target_vault,
        [title, summary, markdown_body[:800]],
        search_root=target_dir,
    )
    if duplicate_note is not None:
        return {
            "title": _note_title_from_path(duplicate_note),
            "summary": _generate_summary(duplicate_note.read_text(encoding="utf-8", errors="ignore")),
            "path": str(duplicate_note),
            "folder": duplicate_note.parent.name,
            "tags": "",
            "source": "rfq-workflow",
            "deduplicated": "true",
        }

    created_at = now or datetime.now()
    normalized_title = _generate_title(title)
    if not normalized_title.lower().startswith("rfq"):
        normalized_title = f"RFQ - {normalized_title}"

    combined_tags = ["rfq", "review", *[tag.strip().lower() for tag in tags if tag.strip()]]
    deduped_tags = list(dict.fromkeys(combined_tags))[:8]

    file_stem = f"{created_at.strftime('%Y%m%d-%H%M%S')}-{_slugify(normalized_title)}"
    note_path = target_dir / f"{file_stem}.md"

    related_lines: List[str] = []
    for related in related_paths[:12]:
        related_path = Path(related)
        related_title = _note_title_from_path(related_path)
        related_lines.append(f"- [[{related_title}]]")
    related_block = "\n".join(related_lines) if related_lines else "- none"

    mode = _extract_label_value(markdown_body, "mode") or _extract_label_value(markdown_body, "transport mode")
    customer = _extract_label_value(markdown_body, "customer")
    country = _extract_label_value(markdown_body, "country")
    pricing_issues = _extract_label_value(markdown_body, "pricing issues")
    country_rules = _extract_label_value(markdown_body, "country rules")
    no_go_count = len(re.findall(r"\bno-go\b", markdown_body, flags=re.IGNORECASE))
    challenge_count = len(re.findall(r"\bchallenge\b", markdown_body, flags=re.IGNORECASE))
    standard_count = len(re.findall(r"\bstandard\b", markdown_body, flags=re.IGNORECASE))
    approvals_matches = [x.strip() for x in re.findall(r"sign-off[:\s]+([^\n]+)", markdown_body, flags=re.IGNORECASE)]
    approvals_text = "; ".join(sorted(set(approvals_matches))) or "unknown"
    related_yaml = (
        "\n".join(f"  - \"{_yaml_escape(_note_title_from_path(Path(path)))}\"" for path in related_paths[:12])
        if related_paths
        else '  - "none"'
    )

    markdown = (
        "---\n"
        f"title: \"{_yaml_escape(normalized_title)}\"\n"
        f"created: {created_at.isoformat()}\n"
        "tags:\n"
        + "\n".join(f"  - {tag}" for tag in deduped_tags)
        + "\n"
        f"summary: \"{_yaml_escape(summary or 'RFQ review summary')}\"\n"
        f"customer: \"{_yaml_escape(customer or 'unknown')}\"\n"
        f"country: \"{_yaml_escape(country or 'unknown')}\"\n"
        f"mode: \"{_yaml_escape(mode or 'mixed')}\"\n"
        f"no_go: {no_go_count}\n"
        f"challenge: {challenge_count}\n"
        f"standard: {standard_count}\n"
        f"approvals: \"{_yaml_escape(approvals_text)}\"\n"
        f"pricing_issues: \"{_yaml_escape(pricing_issues or 'not specified')}\"\n"
        f"country_rules: \"{_yaml_escape(country_rules or 'not specified')}\"\n"
        "related:\n"
        + related_yaml
        + "\n"
        "source: \"rfq-workflow\"\n"
        "---\n\n"
        f"# {normalized_title}\n\n"
        "## Summary\n"
        f"{summary or 'RFQ review summary'}\n\n"
        "## RFQ Metadata\n"
        f"- Customer: {customer or 'unknown'}\n"
        f"- Country: {country or 'unknown'}\n"
        f"- Mode: {mode or 'mixed'}\n"
        f"- No-go: {no_go_count}\n"
        f"- Challenge: {challenge_count}\n"
        f"- Standard: {standard_count}\n"
        f"- Pricing issues: {pricing_issues or 'not specified'}\n"
        f"- Country rules: {country_rules or 'not specified'}\n\n"
        "## Related Knowledge\n"
        f"{related_block}\n\n"
        "## Review\n"
        f"{markdown_body.strip()}\n"
    )

    note_path.write_text(markdown, encoding="utf-8")

    upsert_catalog_entry(
        target_vault,
        {
            "title": normalized_title,
            "artifact_type": "rfq_review",
            "customer": customer or "unknown",
            "project": customer or "unknown",
            "source_folder": target_dir.name,
            "vault_note_path": str(note_path),
            "stored_artifact_path": str(note_path),
            "summary": summary,
            "key_details": [
                f"mode={mode or 'mixed'}",
                f"country={country or 'unknown'}",
                f"no_go={no_go_count}",
                f"challenge={challenge_count}",
            ],
            "tags": deduped_tags,
            "topics": ["rfq", "commercial", "legal", "operations"],
            "useful_for": "RFQ review comparison and drafting",
            "related_notes": [str(path) for path in related_paths[:12]],
            "quality_marker": "useful_example",
            "confidence": "high",
        },
    )

    for related in related_paths:
        linked_path = Path(related)
        if linked_path.exists() and linked_path.suffix.lower() == ".md" and linked_path != note_path:
            _append_backlink(linked_path, normalized_title)

    return {
        "title": normalized_title,
        "summary": summary,
        "path": str(note_path),
        "folder": target_dir.name,
        "tags": ",".join(deduped_tags),
        "source": "rfq-workflow",
    }


def remember_presentation_knowledge(
    text: str,
    *,
    vault_path: Optional[Path] = None,
    now: Optional[datetime] = None,
    pptx_path: Optional[str] = None,
    slide_count: Optional[int] = None,
) -> Dict[str, str]:
    target_vault = (vault_path or settings.obsidian_vault).expanduser()
    ensure_system_library(target_vault)
    target_dir = _resolve_presentation_folder(target_vault)

    topic = _extract_label_value(text, "topic") or _generate_title(text)
    summary = _generate_summary(text)
    inferred_pptx_path = pptx_path or _extract_label_value(text, "pptx") or _extract_label_value(text, "path")
    inferred_slide_count = slide_count
    if inferred_slide_count is None:
        slide_text = _extract_label_value(text, "slides")
        if slide_text:
            match = re.search(r"\d+", slide_text)
            if match:
                try:
                    inferred_slide_count = int(match.group(0))
                except Exception:
                    inferred_slide_count = None

    # When a concrete PPTX path is provided, create a fresh note for that specific artifact
    # so post-processing can maintain a one-to-one PPTX <-> note <-> catalog mapping.
    if not inferred_pptx_path:
        duplicate_note = _find_duplicate_note_by_signals(
            target_vault,
            [topic, summary, inferred_pptx_path or "", text[:500]],
            search_root=target_dir,
        )
        if duplicate_note is not None:
            return {
                "title": _note_title_from_path(duplicate_note),
                "summary": _generate_summary(duplicate_note.read_text(encoding="utf-8", errors="ignore")),
                "path": str(duplicate_note),
                "folder": duplicate_note.parent.name,
                "tags": "",
                "source": "presentation",
                "deduplicated": "true",
            }

    created_at = now or datetime.now()
    customer = _extract_label_value(text, "customer")
    project = _extract_label_value(text, "project")
    speaker_notes = _extract_label_value(text, "speaker notes")
    keywords = _extract_label_value(text, "keywords")
    title = f"Presentation - {topic}" if not topic.lower().startswith("presentation") else topic
    tags = ["presentation", *[tag for tag in _generate_tags(text, limit=5) if tag != "presentation"]][:6]

    related_hits = search_memory_notes(f"{topic} {customer} {project}", vault_path=target_vault, limit=8)
    related_titles = _resolve_related_titles(related_hits)
    aliases = _extract_aliases(title, text)
    pptx_filename = Path(inferred_pptx_path).name if inferred_pptx_path else "unknown.pptx"
    pptx_link = f"[{pptx_filename}]({inferred_pptx_path})" if inferred_pptx_path else "unknown"
    slide_value = str(inferred_slide_count) if inferred_slide_count is not None else "unknown"
    keyword_value = keywords or ", ".join(tags[:5])

    file_stem = f"{created_at.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}"
    note_path = target_dir / f"{file_stem}.md"
    markdown = (
        "---\n"
        f"title: \"{_yaml_escape(title)}\"\n"
        f"created: {created_at.isoformat()}\n"
        "tags:\n"
        + "\n".join(f"  - {tag}" for tag in tags)
        + "\n"
        "aliases:\n"
        + "\n".join(f"  - \"{_yaml_escape(alias)}\"" for alias in aliases)
        + "\n"
        f"summary: \"{_yaml_escape(summary or 'No summary available.')}\"\n"
        f"topic: \"{_yaml_escape(topic)}\"\n"
        f"pptx_path: \"{_yaml_escape(inferred_pptx_path or 'unknown')}\"\n"
        f"pptx_filename: \"{_yaml_escape(pptx_filename)}\"\n"
        f"slide_count: {inferred_slide_count if inferred_slide_count is not None else 0}\n"
        f"keywords: \"{_yaml_escape(keyword_value)}\"\n"
        f"customer: \"{_yaml_escape(customer or 'unknown')}\"\n"
        f"project: \"{_yaml_escape(project or 'unknown')}\"\n"
        f"speaker_notes: \"{_yaml_escape(speaker_notes or 'not specified')}\"\n"
        "related:\n"
        + ("\n".join(f"  - \"{_yaml_escape(item)}\"" for item in related_titles) if related_titles else "  - \"none\"")
        + "\n"
        "source: \"presentation\"\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Summary\n"
        f"{summary or 'No summary available.'}\n\n"
        "## Presentation Metadata\n"
        f"- Topic: {topic}\n"
        f"- Customer: {customer or 'unknown'}\n"
        f"- Project: {project or 'unknown'}\n"
        f"- Keywords: {keyword_value or 'not specified'}\n"
        f"- Slides: {slide_value}\n"
        f"- Speaker notes: {speaker_notes or 'not specified'}\n\n"
        "## Original PPTX\n"
        f"- File: {pptx_link}\n"
        f"- Path: {inferred_pptx_path or 'unknown'}\n\n"
        "## Related Presentations\n"
        + ("\n".join(f"- [[{item}]]" for item in related_titles) if related_titles else "- none")
        + "\n\n"
        "## Details\n"
        f"{text.strip()}\n"
    )
    note_path.write_text(markdown, encoding="utf-8")

    upsert_catalog_entry(
        target_vault,
        {
            "title": title,
            "artifact_type": "presentation",
            "customer": customer or "unknown",
            "project": project or "unknown",
            "source_folder": target_dir.name,
            "vault_note_path": str(note_path),
            "original_path": inferred_pptx_path or "",
            "stored_artifact_path": inferred_pptx_path or "",
            "summary": summary,
            "key_details": [
                f"slide_count={slide_value}",
                f"topic={topic}",
            ],
            "tags": tags,
            "topics": [topic],
            "useful_for": "presentation style/pattern reuse",
            "related_notes": [str(item.get("path") or "") for item in related_hits[:8]],
            "quality_marker": "useful_example",
            "confidence": "high",
        },
    )

    for item in related_hits:
        linked = Path(str(item.get("path") or ""))
        if linked.exists() and linked.suffix.lower() == ".md" and linked != note_path:
            _append_backlink(linked, title)

    return {
        "title": title,
        "summary": summary,
        "path": str(note_path),
        "folder": target_dir.name,
        "tags": ",".join(tags),
        "source": "presentation",
    }


def remember_rfq_payload(
    text: str,
    *,
    vault_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    target_vault = (vault_path or settings.obsidian_vault).expanduser()
    summary = _generate_summary(text)
    title = _extract_label_value(text, "title") or _generate_title(text)
    tags = ["rfq", "review", *[tag for tag in _generate_tags(text, limit=4) if tag not in {"rfq", "review"}]]
    related_hits = search_memory_notes(text, vault_path=target_vault, limit=8)
    related_paths = [str(item.get("path") or "") for item in related_hits if str(item.get("path") or "")]
    return remember_rfq_review(
        title=title,
        summary=summary,
        markdown_body=text,
        tags=tags,
        related_paths=related_paths,
        vault_path=target_vault,
        now=now,
    )
