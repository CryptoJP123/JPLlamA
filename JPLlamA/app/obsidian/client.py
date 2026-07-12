from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import logging
import math

from pathlib import Path

from typing import List, Dict, Any, Optional

import re


logger = logging.getLogger(__name__)

IGNORED_DIRS = {
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

@dataclass

class ObsidianConfig:

    vault_path: Path


class ObsidianClient:

    def __init__(self, config: ObsidianConfig):

        self.config = config
        self._file_cache: Dict[str, Dict[str, Any]] = {}

    def _tokenize(self, text: str) -> List[str]:
        return [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", text) if len(t) > 1]

    def _extract_frontmatter(self, text: str) -> Dict[str, Any]:
        if not text.startswith("---\n"):
            return {}

        end = text.find("\n---\n", 4)
        if end < 0:
            return {}

        block = text[4:end]
        frontmatter: Dict[str, Any] = {}
        tags: List[str] = []
        aliases: List[str] = []
        backlinks: List[str] = []
        related: List[str] = []
        current_list_key: Optional[str] = None
        for raw_line in block.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue

            if line.startswith("  - ") and current_list_key in {"tags", "aliases", "backlinks", "related", "out_links"}:
                item = line[4:].strip().strip('"').strip("'")
                if not item:
                    continue
                if current_list_key == "tags":
                    tags.append(item.lower())
                elif current_list_key == "aliases":
                    aliases.append(item)
                elif current_list_key == "backlinks":
                    backlinks.append(item)
                else:
                    related.append(item)
                continue

            current_list_key = None
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip().strip('"').strip("'")
            if key == "tags":
                current_list_key = "tags"
                if value:
                    tags.extend([v.strip().lower() for v in value.split(",") if v.strip()])
            elif key in {"aliases", "backlinks", "related", "out_links"}:
                current_list_key = key
                if value:
                    values = [v.strip() for v in value.split(",") if v.strip()]
                    if key == "aliases":
                        aliases.extend(values)
                    elif key == "backlinks":
                        backlinks.extend(values)
                    else:
                        related.extend(values)
            else:
                frontmatter[key] = value

        if tags:
            frontmatter["tags"] = sorted(set(tags))
        if aliases:
            frontmatter["aliases"] = sorted(set(aliases))
        if backlinks:
            frontmatter["backlinks"] = sorted(set(backlinks))
        if related:
            frontmatter["related"] = sorted(set(related))
        return frontmatter

    def _is_ignored_note_path(self, vault: Path, md_file: Path) -> bool:
        parts = {part.lower() for part in md_file.relative_to(vault).parts}
        return bool(parts.intersection(IGNORED_DIRS))

    def _parse_created_timestamp(self, frontmatter: Dict[str, Any], md_file: Path) -> datetime:
        created_raw = str(frontmatter.get("created") or "").strip()
        if created_raw:
            try:
                return datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)

    def _folder_weight(self, md_file: Path) -> float:
        folder = md_file.parent.name.lower()
        weights = {
            "projects": 1.2,
            "customers": 1.15,
            "meetings": 1.1,
            "ai": 1.1,
            "dpworld": 1.1,
            "reference": 1.0,
            "ideas": 1.0,
            "personal": 0.95,
            "hifi": 0.95,
        }
        return weights.get(folder, 1.0)

    def _recency_weight(self, created_at: datetime) -> float:
        now = datetime.now(tz=timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - created_at).total_seconds() / 86400)
        return max(0.6, 1.3 - min(0.7, age_days / 365.0))

    def _get_file_record(self, md_file: Path) -> Dict[str, Any]:
        key = str(md_file)
        try:
            stat = md_file.stat()
        except Exception:
            return {}

        cache_entry = self._file_cache.get(key)
        signature = (stat.st_mtime_ns, stat.st_size)
        if cache_entry and cache_entry.get("signature") == signature:
            return cache_entry

        try:
            text = md_file.read_text(errors="ignore")
        except Exception:
            return {}

        record = {
            "signature": signature,
            "text": text,
            "lower": text.lower(),
            "lines": text.splitlines(),
            "path": key,
            "basename": md_file.stem.lower(),
            "frontmatter": self._extract_frontmatter(text),
            "folder": md_file.parent.name,
        }
        record["title"] = str(record["frontmatter"].get("title") or md_file.stem.replace("-", " ").replace("_", " "))
        record["created_at"] = self._parse_created_timestamp(record["frontmatter"], md_file)
        self._file_cache[key] = record
        return record

    def _compute_score(self, query: str, terms: List[str], record: Dict[str, Any]) -> float:
        lower = record["lower"]
        basename = record["basename"]
        tags = [str(tag).lower() for tag in record.get("frontmatter", {}).get("tags", [])]
        aliases = [str(alias).lower() for alias in record.get("frontmatter", {}).get("aliases", [])]
        backlinks = [str(item).lower() for item in record.get("frontmatter", {}).get("backlinks", [])]
        related = [str(item).lower() for item in record.get("frontmatter", {}).get("related", [])]
        title = str(record.get("title") or "").lower()
        folder = str(record.get("folder") or "").lower()
        summary = str(record.get("frontmatter", {}).get("summary") or "")
        searchable_path = str(record.get("path") or "").lower()

        exact_hits = sum(lower.count(term) for term in terms)
        basename_hits = sum(basename.count(term) for term in terms)
        title_hits = sum(title.count(term) for term in terms)
        alias_hits = sum(alias.count(term) for alias in aliases for term in terms)
        folder_hits = sum(folder.count(term) for term in terms)
        backlink_hits = sum(item.count(term) for item in backlinks for term in terms)
        related_hits = sum(item.count(term) for item in related for term in terms)
        path_hits = sum(searchable_path.count(term) for term in terms)
        summary_hits = sum(summary.lower().count(term) for term in terms)
        tag_hits = sum(1 for term in terms if any(term in tag for tag in tags))
        fuzzy_name = SequenceMatcher(None, query.lower(), basename).ratio()

        preview_text = lower[:2400]
        fuzzy_text = SequenceMatcher(None, query.lower(), preview_text).ratio() if preview_text else 0.0
        exact_phrase = query.lower().strip() in lower if query.strip() else False

        if (
            exact_hits == 0
            and title_hits == 0
            and alias_hits == 0
            and tag_hits == 0
            and folder_hits == 0
            and backlink_hits == 0
            and related_hits == 0
            and path_hits == 0
            and fuzzy_name < 0.55
            and fuzzy_text < 0.38
        ):
            return 0.0

        term_density = exact_hits / max(1, len(lower.split()))
        base_score = (
            exact_hits * 10.0
            + basename_hits * 6.0
            + title_hits * 8.0
            + alias_hits * 6.0
            + summary_hits * 4.0
            + folder_hits * 2.0
            + backlink_hits * 3.0
            + related_hits * 3.0
            + path_hits * 3.0
            + tag_hits * 8.0
            + fuzzy_name * 10.0
            + fuzzy_text * 6.0
            + (6.0 if exact_phrase else 0.0)
            + min(5.0, term_density * 800.0)
        )
        return base_score * self._folder_weight(Path(record["path"])) * self._recency_weight(record["created_at"])

    def _build_snippet(self, terms: List[str], record: Dict[str, Any]) -> str:
        lines = record["lines"]
        if not lines:
            return ""

        best_index = 0
        best_score = -1.0
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            lower_line = stripped.lower()
            exact = sum(lower_line.count(term) for term in terms)
            fuzzy = max((SequenceMatcher(None, term, lower_line).ratio() for term in terms), default=0.0)
            score = exact * 2.0 + fuzzy
            if score > best_score:
                best_index = idx
                best_score = score

        start = max(0, best_index - 1)
        end = min(len(lines), best_index + 2)
        snippet_lines = [line.strip() for line in lines[start:end] if line.strip()]
        snippet = " / ".join(snippet_lines)
        return snippet[:500]

    def _build_summary(self, record: Dict[str, Any], snippet: str) -> str:
        frontmatter = record.get("frontmatter") or {}
        summary = str(frontmatter.get("summary") or "").strip()
        if summary:
            return summary[:220]
        return snippet[:220]

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:

        vault = self.config.vault_path.expanduser()

        if not vault.exists():

            logger.warning("Obsidian vault does not exist: %s", vault)

            return []

        terms = self._tokenize(query)

        if not terms:

            return []

        results: List[Dict[str, Any]] = []
        seen_paths = set()
        seen_snippets = set()

        for md_file in vault.rglob("*.md"):
            if self._is_ignored_note_path(vault, md_file):
                continue

            record = self._get_file_record(md_file)
            if not record:
                continue

            score = self._compute_score(query, terms, record)
            if score <= 0.0:

                continue

            snippet = self._build_snippet(terms, record)
            canonical_path = str(md_file.resolve())
            snippet_key = re.sub(r"\s+", " ", snippet.lower()).strip()

            if canonical_path in seen_paths:
                continue
            if snippet_key and snippet_key in seen_snippets:
                continue

            seen_paths.add(canonical_path)
            if snippet_key:
                seen_snippets.add(snippet_key)

            results.append(

                {

                    "path": str(md_file),

                    "score": int(math.floor(score)),

                    "snippet": snippet,

                    "summary": self._build_summary(record, snippet),

                    "tags": list(record.get("frontmatter", {}).get("tags", [])),

                    "aliases": list(record.get("frontmatter", {}).get("aliases", [])),

                    "backlinks": list(record.get("frontmatter", {}).get("backlinks", [])),

                    "related": list(record.get("frontmatter", {}).get("related", [])),

                    "title": str(record.get("title") or ""),

                    "folder": md_file.parent.name,

                }

            )

        results.sort(key=lambda item: (-item["score"], item["path"]))

        return results[:limit]