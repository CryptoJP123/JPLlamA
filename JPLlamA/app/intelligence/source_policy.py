from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import List


@dataclass
class SourcePlan:
    mode: str
    use_knowledge: bool = False
    use_web: bool = False
    use_reference_sources: bool = False
    requested_knowledge_areas: List[str] = field(default_factory=list)
    requested_reference_sources: List[str] = field(default_factory=list)
    clean_prompt: str = ""
    reason: str = ""


_KNOWLEDGE_TRIGGERS = (
    "check the knowledge base",
    "use my knowledge base",
    "search the vault",
    "check obsidian",
    "use the rfq database",
    "look in the rfq contract review knowledge base",
    "use my stored rfqs",
    "compare with what i had for vw",
    "check what we stored about",
    "use the presentation knowledge base",
    "use remembered presentations",
    "use stored emails",
    "look in my previous reviews",
    "use the vw pattern",
    "use the bayer pattern",
    "check in my rfq database",
    "read from vault",
    "answer from vault",
    "what do we know about",
    "semantic search",
    "find notes",
)

_WEB_TRIGGERS = (
    "search the web",
    "look up online",
    "use the internet",
    "check online",
    "web search",
    "find current information online",
    "search searxng",
    "search internet",
)

_REFERENCE_TRIGGERS = (
    "check the dp world freight forwarding documentation centre",
    "use the dp world terms and conditions page",
    "consult the freight forwarding document centre",
    "use the registered reference sources",
    "check our t&c reference page",
    "use the dp world documentation centre",
    "use the freight forwarding terms",
    "use dp world standard trading conditions",
)

_KNOWLEDGE_REGEX = (
    r"\bknowledge base\b",
    r"\brfq database\b",
    r"\brfq contract review knowledge base\b",
    r"\bstored rfq[s]?\b",
    r"\buse .*pattern\b",
)

_REFERENCE_REGEX = (
    r"\bdp world\b.*\bdocumentation centre\b",
    r"\bfreight forwarding\b.*\bterms\b",
    r"\bregistered reference sources\b",
)

_REMEMBER_PREFIXES = (
    "remember ",
    "store ",
    "save ",
)

_SYSTEM_PREFIXES = (
    "help",
    "version",
    "health",
    "settings",
    "configuration",
    "backup ",
    "export ",
    "organize ",
    "reorganize ",
    "migrate apple notes",
)

_WEATHER_LIVE_HINTS = (
    "weather",
    "forecast",
    "temperature",
    "rain",
    "snow",
    "wind",
)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _contains_regex(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _extract_knowledge_areas(text: str) -> List[str]:
    areas: List[str] = []
    for token in ("rfq", "vw", "bayer", "presentation", "email", "obsidian", "vault"):
        if re.search(rf"\b{re.escape(token)}\b", text):
            areas.append(token)
    return areas


def _extract_reference_sources(text: str) -> List[str]:
    sources: List[str] = []
    if "dp world" in text or "documentation centre" in text or "terms and conditions" in text:
        sources.append("DP World Freight Forwarding Documentation Centre")
    return sources


def requires_live_web_data(prompt: str) -> bool:
    lowered = prompt.strip().lower()
    return any(term in lowered for term in _WEATHER_LIVE_HINTS)


def plan_source_usage(prompt: str) -> SourcePlan:
    lowered = prompt.strip().lower()
    if not lowered:
        return SourcePlan(mode="direct", clean_prompt=prompt, reason="Empty prompt defaults to direct mode.")

    if lowered.startswith(_REMEMBER_PREFIXES):
        return SourcePlan(mode="remember", clean_prompt=prompt, reason="Remember/store command detected.")

    if lowered.startswith(_SYSTEM_PREFIXES) or lowered in _SYSTEM_PREFIXES:
        return SourcePlan(mode="system", clean_prompt=prompt, reason="System command detected.")

    use_knowledge = _contains_any(lowered, _KNOWLEDGE_TRIGGERS) or _contains_regex(lowered, _KNOWLEDGE_REGEX)
    use_web = _contains_any(lowered, _WEB_TRIGGERS)
    use_reference = _contains_any(lowered, _REFERENCE_TRIGGERS) or _contains_regex(lowered, _REFERENCE_REGEX)

    if use_knowledge and use_web and use_reference:
        mode = "mixed"
        reason = "Explicit knowledge, web, and reference instructions detected."
    elif sum((use_knowledge, use_web, use_reference)) > 1:
        mode = "mixed"
        reason = "Multiple explicit source instructions detected."
    elif use_knowledge:
        mode = "knowledge"
        reason = "Explicit knowledge/vault request detected."
    elif use_web:
        mode = "web"
        reason = "Explicit internet/web request detected."
    elif use_reference:
        mode = "reference"
        reason = "Explicit registered reference-source request detected."
    else:
        mode = "direct"
        reason = "No explicit vault/web/reference request; default direct mode."

    return SourcePlan(
        mode=mode,
        use_knowledge=use_knowledge,
        use_web=use_web,
        use_reference_sources=use_reference,
        requested_knowledge_areas=_extract_knowledge_areas(lowered),
        requested_reference_sources=_extract_reference_sources(lowered),
        clean_prompt=prompt.strip(),
        reason=reason,
    )
