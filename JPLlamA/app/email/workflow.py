from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from app.email.models import EmailMessage, EmailWorkflowResult
from app.email.parsers import EmailParser
from app.memory.store import search_memory_notes
from app.obsidian.client import ObsidianClient


logger = logging.getLogger(__name__)


class EmailWorkflow:
    def __init__(self, parser: Optional[EmailParser] = None):
        self.parser = parser or EmailParser()

    def process(
        self,
        payload: str,
        *,
        obsidian: ObsidianClient,
        memory_query_limit: int = 5,
        obsidian_query_limit: int = 5,
    ) -> EmailWorkflowResult:
        logger.info("EmailWorkflow: parsing email payload")
        message = self._parse_payload(payload)
        logger.info("EmailWorkflow: generating summary, entities, and actions")
        summary = self.parser.summarize(message)
        entities = self.parser.detect_entities(message)
        actions = self.parser.extract_actions(message)

        query = self._build_search_query(message, summary.keywords)
        logger.info("EmailWorkflow: searching Obsidian and memory with query='%s'", query)
        obsidian_hits = obsidian.search(query, limit=obsidian_query_limit)
        memory_hits = search_memory_notes(query, vault_path=obsidian.config.vault_path, limit=memory_query_limit)
        context = self._build_response_context(message, summary.summary, summary.keywords, entities, actions, obsidian_hits, memory_hits)
        logger.info(
            "EmailWorkflow: completed with %d Obsidian hits and %d memory hits",
            len(obsidian_hits),
            len(memory_hits),
        )

        return EmailWorkflowResult(
            message=message,
            summary=summary,
            tags=summary.keywords,
            entities=entities,
            actions=actions,
            obsidian_hits=obsidian_hits,
            memory_hits=memory_hits,
            response_context=context,
        )

    def _parse_payload(self, payload: str) -> EmailMessage:
        candidate = payload.strip()
        if not candidate:
            raise ValueError("Email payload is empty")

        path = Path(candidate).expanduser()
        if path.exists() and path.is_file():
            suffix = path.suffix.lower()
            if suffix == ".eml":
                return self.parser.parse_eml_file(path)
            if suffix == ".msg":
                return self.parser.parse_msg_file(path)
            text = path.read_text(encoding="utf-8", errors="ignore")
            return self.parser.parse_text_email(text)

        return self.parser.parse_text_email(candidate)

    def _build_search_query(self, message: EmailMessage, tags: List[str]) -> str:
        chunks = [message.subject, message.sender, " ".join(tags[:4])]
        text = " ".join([chunk for chunk in chunks if chunk]).strip()
        if text:
            return text
        body = message.body_text[:200]
        return body or "email"

    def _build_response_context(
        self,
        message: EmailMessage,
        summary: str,
        tags: List[str],
        entities,
        actions,
        obsidian_hits,
        memory_hits,
    ) -> str:
        lines: List[str] = []
        lines.append("Email workflow context")
        lines.append(f"Subject: {message.subject or 'No subject'}")
        lines.append(f"Sender: {message.sender or 'Unknown sender'}")
        lines.append(f"Summary: {summary or 'No summary available'}")
        lines.append(f"Tags: {', '.join(tags) if tags else 'none'}")
        lines.append("")

        lines.extend(self._entity_lines(entities))
        lines.extend(self._action_lines(actions))
        lines.append("")
        lines.append("Relevant Obsidian summaries:")
        lines.extend(self._summary_lines(obsidian_hits))
        lines.append("Relevant memory summaries:")
        lines.extend(self._summary_lines(memory_hits))
        return "\n".join(lines)

    def _entity_lines(self, entities) -> List[str]:
        return [
            f"Customers: {self._render_list(entities.customers)}",
            f"Projects: {self._render_list(entities.projects)}",
            f"Meetings: {self._render_list(entities.meetings)}",
            f"People: {self._render_list(entities.people)}",
            f"Email addresses: {self._render_list(entities.email_addresses)}",
            f"Organizations: {self._render_list(entities.organizations)}",
            (
                "People confidence: "
                + (
                    "; ".join([f"{name}={score:.2f}" for name, score in list(entities.people_confidence.items())[:4]])
                    if entities.people_confidence
                    else "none"
                )
            ),
            f"Detected action items: {self._render_list(entities.action_items)}",
            f"Detected deadlines: {self._render_list(entities.deadlines)}",
        ]

    def _action_lines(self, actions) -> List[str]:
        return [
            "Action extraction:",
            f"- To Do: {self._render_list(actions.todos)}",
            f"- Deadlines: {self._render_list(actions.deadlines)}",
            f"- Follow-ups: {self._render_list(actions.follow_ups)}",
            f"- Risks: {self._render_list(actions.risks)}",
            f"- Decisions: {self._render_list(actions.decisions)}",
        ]

    def _summary_lines(self, items: List[dict], limit: int = 5) -> List[str]:
        if not items:
            return ["- none"]
        lines: List[str] = []
        seen: set[Tuple[str, str]] = set()
        for item in items[:limit]:
            folder = str(item.get("folder") or "General")
            summary = str(item.get("summary") or item.get("snippet") or "").strip()
            if not summary:
                continue
            key = (folder.lower(), summary.lower())
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- [{folder}] {summary[:220]}")
        return lines or ["- none"]

    def _render_list(self, values: List[str], *, limit: int = 4) -> str:
        if not values:
            return "none"
        return "; ".join(values[:limit])
