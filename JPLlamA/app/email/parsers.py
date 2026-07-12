from __future__ import annotations

from datetime import datetime
from email import policy
from email.utils import parsedate_to_datetime
from email.parser import BytesParser
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .models import EmailActionExtraction, EmailAttachment, EmailEntities, EmailMessage, EmailSummary


class EmailParser:
    """Parser layer that accepts generic dict payloads from future providers like Outlook."""

    def parse_eml_file(self, file_path: Union[str, Path]) -> EmailMessage:
        path = Path(file_path)
        raw = path.read_bytes()
        message = self.parse_eml_bytes(raw)
        message.source_path = str(path)
        return message

    def parse_msg_file(self, file_path: Union[str, Path]) -> EmailMessage:
        path = Path(file_path)
        try:
            import extract_msg  # type: ignore
        except ImportError as exc:
            raise ValueError(
                "MSG parsing requires optional dependency extract-msg. Install with: pip install extract-msg"
            ) from exc

        msg = extract_msg.Message(str(path))
        to_list = self._to_list(msg.to)
        cc_list = self._to_list(msg.cc)
        body = str(msg.body or "")
        attachments: List[EmailAttachment] = []
        for item in getattr(msg, "attachments", []) or []:
            data = getattr(item, "data", b"") or b""
            attachments.append(
                EmailAttachment(
                    filename=str(getattr(item, "longFilename", None) or getattr(item, "shortFilename", None) or "attachment.bin"),
                    content_type="application/octet-stream",
                    size_bytes=len(data),
                )
            )

        sent_at = self._parse_datetime(getattr(msg, "date", None))
        return EmailMessage(
            message_id=str(getattr(msg, "messageId", "") or ""),
            subject=str(getattr(msg, "subject", "") or ""),
            sender=str(getattr(msg, "sender", "") or ""),
            to=to_list,
            cc=cc_list,
            body_text=body,
            body_html="",
            received_at=sent_at,
            attachments=attachments,
            provider="msg",
            provider_message_id=str(getattr(msg, "messageId", "") or "") or None,
            source_path=str(path),
            metadata={},
        )

    def parse_text_email(self, text: str) -> EmailMessage:
        normalized_text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
        lines = [line.rstrip() for line in normalized_text.splitlines()]
        headers: Dict[str, str] = {}
        body_start = 0
        for idx, line in enumerate(lines):
            if not line.strip():
                body_start = idx + 1
                break
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            lower_key = key.strip().lower()
            if lower_key in {"from", "to", "cc", "subject", "date", "message-id"}:
                headers[lower_key] = value.strip()

        body_text = "\n".join(lines[body_start:]).strip() if lines else normalized_text.strip()
        if not body_text:
            body_text = normalized_text.strip()

        return EmailMessage(
            message_id=headers.get("message-id", ""),
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            to=self._to_list(headers.get("to")),
            cc=self._to_list(headers.get("cc")),
            body_text=body_text,
            received_at=self._parse_datetime(headers.get("date")),
            provider="text",
            metadata={},
        )

    def parse_eml_bytes(self, raw_bytes: bytes) -> EmailMessage:
        parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)

        subject = str(parsed.get("subject") or "")
        sender = str(parsed.get("from") or "")
        to_list = self._to_list(parsed.get("to"))
        cc_list = self._to_list(parsed.get("cc"))
        message_id = str(parsed.get("message-id") or "")
        received_at = self._parse_datetime(parsed.get("date"))

        body_text = ""
        body_html = ""
        attachments: List[EmailAttachment] = []

        if parsed.is_multipart():
            for part in parsed.walk():
                content_disposition = str(part.get("Content-Disposition") or "")
                content_type = str(part.get_content_type() or "application/octet-stream")
                filename = part.get_filename()

                if filename:
                    payload = part.get_payload(decode=True) or b""
                    attachments.append(
                        EmailAttachment(
                            filename=str(filename),
                            content_type=content_type,
                            size_bytes=len(payload),
                            content_id=str(part.get("Content-ID") or "").strip("<>") or None,
                            content_disposition=content_disposition or None,
                        )
                    )
                    continue

                if content_type == "text/plain" and not body_text:
                    body_text = self._safe_part_text(part)
                elif content_type == "text/html" and not body_html:
                    body_html = self._safe_part_text(part)
        else:
            content_type = str(parsed.get_content_type() or "")
            if content_type == "text/html":
                body_html = self._safe_part_text(parsed)
            else:
                body_text = self._safe_part_text(parsed)

        return EmailMessage(
            message_id=message_id,
            subject=subject,
            sender=sender,
            to=to_list,
            cc=cc_list,
            body_text=body_text,
            body_html=body_html,
            received_at=received_at,
            attachments=attachments,
            provider="eml",
            provider_message_id=message_id or None,
            metadata={
                "x_outlook_message_id": str(parsed.get("x-ms-exchange-organization-network-message-id") or ""),
                "x_outlook_conversation_id": str(parsed.get("thread-index") or ""),
            },
        )

    def parse_attachment(self, payload: Mapping[str, Any]) -> EmailAttachment:
        filename = str(payload.get("filename") or payload.get("name") or "attachment.bin")
        content_type = str(payload.get("content_type") or payload.get("mimeType") or "application/octet-stream")
        size_bytes = int(payload.get("size_bytes") or payload.get("size") or 0)
        content_id = payload.get("content_id") or payload.get("contentId")
        disposition = payload.get("content_disposition") or payload.get("contentDisposition")
        return EmailAttachment(
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            content_id=str(content_id) if content_id else None,
            content_disposition=str(disposition) if disposition else None,
        )

    def parse_message(self, payload: Mapping[str, Any]) -> EmailMessage:
        attachments_raw = payload.get("attachments") or []
        attachments = [
            self.parse_attachment(item)
            for item in attachments_raw
            if isinstance(item, Mapping)
        ]

        return EmailMessage(
            message_id=str(payload.get("message_id") or payload.get("id") or ""),
            subject=str(payload.get("subject") or ""),
            sender=str(payload.get("sender") or payload.get("from") or ""),
            to=self._to_list(payload.get("to")),
            cc=self._to_list(payload.get("cc")),
            bcc=self._to_list(payload.get("bcc")),
            body_text=str(payload.get("body_text") or payload.get("text") or ""),
            body_html=str(payload.get("body_html") or payload.get("html") or ""),
            received_at=self._parse_datetime(payload.get("received_at") or payload.get("receivedDateTime")),
            attachments=attachments,
            provider=str(payload.get("provider") or "generic"),
            provider_message_id=str(payload.get("provider_message_id") or payload.get("internetMessageId") or "") or None,
            source_path=str(payload.get("source_path") or "") or None,
            metadata={
                "outlook_conversation_id": str(payload.get("conversationId") or ""),
                "outlook_change_key": str(payload.get("changeKey") or ""),
            },
        )

    def summarize(self, message: EmailMessage) -> EmailSummary:
        source = message.body_text or self._strip_html(message.body_html)
        normalized = re.sub(r"\s+", " ", source).strip()
        summary = normalized[:240]

        keywords = self._extract_keywords(f"{message.subject} {normalized}")
        return EmailSummary(
            message_id=message.message_id,
            summary=summary,
            keywords=keywords,
            attachment_count=len(message.attachments),
            provider=message.provider,
        )

    def detect_entities(self, message: EmailMessage) -> EmailEntities:
        source = " ".join(
            [
                message.subject,
                message.sender,
                " ".join(message.to),
                " ".join(message.cc),
                message.body_text or self._strip_html(message.body_html),
            ]
        )
        normalized = re.sub(r"\s+", " ", source)
        customers = self._extract_after_keywords(normalized, ["customer", "client", "account"])
        projects = self._extract_after_keywords(normalized, ["project", "program", "initiative"])
        meetings = self._extract_lines_by_keywords(normalized, ["meeting", "call", "sync", "workshop"])
        action_items = self._extract_lines_by_keywords(normalized, ["please", "action", "need to", "todo", "to do"])
        deadlines = self._extract_deadlines(normalized)
        people = self._extract_people_candidates(normalized)
        emails = self._extract_email_addresses(normalized)
        organizations = self._extract_organizations(normalized)
        people_confidence = {person: self._person_confidence(person, normalized) for person in people}
        return EmailEntities(
            customers=customers,
            projects=projects,
            meetings=meetings,
            action_items=action_items,
            deadlines=deadlines,
            people=people,
            email_addresses=emails,
            organizations=organizations,
            people_confidence=people_confidence,
        )

    def extract_actions(self, message: EmailMessage) -> EmailActionExtraction:
        text = message.body_text or self._strip_html(message.body_html)
        lines = [line.strip() for line in re.split(r"[\n\r]+", text) if line.strip()]
        todos = self._pick_action_lines(lines, ["todo", "to do", "please", "need to", "action"])
        follow_ups = self._pick_action_lines(lines, ["follow up", "follow-up", "circle back", "check back"])
        risks = self._pick_action_lines(lines, ["risk", "issue", "blocker", "delay", "concern"])
        decisions = self._pick_action_lines(lines, ["decide", "decision", "approved", "agreed", "selected"])
        deadlines = self._extract_deadlines(text)
        return EmailActionExtraction(
            todos=todos,
            deadlines=deadlines,
            follow_ups=follow_ups,
            risks=risks,
            decisions=decisions,
        )

    def _safe_part_text(self, part: Any) -> str:
        payload = part.get_payload(decode=True)
        if payload is None:
            raw = part.get_payload()
            return str(raw or "")

        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="ignore")
        except LookupError:
            return payload.decode("utf-8", errors="ignore")

    def _to_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if str(v).strip()]
        if isinstance(value, str):
            chunks = [item.strip() for item in value.split(",")]
            return [item for item in chunks if item]
        return [str(value)]

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass

        try:
            return parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None

    def _strip_html(self, html: str) -> str:
        if not html:
            return ""
        return re.sub(r"<[^>]+>", " ", html)

    def _extract_keywords(self, text: str) -> List[str]:
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9_]+", text)]
        stop_words = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "for",
            "from",
            "in",
            "is",
            "it",
            "of",
            "on",
            "or",
            "that",
            "the",
            "to",
            "with",
        }
        counts: Dict[str, int] = {}
        for word in words:
            if len(word) < 3 or word in stop_words:
                continue
            counts[word] = counts.get(word, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [word for word, _ in ranked[:5]]

    def _extract_after_keywords(self, text: str, keywords: Sequence[str]) -> List[str]:
        found: List[str] = []
        patterns = [rf"(?:{'|'.join(map(re.escape, keywords))})\s*[:\-]\s*([^.;\n]+)" for _ in [0]]
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                raw = match.group(1).strip()
                if not raw:
                    continue
                candidate = raw.split(",")[0].strip()
                if candidate and candidate not in found:
                    found.append(candidate[:120])
        return found[:5]

    def _extract_lines_by_keywords(self, text: str, keywords: Sequence[str]) -> List[str]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        results: List[str] = []
        for sentence in sentences:
            lower = sentence.lower()
            if any(keyword in lower for keyword in keywords):
                snippet = sentence[:160]
                if snippet not in results:
                    results.append(snippet)
        return results[:5]

    def _extract_deadlines(self, text: str) -> List[str]:
        patterns = [
            r"\b(?:by|before|due|deadline)\s+([A-Za-z]{3,9}\s+\d{1,2}(?:,\s*\d{4})?)",
            r"\b(?:by|before|due|deadline)\s+(\d{4}-\d{2}-\d{2})",
            r"\b(?:by|before|due|deadline)\s+(\d{1,2}/\d{1,2}/\d{2,4})",
        ]
        deadlines: List[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                value = match.group(1).strip()
                normalized = self._normalize_deadline(value)
                if normalized and normalized not in deadlines:
                    deadlines.append(normalized)
        return deadlines[:5]

    def _extract_people_candidates(self, text: str) -> List[str]:
        people: List[str] = []
        for match in re.finditer(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b", text):
            candidate = match.group(1)
            if candidate not in people:
                people.append(candidate)
        return people[:6]

    def _extract_email_addresses(self, text: str) -> List[str]:
        results: List[str] = []
        for match in re.finditer(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text):
            email = match.group(0).lower()
            if email not in results:
                results.append(email)
        return results[:10]

    def _extract_organizations(self, text: str) -> List[str]:
        organizations: List[str] = []
        patterns = [
            r"\b([A-Z][A-Za-z0-9&.,'\-]+\s+(?:Inc|LLC|Ltd|Corporation|Corp|Group|Company|Co))\b",
            r"\b(?:customer|client|account)\s*[:\-]\s*([A-Z][A-Za-z0-9&.,'\- ]{2,})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                org = re.sub(r"\s+", " ", match.group(1)).strip(" .,")
                if org and org not in organizations:
                    organizations.append(org)
        return organizations[:6]

    def _person_confidence(self, person: str, text: str) -> float:
        score = 0.55
        if re.search(rf"\b{re.escape(person)}\b", text):
            score += 0.15
        if re.search(rf"\b(?:cc|to|from)\s*:\s*[^\n]*{re.escape(person)}", text, flags=re.IGNORECASE):
            score += 0.2
        return min(0.99, round(score, 2))

    def _normalize_deadline(self, value: str) -> str:
        raw = value.strip()
        if not raw:
            return ""

        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%B %d", "%b %d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                if fmt in {"%B %d", "%b %d"}:
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed.date().isoformat()
            except ValueError:
                continue
        return raw

    def _pick_action_lines(self, lines: List[str], keywords: Sequence[str]) -> List[str]:
        picks: List[str] = []
        for line in lines:
            lower = line.lower()
            if any(keyword in lower for keyword in keywords):
                snippet = line[:180]
                if snippet not in picks:
                    picks.append(snippet)
        return picks[:6]
