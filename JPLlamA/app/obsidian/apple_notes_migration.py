from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
import os
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from app.obsidian.client import ObsidianClient, ObsidianConfig


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

IMAGE_EXTENSIONS: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
}

MIGRATION_FOLDERS: Tuple[str, ...] = (
    "Customers",
    "Projects",
    "Meetings",
    "DPWorld",
    "Leadership",
    "AI",
    "HiFi",
    "Finance",
    "Travel",
    "Ideas",
    "Personal",
    "Reference",
    "Emails",
    "RFQs",
    "Presentations",
    "Technology",
    "Career",
    "Archive",
)

INDEX_PAGES: Dict[str, str] = {
    "Customers": "Customers.md",
    "Projects": "Projects.md",
    "Meetings": "Meetings.md",
    "Leadership": "Leadership.md",
    "HiFi": "HiFi.md",
    "AI": "AI.md",
    "DPWorld": "DPWorld.md",
    "Reference": "Reference.md",
    "RFQs": "RFQs.md",
    "Emails": "Emails.md",
    "Presentations": "Presentations.md",
    "Technology": "Technology.md",
    "Career": "Career.md",
    "Personal": "Personal.md",
    "Finance": "Finance.md",
    "Travel": "Travel.md",
    "Ideas": "Ideas.md",
}

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

KNOWN_CUSTOMERS: Tuple[str, ...] = (
    "DP World",
    "Bayer",
    "Volkswagen",
    "VW",
    "TDK",
    "Reckitt",
    "Amazon",
    "Google",
    "Microsoft",
    "Apple Inc",
    "Kik",
    "PayCargo",
)


@dataclass
class _Note:
    path: Path
    rel: Path
    text: str
    frontmatter: Dict[str, object]
    body: str
    title: str


@dataclass
class AppleNotesMigrationResult:
    original_apple_notes_count: int
    customers_apple_before: int
    customers_apple_after: int
    migrated_notes: int
    notes_renamed: int
    missing_files: int
    total_markdown_before: int
    total_markdown_after: int
    customers_created: int
    projects_created: int
    meetings_created: int
    personal_created: int
    reference_created: int
    apple_notes_folders_removed: int
    images_archived: int
    broken_links: int
    search_validation: Dict[str, int]
    knowledge_graph: Dict[str, int]


@dataclass
class AppleNotesMigrationEngineResult:
    migration: AppleNotesMigrationResult
    organizer_mode: str
    organizer_notes_moved: int
    organizer_notes_renamed: int
    organizer_duplicates_found: int
    organizer_report_path: str


