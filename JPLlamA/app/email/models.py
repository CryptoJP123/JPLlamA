from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class EmailAttachment:
    filename: str
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    content_id: Optional[str] = None
    content_disposition: Optional[str] = None


@dataclass
class EmailMessage:
    message_id: str
    subject: str
    sender: str
    to: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    body_text: str = ""
    body_html: str = ""
    received_at: Optional[datetime] = None
    attachments: List[EmailAttachment] = field(default_factory=list)
    provider: str = "generic"
    provider_message_id: Optional[str] = None
    source_path: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class EmailSummary:
    message_id: str
    summary: str
    keywords: List[str] = field(default_factory=list)
    attachment_count: int = 0
    provider: str = "generic"


@dataclass
class EmailEntities:
    customers: List[str] = field(default_factory=list)
    projects: List[str] = field(default_factory=list)
    meetings: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    deadlines: List[str] = field(default_factory=list)
    people: List[str] = field(default_factory=list)
    email_addresses: List[str] = field(default_factory=list)
    organizations: List[str] = field(default_factory=list)
    people_confidence: Dict[str, float] = field(default_factory=dict)


@dataclass
class EmailActionExtraction:
    todos: List[str] = field(default_factory=list)
    deadlines: List[str] = field(default_factory=list)
    follow_ups: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)


@dataclass
class EmailWorkflowResult:
    message: EmailMessage
    summary: EmailSummary
    tags: List[str] = field(default_factory=list)
    entities: EmailEntities = field(default_factory=EmailEntities)
    actions: EmailActionExtraction = field(default_factory=EmailActionExtraction)
    obsidian_hits: List[Dict[str, Any]] = field(default_factory=list)
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)
    response_context: str = ""
