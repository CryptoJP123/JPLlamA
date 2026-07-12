from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import Counter, defaultdict
from pathlib import Path
import os
import hashlib
import json
import logging
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple


logger = logging.getLogger(__name__)


BASE_FOLDERS: Tuple[str, ...] = (
    "Customers",
    "Projects",
    "Meetings",
    "DPWorld",
    "Leadership",
    "AI",
    "HiFi",
    "Finance",
    "Travel",
    "Personal",
    "Reference",
    "Ideas",
    "Presentations",
    "Emails",
    "RFQs",
    "Archive",
    "Review",
    "Templates",
)

INDEX_PAGES: Tuple[str, ...] = (
    "Customers.md",
    "Projects.md",
    "Meetings.md",
    "Leadership.md",
    "HiFi.md",
    "AI.md",
    "DPWorld.md",
    "Reference.md",
    "RFQ.md",
    "RFQs.md",
    "Emails.md",
    "Presentations.md",
)

IGNORED_DIR_NAMES: Set[str] = {
    "attachments",
    "resources",
    "resource",
    "media",
    "images",
    "img",
    "assets",
    "organizerbackups",
    ".obsidian",
    ".trash",
    ".git",
    "__pycache__",
}

ORGANIZER_MODES: Set[str] = {"dry-run", "analyze", "organize", "repair"}
IMPORT_LOCK_FILES: Tuple[str, ...] = (".import.lock", "import.lock", ".obsidian-import.lock")

IGNORED_EXTENSIONS: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
}

CUSTOMER_HINTS: Tuple[str, ...] = (
    "Bayer",
    "VW",
    "Volkswagen",
    "TDK",
    "Reckitt",
    "DP World",
    "Amazon",
    "Microsoft",
    "Google",
    "Apple Inc",
)

IMPORT_SOURCE_NAMES: Set[str] = {
    "apple",
    "apple notes",
    "chain iq",
    "chainiq",
    "ciq",
    "hr",
    "private",
    "supplier",
    "old & admin",
}

TECH_KEYWORDS = {
    "AI": {"ai", "ollama", "llm", "model", "prompt", "rag", "agent", "embedding"},
    "HiFi": {"hifi", "audio", "speaker", "amplifier", "dac", "headphone"},
    "DPWorld": {"dpworld", "cargo", "logistics", "port", "terminal", "shipping"},
    "Finance": {"finance", "budget", "pnl", "invoice", "cost", "pricing", "revenue"},
    "Travel": {"travel", "flight", "hotel", "trip", "itinerary", "passport"},
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "in", "is", "it",
    "of", "on", "or", "that", "the", "to", "was", "were", "with", "this", "these", "those",
}

NOISY_CUSTOMER_VALUES = {
    "archive",
    "duplicates",
    "review",
    "reference",
    "customers",
    "projects",
    "meetings",
    "ideas",
    "personal",
    "templates",
    "apple notes",
    "duplicates",
    "review",
}

NOISY_PROJECT_PATTERNS = (
    r"^\W*$",
    r"^\*+.*\*+$",
    r"^\[\[.*\]\]$",
    r"^[-*]\s+",
    r"^summary:\s*",
)

DISALLOWED_FOLDER_TOKENS: Set[str] = {
    "already",
    "portal",
    "look",
    "our",
    "written",
    "process",
    "contractpptx",
    "details",
    "very",
    "can",
    "check",
    "drawing",
    "jpllama",
    "related",
}

IMAGE_EXTENSIONS: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
}


@dataclass
class NoteRecord:
    path: Path
    rel_path: Path
    text: str
    frontmatter: Dict[str, object]
    body: str
    title: str
    analysis: Dict[str, object]
    links: Set[str]
    backlinks: Set[str]


@dataclass
class OrganizerResult:
    folders_created: int
    notes_moved: int
    notes_renamed: int
    notes_archived: int
    duplicates_found: int
    review_items: int
    top_customers: List[Tuple[str, int]]
    top_projects: List[Tuple[str, int]]
    knowledge_graph_stats: Dict[str, int]
    quality_improvement: float
    report_path: str
    mode: str = "organize"
    images_archived: int = 0
    images_kept: int = 0