class AppleNotesMigrator:
    def __init__(self, vault_path: Path, resource_archive_root: Optional[Path] = None):
        self.vault = vault_path.expanduser()
        self.resource_archive_root = (
            resource_archive_root
            or (Path.home() / "Library" / "Application Support" / "JPLlamA" / "ArchivedResources")
        ).expanduser()
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.move_map: Dict[Path, Path] = {}
        self.renamed_notes = 0

    def _iter_markdown_paths(self) -> Iterable[Path]:
        for root, dirnames, filenames in os.walk(self.vault):
            dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_DIR_NAMES]
            root_path = Path(root)
            for filename in filenames:
                path = root_path / filename
                if path.suffix.lower() != ".md":
                    continue
                if any(part.lower() in IGNORED_DIR_NAMES for part in path.relative_to(self.vault).parts):
                    continue
                yield path

    def _read_markdown(self, path: Path) -> Tuple[Dict[str, object], str, str]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not text.startswith("---\n"):
            return {}, text, text

        end = text.find("\n---\n", 4)
        if end < 0:
            return {}, text, text

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

        return fm, body, text

    def _guess_title(self, path: Path, body: str, frontmatter: Dict[str, object]) -> str:
        fm_title = str(frontmatter.get("title") or "").strip()
        if fm_title:
            return fm_title
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem.replace("_", " ").replace("-", " ").strip()

    def _load_notes(self) -> List[_Note]:
        notes: List[_Note] = []
        for path in sorted(self._iter_markdown_paths()):
            try:
                rel = path.relative_to(self.vault)
                fm, body, text = self._read_markdown(path)
                title = self._guess_title(path, body, fm)
                notes.append(_Note(path=path, rel=rel, text=text, frontmatter=fm, body=body, title=title))
            except FileNotFoundError:
                # Vault can be in-flight during large migrations; skip vanished paths.
                continue
        return notes

    def _is_candidate(self, note: _Note) -> bool:
        parts = [p.lower() for p in note.rel.parts]
        if not parts:
            return False

        top = parts[0]
        if parts and parts[0] == "apple notes":
            return True
        if top in IMPORT_SOURCE_NAMES:
            return True
        if len(parts) >= 2 and parts[0] == "customers" and parts[1] == "apple":
            # Keep legacy Customers/Apple only when the note is genuinely about Apple Inc.
            lower = self._semantic_text(note).lower()
            return self._extract_customer(note, lower) != "Apple Inc"
        return False

    def _semantic_text(self, note: _Note) -> str:
        return "\n".join([note.title, note.body])

    def _clean_label(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        cleaned = cleaned.strip("-*#|:;,. '\"")
        return cleaned

    def _normalize_customer(self, value: str) -> Optional[str]:
        cleaned = self._clean_label(value)
        if not cleaned:
            return None
        low = cleaned.lower()

        if low in IMPORT_SOURCE_NAMES:
            return None
        if "apple notes" in low:
            return None

        if re.search(r"\bdp\s*world\b", low) or "dpworld" in low:
            return "DP World"
        if "volkswagen" in low or low == "vw":
            return "VW"
        if low in {"bayer", "tdk", "reckitt", "amazon", "google", "microsoft", "kik", "paycargo"}:
            return cleaned.title() if low not in {"kik", "paycargo", "tdk", "vw"} else {"kik": "Kik", "paycargo": "PayCargo", "tdk": "TDK", "vw": "VW"}[low]

        # Apple is only valid when clearly about Apple Inc, not the import source.
        if low == "apple":
            return None
        if "apple inc" in low:
            return "Apple Inc"
        return cleaned if 2 <= len(cleaned) <= 60 else None

    def _extract_customer(self, note: _Note, lower: str) -> Optional[str]:
        explicit = re.search(
            r"(?:^|[\r\n])\s*(?:customer|client|account|company)\s*:\s*([^\n.;]+)",
            note.text,
            flags=re.IGNORECASE,
        )
        if not explicit:
            explicit = re.search(
                r"\b(?:customer|client|account|company)\s+-\s+([^\n.;]+)",
                note.body,
                flags=re.IGNORECASE,
            )
        if explicit:
            normalized = self._normalize_customer(explicit.group(1))
            if normalized:
                return normalized

        if "dp world" in lower or "dpworld" in lower:
            return "DP World"
        if "volkswagen" in lower or re.search(r"\bvw\b", lower):
            return "VW"
        if re.search(r"\bbayer\b", lower):
            return "Bayer"
        if re.search(r"\btdk\b", lower):
            return "TDK"
        if re.search(r"\breckitt\b", lower):
            return "Reckitt"
        if re.search(r"\bpaycargo\b", lower):
            return "PayCargo"
        if re.search(r"\bkik\b", lower):
            return "Kik"
        # Apple customer must be explicit to avoid import-source leakage.
        if any(token in lower for token in ("apple inc", "cupertino", "iphone", "macbook", "ios", "ipad")):
            return "Apple Inc"
        return None

    def _classify(self, note: _Note) -> Tuple[Path, Dict[str, str]]:
        tags = note.frontmatter.get("tags") if isinstance(note.frontmatter.get("tags"), list) else []
        tag_set = {str(t).lower() for t in tags}
        source = str(note.frontmatter.get("source") or "").lower()
        semantic_text = self._semantic_text(note)
        lower = semantic_text.lower()

        customer = self._extract_customer(note, lower)
        project = "" if not re.search(r"\b(project|roadmap|initiative|program)\b", lower) else note.title[:80]
        meeting = "" if not re.search(r"\b(meeting|minutes|agenda|sync|workshop|standup|call)\b", lower) else note.title[:80]

        if "email" in tag_set or source == "email" or re.search(r"^subject:\s", semantic_text, flags=re.IGNORECASE | re.MULTILINE):
            return Path("Emails"), {"customer": customer or "", "project": project, "meeting": meeting}
        if "rfq" in tag_set or "rfq" in source or re.search(r"\b(rfq|request for quote|tender|bid)\b", lower):
            return Path("RFQs"), {"customer": customer or "", "project": project, "meeting": meeting}
        if "presentation" in tag_set or "presenton" in source or re.search(r"\b(presentation|slide|deck)\b", lower):
            return Path("Presentations"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(leadership|board|executive|c-suite|ceo|coo|cfo)\b", lower):
            return Path("Leadership"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(personal|journal|family|health|private goal|my goals)\b", lower):
            return Path("Personal"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(ollama|llm|prompt|agent|embedding|ai)\b", lower):
            return Path("AI"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(hifi|speaker|amplifier|dac|headphone|audio)\b", lower):
            return Path("HiFi"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(finance|budget|invoice|cost|revenue|pnl)\b", lower):
            return Path("Finance"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(travel|flight|hotel|trip|itinerary|visa|passport)\b", lower):
            return Path("Travel"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(idea|brainstorm)\b", lower):
            return Path("Ideas"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(technology|architecture|platform|system|api|integration|data custodian)\b", lower):
            return Path("Technology"), {"customer": customer or "", "project": project, "meeting": meeting}
        if re.search(r"\b(career|resume|cv|hiring|interview|promotion)\b", lower):
            return Path("Career"), {"customer": customer or "", "project": project, "meeting": meeting}
        if customer == "DP World":
            return Path("DPWorld"), {"customer": customer, "project": project, "meeting": meeting}
        if customer:
            rel_parts = [p.lower() for p in note.rel.parts]
            if customer == "Apple Inc" and len(rel_parts) >= 2 and rel_parts[0] == "customers" and rel_parts[1] == "apple":
                return Path("Customers") / "Apple", {"customer": customer, "project": project, "meeting": meeting}
            safe = self._sanitize_segment(customer)
            return Path("Customers") / safe, {"customer": customer, "project": project, "meeting": meeting}
        if meeting:
            return Path("Meetings"), {"customer": customer or "", "project": project, "meeting": meeting}
        if project:
            return Path("Projects"), {"customer": customer or "", "project": project, "meeting": meeting}
        return Path("Reference"), {"customer": customer or "", "project": project, "meeting": meeting}

    def _sanitize_segment(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", value).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned[:80] if cleaned else "General"

    def _ensure_unique_destination(self, rel: Path, reserved: Set[Path], moving_sources: Set[Path]) -> Path:
        target = self.vault / rel
        if rel not in reserved and (not target.exists() or rel in moving_sources):
            return rel
        stem = rel.stem
        suffix = rel.suffix
        parent = rel.parent
        idx = 1
        while True:
            cand = parent / f"{stem}-{idx}{suffix}"
            if cand not in reserved and (not (self.vault / cand).exists() or cand in moving_sources):
                return cand
            idx += 1

    def _ensure_base_folders(self) -> None:
        for folder in MIGRATION_FOLDERS:
            (self.vault / folder).mkdir(parents=True, exist_ok=True)
        (self.vault / "Archive" / "Review").mkdir(parents=True, exist_ok=True)

    def _apply_moves(self, planned: Dict[Path, Path]) -> int:
        staged: List[Tuple[Path, Path]] = []
        moved = 0
        for old_path, rel_target in planned.items():
            if not old_path.exists():
                continue
            new_path = self.vault / rel_target
            old_rel = old_path.relative_to(self.vault)
            if old_rel == rel_target:
                continue
            new_path.parent.mkdir(parents=True, exist_ok=True)
            temp = old_path.with_name(f"{old_path.name}.apple-migrate")
            i = 1
            while temp.exists():
                temp = old_path.with_name(f"{old_path.name}.apple-migrate-{i}")
                i += 1
            try:
                old_path.rename(temp)
            except FileNotFoundError:
                continue
            staged.append((temp, new_path))
            self.move_map[old_rel] = rel_target

        for temp, new_path in staged:
            if not temp.exists():
                continue
            if new_path.exists() and temp.resolve() != new_path.resolve():
                stem = new_path.stem
                suffix = new_path.suffix
                parent = new_path.parent
                index = 1
                candidate = parent / f"{stem}-migrated-{index}{suffix}"
                while candidate.exists():
                    index += 1
                    candidate = parent / f"{stem}-migrated-{index}{suffix}"
                new_path = candidate
                self.renamed_notes += 1
            new_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                temp.rename(new_path)
            except FileNotFoundError:
                continue
            moved += 1
        return moved

    def _replace_managed_block(self, text: str, start: str, end: str, block: str) -> str:
        if start in text and end in text and text.index(start) < text.index(end):
            before = text[: text.index(start)]
            after = text[text.index(end) + len(end) :]
            return before.rstrip() + "\n\n" + block + "\n" + after.lstrip()
        return text.rstrip() + "\n\n" + block + "\n"

    def _update_links(self) -> None:
        if not self.move_map:
            return
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
                old_wiki = old_str[:-3]
                new_wiki = new_str[:-3]
                updated = updated.replace(f"[[{old_wiki}]]", f"[[{new_wiki}]]")
                updated = updated.replace(f"[[{old_wiki}|", f"[[{new_wiki}|")
            if updated != text:
                try:
                    note_path.write_text(updated, encoding="utf-8")
                except FileNotFoundError:
                    continue

    def _cleanup_customers_apple(self) -> None:
        folder = self.vault / "Customers" / "Apple"
        if not folder.exists() or not folder.is_dir():
            return

        markdown = sorted(folder.rglob("*.md"))
        if not markdown:
            try:
                folder.rmdir()
            except OSError:
                pass
            return

        for path in markdown:
            try:
                fm, body, text = self._read_markdown(path)
            except FileNotFoundError:
                continue

            lower = "\n".join([path.stem, body]).lower()
            source = str(fm.get("source") or "").lower()
            customer = str(fm.get("customer") or "").lower()
            has_apple_inc = bool(re.search(r"\bapple\s+inc\b", lower) or customer == "apple inc")

            # Keep folder only when it contains real Apple Inc customer notes.
            if has_apple_inc and source != "apple-notes-import":
                return

        for path in markdown:
            try:
                fm, body, text = self._read_markdown(path)
            except FileNotFoundError:
                continue
            note = _Note(
                path=path,
                rel=path.relative_to(self.vault),
                text=text,
                frontmatter=fm,
                body=body,
                title=self._guess_title(path, body, fm),
            )
            destination, _ = self._classify(note)
            if destination == Path("Customers") / "Apple":
                destination = Path("Reference")
            target_rel = self._ensure_unique_destination(destination / path.name, set(), set())
            target = self.vault / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.resolve() != target.resolve():
                path.rename(target)

        for d in sorted([p for p in folder.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                continue
        try:
            folder.rmdir()
        except OSError:
            pass

    def _render_note(self, frontmatter: Dict[str, object], body: str) -> str:
        lines = ["---"]
        ordered = [
            "title",
            "summary",
            "tags",
            "aliases",
            "source",
            "customer",
            "project",
            "meeting",
            "created",
            "modified",
            "original_filename",
            "original_path",
        ]

        def emit(key: str, value: object) -> None:
            if value is None or value == "":
                return
            if isinstance(value, list):
                if not value:
                    return
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {str(item)}")
                return
            lines.append(f"{key}: \"{str(value).replace(chr(34), chr(39))}\"")

        emitted = set()
        for key in ordered:
            if key in frontmatter:
                emit(key, frontmatter[key])
                emitted.add(key)
        for key, value in frontmatter.items():
            if key in emitted:
                continue
            emit(key, value)
        lines.append("---")
        return "\n".join(lines) + "\n\n" + body.strip() + "\n"

    def _summary(self, text: str, title: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        if not clean:
            return "No summary available."
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        head = " ".join(sentences[:2])[:280]
        if title and title.lower() not in head.lower() and len(title) < 80:
            return f"{title}: {head}"[:280]
        return head

    def _repair_metadata(self, notes: List[_Note], classification: Dict[Path, Dict[str, str]]) -> None:
        reverse_map = {new: old for old, new in self.move_map.items()}
        now = datetime.now(timezone.utc).isoformat()

        for note in notes:
            fm = dict(note.frontmatter)
            rel = note.rel
            old_rel = reverse_map.get(rel)
            cls = classification.get(note.path, {})

            fm["title"] = note.title
            fm["summary"] = self._summary(note.body, note.title)
            tags = set(str(t).lower() for t in (fm.get("tags") if isinstance(fm.get("tags"), list) else []))
            if rel.parts:
                tags.add(rel.parts[0].lower())
            if cls.get("customer"):
                tags.add(cls["customer"].lower().replace(" ", "-"))
            if cls.get("project"):
                tags.add("project")
            if cls.get("meeting"):
                tags.add("meeting")
            fm["tags"] = sorted(tags)

            aliases = set(str(a) for a in (fm.get("aliases") if isinstance(fm.get("aliases"), list) else []))
            aliases.add(note.title)
            aliases.add(note.path.stem.replace("-", " "))
            if old_rel:
                aliases.add(old_rel.stem.replace("-", " "))
                aliases.add(old_rel.as_posix()[:-3])
            fm["aliases"] = sorted(a for a in aliases if a)

            if old_rel and not fm.get("original_filename"):
                fm["original_filename"] = old_rel.name
            if old_rel and not fm.get("original_path"):
                fm["original_path"] = old_rel.as_posix()

            if not fm.get("source"):
                fm["source"] = "apple-notes-import"
            if cls.get("customer"):
                fm["customer"] = cls["customer"]
            if cls.get("project"):
                fm["project"] = cls["project"]
            if cls.get("meeting"):
                fm["meeting"] = cls["meeting"]
            if not fm.get("created"):
                fm["created"] = datetime.fromtimestamp(note.path.stat().st_mtime, tz=timezone.utc).isoformat()
            fm["modified"] = now

            rendered = self._render_note(fm, note.body)
            note.path.write_text(rendered, encoding="utf-8")

    def _extract_links(self, text: str) -> Set[str]:
        links: Set[str] = set()
        for match in re.findall(r"\[\[([^\]|#]+)", text):
            target = str(match).strip().replace(".md", "")
            if target:
                links.add(target)
        for match in re.findall(r"\]\(([^)]+)\)", text):
            target = str(match).strip().split("#", 1)[0].replace(".md", "")
            if target and "://" not in target and not target.startswith("mailto:"):
                links.add(target)
        return links

    def _create_indexes(self, notes: List[_Note]) -> None:
        buckets: Dict[str, List[Path]] = {name: [] for name in INDEX_PAGES.values()}
        for note in notes:
            if not note.rel.parts:
                continue
            head = note.rel.parts[0]
            index_name = INDEX_PAGES.get(head)
            if index_name:
                buckets[index_name].append(note.rel)

        for index_name, rels in buckets.items():
            index_path = self.vault / index_name
            if not index_path.exists():
                continue
            text = index_path.read_text(encoding="utf-8", errors="ignore")
            lines = ["<!-- JPLlama:index:start -->", "## Notes"]
            for rel in sorted(rels):
                lines.append(f"- [[{rel.as_posix()[:-3]}]]")
            lines.append("<!-- JPLlama:index:end -->")
            block = "\n".join(lines)
            updated = self._replace_managed_block(text, "<!-- JPLlama:index:start -->", "<!-- JPLlama:index:end -->", block)
            index_path.write_text(updated, encoding="utf-8")

    def _missing_files_count(self) -> int:
        missing = 0
        for rel in self.move_map.values():
            if not (self.vault / rel).exists():
                missing += 1
        return missing

    def _create_backlinks(self, notes: List[_Note]) -> Dict[str, int]:
        by_stub: Dict[str, Path] = {}
        link_counts = 0
        backlinks = 0

        for note in notes:
            by_stub[note.path.stem.lower()] = note.path
            by_stub[note.rel.as_posix()[:-3].lower()] = note.path

        incoming: Dict[Path, Set[str]] = defaultdict(set)
        for note in notes:
            links = self._extract_links(note.text)
            link_counts += len(links)
            for link in links:
                key = link.lower().lstrip("./")
                target = by_stub.get(key)
                if target and target != note.path:
                    incoming[target].add(note.rel.as_posix()[:-3])

        for note in notes:
            refs = sorted(incoming.get(note.path, set()))
            if not refs:
                continue
            backlinks += len(refs)
            block_lines = ["<!-- JPLlama:related:start -->", "## Related"]
            for ref in refs[:12]:
                block_lines.append(f"- [[{ref}]]")
            block_lines.append("<!-- JPLlama:related:end -->")
            block = "\n".join(block_lines)
            updated = self._replace_managed_block(note.text, "<!-- JPLlama:related:start -->", "<!-- JPLlama:related:end -->", block)
            if updated != note.text:
                note.path.write_text(updated, encoding="utf-8")

        return {"outgoing_links": link_counts, "backlinks": backlinks}

    def _collect_markdown_references(self) -> Set[str]:
        refs: Set[str] = set()
        for note in self._load_notes():
            parent = note.path.parent
            for raw in re.findall(r"!\[\[([^\]|#]+)", note.text):
                cleaned = str(raw).strip().split("#", 1)[0].split("?", 1)[0]
                if Path(cleaned).suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                refs.add(str((self.vault / cleaned).resolve()))
                refs.add(str((parent / cleaned).resolve()))
                refs.add(Path(cleaned).name.lower())
            for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)", note.text):
                cleaned = str(raw).strip().split("#", 1)[0].split("?", 1)[0]
                if Path(cleaned).suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                refs.add(str((self.vault / cleaned).resolve()))
                refs.add(str((parent / cleaned).resolve()))
                refs.add(Path(cleaned).name.lower())
        return refs

    def _iter_image_paths(self) -> Iterable[Path]:
        for root, dirnames, filenames in os.walk(self.vault):
            dirnames[:] = [d for d in dirnames if d.lower() not in {".obsidian", ".trash", ".git", "__pycache__", "organizerbackups"}]
            root_path = Path(root)
            for filename in filenames:
                path = root_path / filename
                if path.suffix.lower() in IMAGE_EXTENSIONS:
                    yield path

    def _archive_unused_images(self) -> int:
        refs = self._collect_markdown_references()
        archive_root = self.resource_archive_root / self.run_id
        archive_root.mkdir(parents=True, exist_ok=True)
        archived = 0
        for image in sorted(self._iter_image_paths()):
            rel = image.relative_to(self.vault)
            rel_parts = [p.lower() for p in rel.parts]
            if any(part in {"attachments", "resources", "resource"} for part in rel_parts):
                continue
            image_abs = str(image.resolve())
            image_name = image.name.lower()
            if image_abs in refs or image_name in refs:
                continue
            target = archive_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            candidate = target
            idx = 1
            while candidate.exists():
                candidate = target.with_name(f"{target.stem}-{idx}{target.suffix}")
                idx += 1
            image.rename(candidate)
            archived += 1
        return archived

    def _remove_empty_apple_notes_dirs(self) -> int:
        removed = 0
        root = self.vault / "Apple Notes"
        if not root.exists() or not root.is_dir():
            return 0

        all_dirs = sorted([p for p in root.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True)
        for d in all_dirs:
            try:
                d.rmdir()
                removed += 1
            except OSError:
                continue
        try:
            root.rmdir()
            removed += 1
        except OSError:
            pass
        return removed

    def _broken_link_count(self, notes: List[_Note]) -> int:
        available: Set[str] = set()
        for note in notes:
            available.add(note.path.stem.lower())
            available.add(note.rel.as_posix()[:-3].lower())

        broken = 0
        for note in notes:
            for raw in self._extract_links(note.text):
                key = raw.lower().lstrip("./")
                if key not in available:
                    broken += 1
        return broken

    def _search_validation(self, terms: List[str]) -> Dict[str, int]:
        client = ObsidianClient(ObsidianConfig(vault_path=self.vault))
        result: Dict[str, int] = {}
        for term in terms:
            hits = client.search(term, limit=5000)
            result[term] = len(hits)
        return result

    def run(self) -> AppleNotesMigrationResult:
        if not self.vault.exists():
            raise RuntimeError(f"Vault not found: {self.vault}")

        all_notes_before = self._load_notes()
        total_markdown_before = len(all_notes_before)
        original_apple_notes_count = sum(1 for n in all_notes_before if n.rel.parts and n.rel.parts[0].lower() == "apple notes")
        customers_apple_before = sum(
            1
            for n in all_notes_before
            if len(n.rel.parts) >= 2 and n.rel.parts[0].lower() == "customers" and n.rel.parts[1].lower() == "apple"
        )

        self._ensure_base_folders()

        candidates = [n for n in all_notes_before if self._is_candidate(n)]
        moving_sources: Set[Path] = {n.rel for n in candidates}
        planned: Dict[Path, Path] = {}
        reserved: Set[Path] = {n.rel for n in all_notes_before}
        classification_by_old_path: Dict[Path, Dict[str, str]] = {}

        for note in candidates:
            destination_folder, cls = self._classify(note)
            classification_by_old_path[note.path] = cls
            desired = destination_folder / note.path.name
            unique = self._ensure_unique_destination(desired, reserved, moving_sources)
            planned[note.path] = unique
            reserved.add(unique)

        migrated_notes = self._apply_moves(planned)
        self._update_links()

        if migrated_notes == 0 and not self.move_map:
            apple_notes_folders_removed = self._remove_empty_apple_notes_dirs()
            self._cleanup_customers_apple()
            final_notes = self._load_notes()
            total_markdown_after = len(final_notes)
            missing_files = self._missing_files_count()
            customers_apple_after = sum(
                1
                for n in final_notes
                if len(n.rel.parts) >= 2 and n.rel.parts[0].lower() == "customers" and n.rel.parts[1].lower() == "apple"
            )

            folder_counts = defaultdict(int)
            customer_subfolders = set()
            for note in final_notes:
                if not note.rel.parts:
                    continue
                top = note.rel.parts[0]
                folder_counts[top] += 1
                if top == "Customers" and len(note.rel.parts) >= 2:
                    customer_subfolders.add(note.rel.parts[1])

            broken_links = self._broken_link_count(final_notes)
            search_validation = self._search_validation(
                [
                    "password",
                    "OPSX",
                    "DP World",
                    "PayCargo",
                    "Kik",
                    "Bayer",
                    "Customer Implementation",
                    "Leadership",
                    "Data Custodian",
                ]
            )

            knowledge_graph = {
                "notes": len(final_notes),
                "outgoing_links": 0,
                "backlinks": 0,
                "customer_nodes": len(customer_subfolders),
                "broken_links": broken_links,
            }

            return AppleNotesMigrationResult(
                original_apple_notes_count=original_apple_notes_count,
                customers_apple_before=customers_apple_before,
                customers_apple_after=customers_apple_after,
                migrated_notes=0,
                notes_renamed=0,
                missing_files=missing_files,
                total_markdown_before=total_markdown_before,
                total_markdown_after=total_markdown_after,
                customers_created=len(customer_subfolders),
                projects_created=folder_counts.get("Projects", 0),
                meetings_created=folder_counts.get("Meetings", 0),
                personal_created=folder_counts.get("Personal", 0),
                reference_created=folder_counts.get("Reference", 0),
                apple_notes_folders_removed=apple_notes_folders_removed,
                images_archived=0,
                broken_links=broken_links,
                search_validation=search_validation,
                knowledge_graph=knowledge_graph,
            )

        all_notes_after_move = self._load_notes()

        classification_by_new_path: Dict[Path, Dict[str, str]] = {}
        for note in all_notes_after_move:
            old_rel = None
            for old, new in self.move_map.items():
                if new == note.rel:
                    old_rel = old
                    break
            if old_rel is None:
                classification_by_new_path[note.path] = self._classify(note)[1]
            else:
                old_abs = self.vault / old_rel
                classification_by_new_path[note.path] = classification_by_old_path.get(old_abs, self._classify(note)[1])

        self._repair_metadata(all_notes_after_move, classification_by_new_path)

        refreshed = self._load_notes()
        self._create_indexes(refreshed)
        link_stats = self._create_backlinks(refreshed)

        images_archived = self._archive_unused_images()
        apple_notes_folders_removed = self._remove_empty_apple_notes_dirs()
        self._cleanup_customers_apple()

        final_notes = self._load_notes()
        total_markdown_after = len(final_notes)
        missing_files = self._missing_files_count()
        customers_apple_after = sum(
            1
            for n in final_notes
            if len(n.rel.parts) >= 2 and n.rel.parts[0].lower() == "customers" and n.rel.parts[1].lower() == "apple"
        )

        folder_counts = defaultdict(int)
        customer_subfolders = set()
        for note in final_notes:
            if not note.rel.parts:
                continue
            top = note.rel.parts[0]
            folder_counts[top] += 1
            if top == "Customers" and len(note.rel.parts) >= 2:
                customer_subfolders.add(note.rel.parts[1])

        broken_links = self._broken_link_count(final_notes)
        search_validation = self._search_validation(
            [
                "password",
                "OPSX",
                "DP World",
                "PayCargo",
                "Kik",
                "Bayer",
                "Customer Implementation",
                "Leadership",
                "Data Custodian",
            ]
        )

        knowledge_graph = {
            "notes": len(final_notes),
            "outgoing_links": link_stats.get("outgoing_links", 0),
            "backlinks": link_stats.get("backlinks", 0),
            "customer_nodes": len(customer_subfolders),
            "broken_links": broken_links,
        }

        return AppleNotesMigrationResult(
            original_apple_notes_count=original_apple_notes_count,
            customers_apple_before=customers_apple_before,
            customers_apple_after=customers_apple_after,
            migrated_notes=migrated_notes,
            notes_renamed=self.renamed_notes,
            missing_files=missing_files,
            total_markdown_before=total_markdown_before,
            total_markdown_after=total_markdown_after,
            customers_created=len(customer_subfolders),
            projects_created=folder_counts.get("Projects", 0),
            meetings_created=folder_counts.get("Meetings", 0),
            personal_created=folder_counts.get("Personal", 0),
            reference_created=folder_counts.get("Reference", 0),
            apple_notes_folders_removed=apple_notes_folders_removed,
            images_archived=images_archived,
            broken_links=broken_links,
            search_validation=search_validation,
            knowledge_graph=knowledge_graph,
        )


def run_apple_notes_migration(vault_path: Path, *, resource_archive_root: Optional[Path] = None) -> AppleNotesMigrationResult:
    migrator = AppleNotesMigrator(vault_path=vault_path, resource_archive_root=resource_archive_root)
    return migrator.run()


def run_apple_notes_migration_engine(
    vault_path: Path,
    *,
    resource_archive_root: Optional[Path] = None,
    organizer_mode: str = "organize",
) -> AppleNotesMigrationEngineResult:
    from app.obsidian.organizer import run_obsidian_organizer

    migration = run_apple_notes_migration(vault_path=vault_path, resource_archive_root=resource_archive_root)
    organizer = run_obsidian_organizer(vault_path, mode=organizer_mode, resource_archive_root=resource_archive_root)

    return AppleNotesMigrationEngineResult(
        migration=migration,
        organizer_mode=organizer.mode,
        organizer_notes_moved=organizer.notes_moved,
        organizer_notes_renamed=organizer.notes_renamed,
        organizer_duplicates_found=organizer.duplicates_found,
        organizer_report_path=organizer.report_path,
    )
