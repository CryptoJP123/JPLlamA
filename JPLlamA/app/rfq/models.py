from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RfqDocumentSummary:
    name: str
    source: str
    file_type: str
    size_bytes: int = 0
    structure: List[str] = field(default_factory=list)
    text_excerpt: str = ""
    total_chunks: int = 0
    chunks_processed: int = 0
    status: str = "pending"
    error: Optional[str] = None


@dataclass
class RfqFinding:
    bucket: str
    category: str
    severity: str
    finding: str
    evidence: str
    source: str
    sign_off: str = ""
    outside_baseline: bool = False


@dataclass
class RfqReviewResult:
    transport_mode: str
    documents: List[RfqDocumentSummary] = field(default_factory=list)
    table1: List[RfqFinding] = field(default_factory=list)
    table2: List[RfqFinding] = field(default_factory=list)
    table3: List[RfqFinding] = field(default_factory=list)
    approvals_required: List[str] = field(default_factory=list)
    partial_review: bool = False
    pending_items: List[str] = field(default_factory=list)
    compact_context: str = ""
    markdown_report: str = ""
    markdown_path: str = ""
    docx_path: str = ""
    obsidian_note_path: str = ""
    recommendation: str = ""
    recommendation_reason: str = ""