class ObsidianOrganizer:
    def __init__(self, vault_path: Path, mode: str = "organize", resource_archive_root: Optional[Path] = None):
        self.vault = vault_path.expanduser()
        self.mode = mode
        if self.mode not in ORGANIZER_MODES:
            raise ValueError(f"Unsupported organizer mode: {self.mode}")
        self.created_folders: Set[Path] = set()
        self.move_map: Dict[Path, Path] = {}
        self.rename_count = 0
        self.move_count = 0
        self.archive_count = 0
        self.images_archived = 0
        self.images_kept = 0
        self._backup_run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self._backup_root = self.vault / "Archive" / "OrganizerBackups" / self._backup_run_id
        self._resource_archive_root = (resource_archive_root or (Path.home() / "Library" / "Application Support" / "JPLlamA" / "ArchivedResources")).expanduser()

    def _iter_markdown_paths(self) -> Iterable[Path]:
        for root, dirnames, filenames in os.walk(self.vault):
            dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_DIR_NAMES]
            root_path = Path(root)
            for filename in filenames:
                path = root_path / filename
                suffix = path.suffix.lower()
                if suffix in IGNORED_EXTENSIONS:
                    continue
                if suffix != ".md":
                    continue
                if any(part.lower() in IGNORED_DIR_NAMES for part in path.relative_to(self.vault).parts):
                    continue
                yield path

    def run(self) -> OrganizerResult:
        if not self.vault.exists():
            raise RuntimeError(f"Vault not found: {self.vault}")

        import_lock = self._find_import_lock()
        if import_lock is not None and self.mode in {"organize", "repair"}:
            raise RuntimeError(
                f"Import appears active: lock file present at {import_lock}. "
                "Remove the lock file after import completes, then rerun organizer."
            )

        logger.info("Organizer: scanning vault %s mode=%s", self.vault, self.mode)
        notes = self._load_notes()

        if self.mode == "analyze":
            duplicate_sets = self._find_duplicates(notes)
            duplicate_paths = self._non_canonical_duplicates(duplicate_sets)
            review_paths = self._find_review_items(notes)
            planned_destinations = self._plan_destinations(notes, duplicate_paths, review_paths)
            self.rename_count = sum(
                1
                for old_path, rel in planned_destinations.items()
                if old_path.name != rel.name
            )
            self.move_count = sum(
                1
                for old_path, rel in planned_destinations.items()
                if old_path.relative_to(self.vault) != rel
            )
            self.archive_count = sum(
                1
                for old_path, rel in planned_destinations.items()
                if old_path.relative_to(self.vault) != rel and rel.parts and rel.parts[0] == "Archive"
            )
            result = self._build_result(notes, duplicate_sets, review_paths)
            return result

        if self.mode in {"dry-run", "organize"}:
            self._ensure_base_structure(notes)

        duplicate_sets = self._find_duplicates(notes)
        duplicate_paths = self._non_canonical_duplicates(duplicate_sets)
        review_paths = self._find_review_items(notes)

        if self.mode == "dry-run":
            planned_destinations = self._plan_destinations(notes, duplicate_paths, review_paths)
            self.rename_count = sum(
                1
                for old_path, rel in planned_destinations.items()
                if old_path.name != rel.name
            )
            self.move_count = sum(
                1
                for old_path, rel in planned_destinations.items()
                if old_path.relative_to(self.vault) != rel
            )
            self.archive_count = sum(
                1
                for old_path, rel in planned_destinations.items()
                if old_path.relative_to(self.vault) != rel and rel.parts and rel.parts[0] == "Archive"
            )
            return self._build_result(notes, duplicate_sets, review_paths)

        if self.mode == "organize":
            planned_destinations = self._plan_destinations(notes, duplicate_paths, review_paths)
            self._apply_moves(planned_destinations)
            self._update_links()
            self._archive_unused_images()

        moved_notes = self._reload_notes()
        self._enrich_notes(moved_notes)
        self._create_indexes(moved_notes)
        self._create_backlinks(moved_notes)

        result = self._build_result(moved_notes, duplicate_sets, review_paths)
        return result

    def _read_markdown(self, path: Path) -> Tuple[Dict[str, object], str]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not text.startswith("---\n"):
            return {}, text

        end = text.find("\n---\n", 4)
        if end < 0:
            return {}, text

        block = text[4:end]
        body = text[end + 5 :]

        fm: Dict[str, object] = {}
        current_list: Optional[str] = None
        for raw in block.splitlines():
            line = raw.rstrip()
            if not line:
                continue

            if line.startswith("  - ") and current_list:
                value = line[4:].strip().strip('"').strip("'")
                fm.setdefault(current_list, [])
                if isinstance(fm[current_list], list):
                    fm[current_list].append(value)
                continue

            current_list = None
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value == "":
                fm[key] = []
                current_list = key
            else:
                fm[key] = value

        return fm, body

    def _load_notes(self) -> List[NoteRecord]:
        notes: List[NoteRecord] = []
        for path in sorted(self._iter_markdown_paths()):
            rel = path.relative_to(self.vault)
            frontmatter, body = self._read_markdown(path)
            title = self._guess_title(path, body, frontmatter)
            text = path.read_text(encoding="utf-8", errors="ignore")
            analysis = self._analyze(path, rel, text, frontmatter, body, title)
            links = self._extract_links(text)
            notes.append(
                NoteRecord(
                    path=path,
                    rel_path=rel,
                    text=text,
                    frontmatter=frontmatter,
                    body=body,
                    title=title,
                    analysis=analysis,
                    links=links,
                    backlinks=set(),
                )
            )
        self._build_backlinks(notes)
        return notes

    def _reload_notes(self) -> List[NoteRecord]:
        return self._load_notes()

    def _find_import_lock(self) -> Optional[Path]:
        for name in IMPORT_LOCK_FILES:
            candidate = self.vault / name
            if candidate.exists():
                return candidate
        return None

    def _backup_file_if_needed(self, path: Path, previous_text: str, next_text: str) -> None:
        if self.mode not in {"organize", "repair"}:
            return
        if previous_text == next_text:
            return
        relative = path.relative_to(self.vault)
        backup_path = self._backup_root / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(previous_text, encoding="utf-8")

    def _safe_write_text(self, path: Path, text: str) -> None:
        try:
            previous = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        except FileNotFoundError:
            return
        self._backup_file_if_needed(path, previous, text)
        try:
            path.write_text(text, encoding="utf-8")
        except FileNotFoundError:
            return

    def _extract_links(self, text: str) -> Set[str]:
        links: Set[str] = set()
        for match in re.findall(r"\[\[([^\]|#]+)", text):
            target = str(match).strip()
            if target:
                links.add(target)
        for match in re.findall(r"\]\(([^)]+)\)", text):
            target = str(match).strip()
            if target:
                links.add(target)
        return links

    def _build_backlinks(self, notes: List[NoteRecord]) -> None:
        index: Dict[str, NoteRecord] = {}
        for note in notes:
            index[note.path.stem.lower()] = note
            index[note.rel_path.as_posix()[:-3].lower()] = note

        for note in notes:
            for raw_link in note.links:
                key = raw_link.replace(".md", "").strip().lower().lstrip("./")
                target = index.get(key)
                if target and target.path != note.path:
                    target.backlinks.add(note.rel_path.as_posix()[:-3])

    def _tokenize(self, text: str) -> List[str]:
        return [w.lower() for w in re.findall(r"[A-Za-z0-9_]+", text)]

    def _guess_title(self, path: Path, body: str, frontmatter: Dict[str, object]) -> str:
        fm_title = str(frontmatter.get("title") or "").strip()
        if fm_title:
            return fm_title

        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()

        return path.stem.replace("_", " ").replace("-", " ").strip()

    def _extract_people(self, text: str) -> List[str]:
        matches = re.findall(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b", text)
        people = sorted(set(m for m in matches if len(m) <= 40))
        return people[:8]

    def _extract_customer(self, text: str, rel: Path) -> Optional[str]:
        haystack = text[:12000]
        lower = haystack.lower()

        explicit = re.search(r"\b(?:customer|client|account|company)\s*[:\-]\s*([^\n.;]+)", haystack, flags=re.IGNORECASE)
        if explicit:
            candidate = self._clean_label(explicit.group(1))
            if candidate:
                return candidate

        for customer in CUSTOMER_HINTS:
            if customer.lower() in lower:
                return customer

        return None

    def _normalize_customer_name(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = self._clean_label(value)
        if not cleaned:
            return None

        low_cleaned = cleaned.lower()
        if low_cleaned in IMPORT_SOURCE_NAMES:
            return None
        if "apple notes" in low_cleaned:
            return None
        if low_cleaned == "apple":
            return None
        if "apple inc" in low_cleaned:
            return "Apple Inc"

        # Normalize broad DP World name variants to one canonical label.
        normalized = re.sub(r"\s+", " ", cleaned).strip()
        low = normalized.lower().replace("-", " ")
        if re.search(r"\bdp\s*world\b", low) or "dpworld" in low:
            return "DP World"
        if "global forwarding" in low and ("dp" in low or "world" in low):
            return "DP World"
        if "freight forwarding" in low and ("dp" in low or "world" in low):
            return "DP World"
        if low in {"vw", "volkswagen"}:
            return "VW"
        if "volkswagen" in low:
            return "VW"

        return normalized

    def _extract_project(self, title: str, text: str) -> Optional[str]:
        if "project" in title.lower():
            return title

        lines = [line.strip() for line in text.splitlines()[:20] if line.strip()]
        for line in lines:
            if re.search(r"\b(project|initiative|roadmap|milestone)\b", line, flags=re.IGNORECASE):
                return re.sub(r"\s+", " ", line)[:80]
        return None

    def _extract_meeting(self, title: str, text: str) -> Optional[str]:
        full = f"{title}\n{text[:2000]}"
        if re.search(r"\b(meeting|agenda|minutes|sync|workshop|standup)\b", full, flags=re.IGNORECASE):
            return title[:80]
        return None

    def _extract_topic(self, title: str, tokens: List[str]) -> str:
        if title.strip():
            return title.strip()[:80]
        if tokens:
            return " ".join(tokens[:6])
        return "General"

    def _extract_technology(self, tokens: List[str]) -> List[str]:
        found = []
        token_set = set(tokens)
        for label, keywords in TECH_KEYWORDS.items():
            if token_set.intersection(keywords):
                found.append(label)
        return found

    def _compute_confidence(self, signals: List[bool], token_count: int) -> float:
        score = 0.35 + (0.08 * sum(1 for s in signals if s)) + min(0.2, token_count / 5000.0)
        return round(min(0.99, score), 2)

    def _analyze(
        self,
        path: Path,
        rel: Path,
        text: str,
        frontmatter: Dict[str, object],
        body: str,
        title: str,
    ) -> Dict[str, object]:
        aliases = frontmatter.get("aliases") if isinstance(frontmatter.get("aliases"), list) else []
        fm_summary = str(frontmatter.get("summary") or "")
        merged = "\n".join(
            [
                title,
                " ".join(str(a) for a in aliases),
                fm_summary,
                text[:12000],
            ]
        )
        tokens = self._tokenize(merged)

        customer = self._normalize_customer_name(self._extract_customer(merged, rel))
        company = customer
        project = self._extract_project(title, merged)
        meeting = self._extract_meeting(title, merged)
        technology = self._extract_technology(tokens)
        people = self._extract_people(merged)
        topic = self._extract_topic(title, tokens)

        signals = [
            bool(frontmatter),
            bool(customer),
            bool(project),
            bool(meeting),
            bool(technology),
            bool(people),
            bool(aliases),
            bool(fm_summary),
            len(tokens) > 50,
        ]
        confidence = self._compute_confidence(signals, len(tokens))

        return {
            "topic": topic,
            "customer": customer,
            "company": company,
            "project": project,
            "meeting": meeting,
            "technology": technology,
            "people": people,
            "confidence": confidence,
        }

    def _ensure_dir(self, path: Path) -> None:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            self.created_folders.add(path)

    def _ensure_base_structure(self, notes: List[NoteRecord]) -> None:
        for folder in BASE_FOLDERS:
            self._ensure_dir(self.vault / folder)

        self._ensure_dir(self.vault / "Archive" / "Duplicates")
        self._ensure_dir(self.vault / "Archive" / "Review")

        customer_names = sorted(
            {
                str(note.analysis.get("customer"))
                for note in notes
                if note.analysis.get("customer")
            }
        )
        for customer in customer_names:
            safe = self._sanitize_segment(customer)
            self._ensure_dir(self.vault / "Customers" / safe)

    def _normalize_for_hash(self, text: str) -> str:
        cleaned = re.sub(r"---\n.*?\n---\n", "", text, flags=re.DOTALL)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
        return cleaned

    def _find_duplicates(self, notes: List[NoteRecord]) -> Dict[str, List[NoteRecord]]:
        groups: Dict[str, List[NoteRecord]] = defaultdict(list)
        for note in notes:
            normalized = self._normalize_for_hash(note.text)
            if len(normalized) < 40:
                continue
            digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
            groups[digest].append(note)

        return {
            k: sorted(v, key=lambda n: (len(n.backlinks), len(n.links), -len(n.text)), reverse=True)
            for k, v in groups.items()
            if len(v) > 1
        }

    def _non_canonical_duplicates(self, duplicate_sets: Dict[str, List[NoteRecord]]) -> Set[Path]:
        duplicate_paths: Set[Path] = set()
        for notes in duplicate_sets.values():
            sorted_notes = sorted(notes, key=lambda n: (len(n.rel_path.parts), str(n.rel_path)))
            for dup in sorted_notes[1:]:
                duplicate_paths.add(dup.path)
        return duplicate_paths

    def _is_garbage(self, text: str) -> bool:
        lower = text.lower()
        garbage_patterns = (
            "scanned with",
            "sent from my iphone",
            "apple notes",
            "attachments:",
            "untitled note",
        )
        return any(pattern in lower for pattern in garbage_patterns)

    def _sentence_count(self, text: str) -> int:
        normalized = text.replace("\r\n", "\n")
        line_units = [line.strip() for line in normalized.split("\n") if line.strip()]
        punct_units = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", normalized.strip()))
        return max(len(line_units), len([s for s in punct_units if s.strip()]))

    def _find_review_items(self, notes: List[NoteRecord]) -> Set[Path]:
        review: Set[Path] = set()
        for note in notes:
            content = re.sub(r"---\n.*?\n---\n", "", note.text, flags=re.DOTALL).strip()
            has_core_entity = bool(note.analysis.get("customer") or note.analysis.get("project") or note.analysis.get("meeting"))
            if len(content) < 40:
                review.add(note.path)
                continue
            if self._sentence_count(content) <= 1 and not has_core_entity:
                review.add(note.path)
                continue
            if self._is_garbage(content):
                review.add(note.path)
                continue
            confidence = float(note.analysis.get("confidence") or 0.0)
            if confidence < 0.45:
                review.add(note.path)
                continue
            if not note.links and not note.backlinks and len(content) < 80 and not has_core_entity:
                review.add(note.path)
                continue
        return review

    def _sanitize_segment(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", value).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned[:80] if cleaned else "General"

    def _clean_label(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        cleaned = cleaned.strip("-*_#|:;,. '\"")
        return cleaned

    def _normalize_customer_label(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None

        cleaned = self._clean_label(value)
        if not cleaned:
            return None

        lower = cleaned.lower().strip("'\"")
        if lower in NOISY_CUSTOMER_VALUES:
            return None
        if "[[" in cleaned or "]]" in cleaned:
            return None
        if re.search(r"^\d+\]?\]?$", cleaned):
            return None
        if len(cleaned) < 2 or len(cleaned) > 60:
            return None

        low_tokens = {token for token in re.findall(r"[a-z0-9]+", cleaned.lower())}
        if any(token in DISALLOWED_FOLDER_TOKENS for token in low_tokens):
            return None

        normalized = self._normalize_customer_name(cleaned)
        if not normalized:
            return None
        if normalized.lower() in NOISY_CUSTOMER_VALUES:
            return None
        return normalized

    def _normalize_project_label(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None

        cleaned = self._clean_label(value)
        if not cleaned:
            return None

        if len(cleaned) < 4 or len(cleaned) > 90:
            return None

        lower = cleaned.lower()
        if lower in NOISY_CUSTOMER_VALUES:
            return None
        if lower in {"project", "projects", "initiative", "roadmap"}:
            return None
        if "mailto:" in lower:
            return None
        if "[[" in cleaned or "]]" in cleaned:
            return None
        if re.search(r"^\d+\]?\]?$", cleaned):
            return None

        for pattern in NOISY_PROJECT_PATTERNS:
            if re.search(pattern, cleaned):
                return None

        # Reject lines that look like raw email forwards or checklist bullets.
        if ":" in cleaned and cleaned.lower().startswith(("fwd", "re", "fw")):
            return None

        return cleaned

    def _slugify_filename(self, title: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title.lower()).strip("-")
        if not slug:
            slug = "note"
        return slug[:110]

    def _folder_for_note(self, note: NoteRecord) -> Path:
        analysis = note.analysis
        customer = analysis.get("customer")
        project = analysis.get("project")
        meeting = analysis.get("meeting")
        technology = analysis.get("technology") or []

        folder_parts = [part.lower() for part in note.rel_path.parts]
        if any(part in {"attachments", "resources"} for part in folder_parts):
            return note.rel_path.parent

        tags = note.frontmatter.get("tags") if isinstance(note.frontmatter.get("tags"), list) else []
        source = str(note.frontmatter.get("source") or "").lower()
        tag_set = {str(tag).lower() for tag in tags}
        lower = note.text.lower()

        if "email" in tag_set or source == "email":
            return Path("Emails")
        if "rfq" in tag_set or "rfq" in source:
            return Path("RFQs")
        if "presentation" in tag_set or "presenton" in source or any(key in lower for key in ("presentation", "slides", "deck")):
            return Path("Presentations")
        if any(key in lower for key in ("leadership", "board", "executive committee", "c-suite", "ceo", "coo", "cfo")):
            return Path("Leadership")

        if customer:
            return Path("Customers") / self._sanitize_segment(str(customer))

        tech_set = {str(t) for t in technology}
        if "AI" in tech_set:
            return Path("AI")
        if "HiFi" in tech_set:
            return Path("HiFi")
        if "Finance" in tech_set:
            return Path("Finance")
        if "Travel" in tech_set:
            return Path("Travel")

        if meeting:
            return Path("Meetings")

        if project:
            return Path("Projects")

        if note.backlinks and len(note.backlinks) >= 5:
            return Path("Reference")

        if "template" in lower or note.rel_path.parts and "templates" in note.rel_path.parts[0].lower():
            return Path("Templates")
        if "idea" in lower or "brainstorm" in lower:
            return Path("Ideas")
        if "personal" in lower or "journal" in lower:
            return Path("Personal")

        return Path("Reference")

    def _build_new_rel_path(self, note: NoteRecord, base_folder: Path) -> Path:
        title = str(note.analysis.get("topic") or note.title or note.path.stem)
        clean_title = self._sanitize_segment(title)
        filename = self._slugify_filename(clean_title) + ".md"
        return base_folder / filename

    def _ensure_unique_destination(self, target_rel: Path, source_rel: Path, reserved: Set[Path]) -> Path:
        target = self.vault / target_rel
        if (not target.exists() and target_rel not in reserved) or target_rel == source_rel:
            return target_rel

        stem = target_rel.stem
        suffix = target_rel.suffix
        parent = target_rel.parent
        index = 1
        while True:
            candidate = parent / f"{stem}-{index}{suffix}"
            if candidate not in reserved and not (self.vault / candidate).exists():
                return candidate
            index += 1

    def _plan_destinations(
        self,
        notes: List[NoteRecord],
        duplicate_paths: Set[Path],
        review_paths: Set[Path],
    ) -> Dict[Path, Path]:
        plan: Dict[Path, Path] = {}
        reserved_targets: Set[Path] = set()

        for note in notes:
            if any(part.lower() in IGNORED_DIR_NAMES for part in note.rel_path.parts):
                plan[note.path] = note.rel_path
                reserved_targets.add(note.rel_path)
                continue

            if note.rel_path.name in INDEX_PAGES:
                plan[note.path] = note.rel_path
                reserved_targets.add(note.rel_path)
                continue

            if note.path in duplicate_paths:
                desired = Path("Archive") / "Duplicates" / note.path.name
            elif note.path in review_paths:
                desired = Path("Archive") / "Review" / note.path.name
            else:
                folder = self._folder_for_note(note)
                desired = self._build_new_rel_path(note, folder)

            unique = self._ensure_unique_destination(desired, note.rel_path, reserved_targets)
            plan[note.path] = unique
            reserved_targets.add(unique)
        return plan

    def _apply_moves(self, plan: Dict[Path, Path]) -> None:
        staged_moves: List[Tuple[Path, Path, Path, Path, bool, bool]] = []

        for old_path, target_rel in plan.items():
            if old_path.suffix.lower() != ".md":
                continue

            new_path = self.vault / target_rel
            old_rel = old_path.relative_to(self.vault)

            self._ensure_dir(new_path.parent)

            old_name = old_path.name
            new_name = new_path.name
            renamed = old_name != new_name
            if old_name != new_name:
                self.rename_count += 1

            if old_path.resolve() == new_path.resolve():
                continue

            temp_candidate = old_path.with_name(f"{old_path.name}.jpllama-moving")
            counter = 1
            while temp_candidate.exists():
                temp_candidate = old_path.with_name(f"{old_path.name}.jpllama-moving-{counter}")
                counter += 1

            old_path.rename(temp_candidate)
            staged_moves.append((temp_candidate, new_path, old_rel, target_rel, renamed, target_rel.parts[0] == "Archive"))

        for temp_path, new_path, old_rel, target_rel, _renamed, is_archive in staged_moves:
            if new_path.exists() and temp_path.resolve() != new_path.resolve():
                raise RuntimeError(f"Organizer refused to overwrite existing note: {new_path}")
            self._ensure_dir(new_path.parent)
            temp_path.rename(new_path)
            self.move_map[old_rel] = target_rel
            self.move_count += 1

            if is_archive:
                self.archive_count += 1

    def _unique_stem_map(self) -> Dict[str, str]:
        counts = Counter(rel.stem for rel in self.move_map.keys())
        stem_map: Dict[str, str] = {}
        for old_rel, new_rel in self.move_map.items():
            if counts[old_rel.stem] == 1 and old_rel.stem != new_rel.stem:
                stem_map[old_rel.stem] = new_rel.stem
        return stem_map

    def _replace_managed_block(self, text: str, start: str, end: str, block: str) -> str:
        if start in text and end in text and text.index(start) < text.index(end):
            before = text[: text.index(start)]
            after = text[text.index(end) + len(end) :]
            return before.rstrip() + "\n\n" + block + "\n" + after.lstrip()
        return text.rstrip() + "\n\n" + block + "\n"

    def _update_links(self) -> None:
        if not self.move_map:
            return

        stem_map = self._unique_stem_map()

        for note_path in sorted(self._iter_markdown_paths()):
            try:
                text = note_path.read_text(encoding="utf-8", errors="ignore")
            except FileNotFoundError:
                continue
            updated = text

            for old_rel, new_rel in self.move_map.items():
                old_str = old_rel.as_posix()
                new_str = new_rel.as_posix()
                updated = updated.replace(f"]({old_str})", f"]({new_str})")
                updated = updated.replace(f"]({old_str[:-3]})", f"]({new_str[:-3]})")

                old_wiki_path = old_str[:-3]
                new_wiki_path = new_str[:-3]
                updated = updated.replace(f"[[{old_wiki_path}]]", f"[[{new_wiki_path}]]")
                updated = updated.replace(f"[[{old_wiki_path}|", f"[[{new_wiki_path}|")

            for old_stem, new_stem in stem_map.items():
                updated = updated.replace(f"[[{old_stem}]]", f"[[{new_stem}]]")
                updated = updated.replace(f"[[{old_stem}|", f"[[{new_stem}|")

            if updated != text:
                self._safe_write_text(note_path, updated)

    def _top_keywords(self, text: str, limit: int = 8) -> List[str]:
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9_]+", text)]
        counts: Counter = Counter()
        for word in words:
            if len(word) < 3 or word in STOP_WORDS:
                continue
            counts[word] += 1
        return [word for word, _ in counts.most_common(limit)]

    def _summary(self, body: str, existing: Optional[str] = None, title: Optional[str] = None) -> str:
        if existing and str(existing).strip() and len(str(existing).strip()) > 24:
            return str(existing).strip()[:280]

        clean = re.sub(r"\s+", " ", body).strip()
        if not clean:
            return "No summary available."
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        head = " ".join(sentences[:2])[:280]
        if title and title.lower() not in head.lower() and len(title) < 80:
            return f"{title}: {head}"[:280]
        return head

    def _write_note(self, note: NoteRecord, frontmatter: Dict[str, object], body: str) -> None:
        order = [
            "title", "summary", "tags", "keywords", "aliases", "created", "modified", "source",
            "topic", "customer", "company", "project", "meeting", "technology", "people", "confidence",
            "out_links", "backlinks",
        ]

        lines = ["---"]
        emitted = set()

        def emit_field(key: str, value: object) -> None:
            if value is None:
                return
            if isinstance(value, list):
                if not value:
                    return
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {str(item)}")
            else:
                lines.append(f"{key}: \"{str(value).replace(chr(34), chr(39))}\"")

        for key in order:
            if key in frontmatter:
                emit_field(key, frontmatter[key])
                emitted.add(key)

        for key, value in frontmatter.items():
            if key in emitted:
                continue
            emit_field(key, value)

        lines.append("---")
        rendered = "\n".join(lines) + "\n\n" + body.strip() + "\n"
        self._safe_write_text(note.path, rendered)

    def _enrich_notes(self, notes: List[NoteRecord]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        reverse_move_map: Dict[Path, Path] = {new_rel: old_rel for old_rel, new_rel in self.move_map.items()}

        for note in notes:
            fm = dict(note.frontmatter)
            analysis = note.analysis
            old_rel = reverse_move_map.get(note.rel_path)

            fm["title"] = note.title
            fm["summary"] = self._summary(note.body, existing=fm.get("summary"), title=note.title)

            existing_tags = fm.get("tags") if isinstance(fm.get("tags"), list) else []
            computed_tags = set(str(t).lower() for t in existing_tags)

            folder_tag = note.rel_path.parts[0].lower() if note.rel_path.parts else "reference"
            computed_tags.add(folder_tag)
            if analysis.get("customer"):
                computed_tags.add(str(analysis["customer"]).lower().replace(" ", "-"))
            if analysis.get("project"):
                computed_tags.add("project")
            if analysis.get("meeting"):
                computed_tags.add("meeting")
            for tech in analysis.get("technology", []):
                computed_tags.add(str(tech).lower())

            fm["tags"] = sorted(computed_tags)
            fm["keywords"] = self._top_keywords(note.body)
            aliases = {note.path.stem.replace("-", " "), note.title}
            if old_rel:
                aliases.add(old_rel.stem.replace("-", " ").replace("_", " "))
                aliases.add(old_rel.as_posix()[:-3])
            if analysis.get("customer"):
                aliases.add(str(analysis.get("customer")))
            if analysis.get("project"):
                aliases.add(str(analysis.get("project")))
            for alias in fm.get("aliases") if isinstance(fm.get("aliases"), list) else []:
                aliases.add(str(alias))
            fm["aliases"] = sorted(a for a in aliases if a)

            if old_rel and not fm.get("original_filename"):
                fm["original_filename"] = old_rel.name
            if old_rel and not fm.get("original_path"):
                fm["original_path"] = old_rel.as_posix()

            if not fm.get("created"):
                created = datetime.fromtimestamp(note.path.stat().st_mtime, tz=timezone.utc).isoformat()
                fm["created"] = created
            fm["modified"] = now

            if not fm.get("source"):
                fm["source"] = "apple-notes-import"

            fm["topic"] = analysis.get("topic")
            fm["customer"] = analysis.get("customer")
            fm["company"] = analysis.get("company")
            fm["project"] = analysis.get("project")
            fm["meeting"] = analysis.get("meeting")
            fm["technology"] = analysis.get("technology")
            fm["people"] = analysis.get("people")
            fm["confidence"] = analysis.get("confidence")
            fm["out_links"] = sorted(note.links)[:30]
            fm["backlinks"] = sorted(note.backlinks)[:30]

            self._write_note(note, fm, note.body)

    def _bucket_for_index(self, note: NoteRecord) -> Optional[str]:
        rel = note.rel_path
        head = rel.parts[0] if rel.parts else ""
        tags = note.frontmatter.get("tags") if isinstance(note.frontmatter.get("tags"), list) else []
        source = str(note.frontmatter.get("source") or "").lower()
        tag_set = {str(tag).lower() for tag in tags}

        if "rfq" in tag_set or "rfq" in source:
            return "RFQs.md"
        if "email" in tag_set or source == "email":
            return "Emails.md"

        lower = note.text.lower()
        if "presentation" in tag_set or "presenton" in source or any(key in lower for key in ("presentation", "slides", "deck")):
            return "Presentations.md"
        if any(key in lower for key in ("leadership", "board", "executive committee", "c-suite", "ceo", "coo", "cfo")):
            return "Leadership.md"

        if head == "Customers":
            return "Customers.md"
        if head == "Projects":
            return "Projects.md"
        if head == "Meetings":
            return "Meetings.md"
        if head == "HiFi":
            return "HiFi.md"
        if head == "AI":
            return "AI.md"
        if head in {"DPWorld", "DP World"}:
            return "DPWorld.md"
        if head == "Reference":
            return "Reference.md"
        return None

    def _collect_markdown_references(self) -> Set[str]:
        references: Set[str] = set()
        for note_path in sorted(self._iter_markdown_paths()):
            try:
                text = note_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            parent = note_path.parent
            refs: List[str] = []
            refs.extend(re.findall(r"!\[\[([^\]|#]+)", text))
            refs.extend(re.findall(r"\[[^\]]*\]\(([^)]+)\)", text))
            refs.extend(re.findall(r"\[\[([^\]|#]+\.(?:png|jpg|jpeg|gif|svg|webp|ico))", text, flags=re.IGNORECASE))
            for raw in refs:
                cleaned = str(raw).strip().split("#", 1)[0].split("?", 1)[0].strip()
                if not cleaned:
                    continue
                suffix = Path(cleaned).suffix.lower()
                if suffix not in IMAGE_EXTENSIONS:
                    continue
                direct = (self.vault / cleaned).resolve()
                parent_rel = (parent / cleaned).resolve()
                references.add(str(direct))
                references.add(str(parent_rel))
                references.add(Path(cleaned).name.lower())
        return references

    def _iter_image_paths(self) -> Iterable[Path]:
        for root, dirnames, filenames in os.walk(self.vault):
            dirnames[:] = [d for d in dirnames if d.lower() not in {".obsidian", ".trash", ".git", "__pycache__", "organizerbackups"}]
            root_path = Path(root)
            for filename in filenames:
                path = root_path / filename
                if path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                yield path

    def _archive_unused_images(self) -> None:
        if self.mode != "organize":
            return
        references = self._collect_markdown_references()
        archive_root = self._resource_archive_root / self._backup_run_id
        archive_root.mkdir(parents=True, exist_ok=True)

        archived = 0
        kept = 0
        for image_path in sorted(self._iter_image_paths()):
            rel = image_path.relative_to(self.vault)
            rel_parts = [part.lower() for part in rel.parts]
            if any(part in {"attachments", "resources", "resource"} for part in rel_parts):
                kept += 1
                continue
            image_abs = str(image_path.resolve())
            image_name = image_path.name.lower()
            if image_abs in references or image_name in references:
                kept += 1
                continue
            target = archive_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            candidate = target
            index = 1
            while candidate.exists():
                candidate = target.with_name(f"{target.stem}-{index}{target.suffix}")
                index += 1
            image_path.rename(candidate)
            archived += 1

        self.images_archived = archived
        self.images_kept = kept

    def _create_indexes(self, notes: List[NoteRecord]) -> None:
        buckets: Dict[str, List[Path]] = {name: [] for name in INDEX_PAGES}
        for note in notes:
            index_name = self._bucket_for_index(note)
            if index_name:
                buckets[index_name].append(note.rel_path)

        if "RFQs.md" in buckets and "RFQ.md" in buckets:
            buckets["RFQ.md"] = list(buckets["RFQs.md"])

        for index_name, rels in buckets.items():
            rels = sorted(rels)
            index_path = self.vault / index_name
            if index_path.exists():
                text = index_path.read_text(encoding="utf-8", errors="ignore")
            else:
                text = f"# {index_name[:-3]}\n"

            lines = ["<!-- JPLlama:index:start -->", "## Notes"]
            for rel in rels:
                lines.append(f"- [[{rel.as_posix()[:-3]}]]")
            lines.append("<!-- JPLlama:index:end -->")
            block = "\n".join(lines)
            updated = self._replace_managed_block(text, "<!-- JPLlama:index:start -->", "<!-- JPLlama:index:end -->", block)
            self._safe_write_text(index_path, updated)

    def _create_backlinks(self, notes: List[NoteRecord]) -> None:
        customer_map: Dict[str, List[NoteRecord]] = defaultdict(list)
        project_map: Dict[str, List[NoteRecord]] = defaultdict(list)
        topic_map: Dict[str, List[NoteRecord]] = defaultdict(list)

        for note in notes:
            customer = note.analysis.get("customer")
            project = note.analysis.get("project")
            topic = note.analysis.get("topic")
            if customer:
                customer_map[str(customer)].append(note)
            if project:
                project_map[str(project)].append(note)
            if topic:
                topic_map[str(topic)].append(note)

        for note in notes:
            related: Set[str] = set()

            customer = note.analysis.get("customer")
            project = note.analysis.get("project")
            topic = note.analysis.get("topic")

            if customer:
                for candidate in customer_map.get(str(customer), []):
                    if candidate.path != note.path:
                        related.add(candidate.rel_path.as_posix()[:-3])
            if project:
                for candidate in project_map.get(str(project), []):
                    if candidate.path != note.path:
                        related.add(candidate.rel_path.as_posix()[:-3])
            if topic:
                for candidate in topic_map.get(str(topic), []):
                    if candidate.path != note.path:
                        related.add(candidate.rel_path.as_posix()[:-3])

            for linked in note.links:
                related.add(str(linked).replace(".md", ""))
            for backlink in note.backlinks:
                related.add(str(backlink).replace(".md", ""))

            self_ref = note.rel_path.as_posix()[:-3]
            if self_ref in related:
                related.remove(self_ref)

            if not related:
                continue

            related_list = sorted(related)[:12]
            lines = ["<!-- JPLlama:related:start -->", "## Related"]
            lines.extend(f"- [[{item}]]" for item in related_list)
            lines.append("<!-- JPLlama:related:end -->")
            block = "\n".join(lines)

            text = note.path.read_text(encoding="utf-8", errors="ignore")
            updated = self._replace_managed_block(
                text,
                "<!-- JPLlama:related:start -->",
                "<!-- JPLlama:related:end -->",
                block,
            )
            if updated != text:
                self._safe_write_text(note.path, updated)

    def _is_internal_link(self, raw_link: str) -> bool:
        candidate = str(raw_link or "").strip()
        if not candidate:
            return False
        if "://" in candidate:
            return False
        if candidate.startswith("mailto:"):
            return False
        if candidate.startswith("#"):
            return False
        if candidate.startswith("data:"):
            return False
        base = candidate.split("#", 1)[0].split("?", 1)[0].strip()
        suffix = Path(base).suffix.lower()
        if suffix and suffix != ".md":
            return False
        return True

    def _canonical_internal_link(self, raw_link: str) -> str:
        value = str(raw_link or "").strip()
        value = value.split("#", 1)[0].strip().lstrip("./")
        value = value.replace("\\", "/")
        if value.endswith(".md"):
            value = value[:-3]
        return value.lower().strip("/")

    def _broken_link_count(self, notes: List[NoteRecord]) -> int:
        available: Set[str] = set()
        for note in notes:
            stem = note.path.stem.lower()
            rel = note.rel_path.as_posix()[:-3].lower()
            available.add(stem)
            available.add(rel)

        broken = 0
        for note in notes:
            for raw_link in note.links:
                if not self._is_internal_link(raw_link):
                    continue
                canonical = self._canonical_internal_link(raw_link)
                if not canonical:
                    continue
                if canonical in available:
                    continue
                broken += 1
        return broken

    def _missing_file_count(self, notes: List[NoteRecord]) -> int:
        return sum(1 for note in notes if not note.path.exists())

    def _build_result(
        self,
        notes: List[NoteRecord],
        duplicate_sets: Dict[str, List[NoteRecord]],
        review_paths: Set[Path],
    ) -> OrganizerResult:
        customer_counter = Counter()
        project_counter = Counter()
        entities = 0
        total_out_links = 0
        total_backlinks = 0
        confident_notes = 0

        for note in notes:
            if note.rel_path.parts and note.rel_path.parts[0] == "Archive":
                continue

            customer = self._normalize_customer_label(note.analysis.get("customer"))
            project = self._normalize_project_label(note.analysis.get("project"))
            people = note.analysis.get("people") or []
            tech = note.analysis.get("technology") or []
            if customer:
                customer_counter[customer] += 1
            if project:
                project_counter[project] += 1
            entities += len(people) + len(tech) + (1 if customer else 0) + (1 if project else 0)
            total_out_links += len(note.links)
            total_backlinks += len(note.backlinks)
            if float(note.analysis.get("confidence") or 0.0) >= 0.65:
                confident_notes += 1

        graph_stats = {
            "notes": len(notes),
            "links_updated": len(self.move_map),
            "entities": entities,
            "index_pages": len(INDEX_PAGES),
            "outgoing_links": total_out_links,
            "backlinks": total_backlinks,
            "high_confidence_notes": confident_notes,
        }

        broken_links = self._broken_link_count(notes)
        missing_files = self._missing_file_count(notes)
        graph_stats["broken_links"] = broken_links
        graph_stats["missing_files"] = missing_files

        quality = min(
            97.0,
            35.0
            + (self.move_count * 0.008)
            + (entities * 0.002)
            + (total_backlinks * 0.001)
            + (confident_notes * 0.01),
        )

        report = {
            "folders_created": len(self.created_folders),
            "folders_removed": 0,
            "notes_moved": self.move_count,
            "notes_renamed": self.rename_count,
            "notes_archived": self.archive_count,
            "duplicates_found": sum(len(v) - 1 for v in duplicate_sets.values()),
            "review_items": len(review_paths),
            "images_archived": self.images_archived,
            "images_kept": self.images_kept,
            "attachments_preserved": True,
            "broken_links": broken_links,
            "missing_files": missing_files,
            "top_customers": customer_counter.most_common(10),
            "top_projects": project_counter.most_common(10),
            "knowledge_graph_statistics": graph_stats,
            "estimated_vault_quality_improvement": round(quality, 2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        if self.mode == "analyze":
            report_name = "organizer_report.analyze.json"
        elif self.mode == "dry-run":
            report_name = "organizer_report.dry-run.json"
        elif self.mode == "repair":
            report_name = "organizer_report.repair.json"
        else:
            report_name = "organizer_report.json"

        report_path = self.vault / "Archive" / report_name
        self._ensure_dir(report_path.parent)
        report["mode"] = self.mode
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        return OrganizerResult(
            folders_created=report["folders_created"],
            notes_moved=report["notes_moved"],
            notes_renamed=report["notes_renamed"],
            notes_archived=report["notes_archived"],
            duplicates_found=report["duplicates_found"],
            review_items=report["review_items"],
            top_customers=report["top_customers"],
            top_projects=report["top_projects"],
            knowledge_graph_stats=graph_stats,
            quality_improvement=report["estimated_vault_quality_improvement"],
            report_path=str(report_path),
            mode=self.mode,
            images_archived=self.images_archived,
            images_kept=self.images_kept,
        )


def run_obsidian_organizer(vault_path: Path, *, mode: str = "organize", resource_archive_root: Optional[Path] = None) -> OrganizerResult:
    organizer = ObsidianOrganizer(vault_path=vault_path, mode=mode, resource_archive_root=resource_archive_root)
    return organizer.run()
