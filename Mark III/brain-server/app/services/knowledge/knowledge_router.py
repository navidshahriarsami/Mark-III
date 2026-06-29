"""
MARK III — Knowledge Router

Decides whether a query should consult the Obsidian vault.
Prevents unnecessary vault lookups for conversational queries.
"""
from __future__ import annotations

import re


_KNOWLEDGE_RE = re.compile(
    r"\b(architecture|roadmap|spec(ification)?|design|decision|"
    r"document(ation)?|phase|plan|requirement|meeting|note|"
    r"research|idea|concept|how (does|do|is|was) .+ (work|built|designed)|"
    r"what (is|was|are) (the|our|my) .+(architecture|design|plan|spec)|"
    r"tell me about|explain (the|our|my)|obsidian|vault|"
    r"mark.?iii|mark 3|brain server|pipeline|module|service|"
    r"phase \d+|pathwayau|project|funding|pitch)\b",
    re.I,
)

_SKIP_RE = re.compile(
    r"^(hi|hello|hey|thanks?|bye|yes|no|ok|how are you|"
    r"what time|weather|battery|cpu|ram|gpu|temperature)\b",
    re.I,
)


def should_query_vault(text: str) -> bool:
    """
    Return True if the query likely needs Obsidian knowledge.
    Skips purely conversational or live-data queries.
    """
    t = text.strip()
    if _SKIP_RE.match(t):
        return False
    return bool(_KNOWLEDGE_RE.search(t))
