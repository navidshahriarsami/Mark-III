"""
MARK III Cognitive Council — Model Router

MARK III Principle: Routing requires zero external API calls.

Pure keyword/regex classification. <1ms. No LLM involved.

Pattern order: most specific first (URL before app, command before launch).
EXECUTIVE is always included — it produces the final answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .specialist_registry import SpecialistRole


@dataclass
class QueryAnalysis:
    roles:       list[SpecialistRole]
    complexity:  str                   # "low" | "medium" | "high"
    domain_tags: list[str]
    reasoning:   str


# ---------------------------------------------------------------------------
# Rules — ordered most-specific first
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Rule:
    pattern:    str
    roles:      tuple[SpecialistRole, ...]
    tags:       tuple[str, ...]
    complexity: str = "medium"


_RULES: list[_Rule] = [
    # Code / engineering
    _Rule(
        r"\b(code|debug|fix\s+bug|bug|error|exception|traceback|function|class|method|"
        r"api|endpoint|import|syntax|compile|runtime|refactor|algorithm|data\s*structure|"
        r"sql|query|script|implement|unit\s*test|test\s*case|dockerfile|ci.?cd|"
        r"git\s+(commit|push|pull|branch|merge)|deploy|variable|loop|array|dict|"
        r"async|await|promise|callback|lambda|regex|json|xml|http|rest|graphql)\b",
        (SpecialistRole.CODING, SpecialistRole.REASONING),
        ("coding", "engineering"),
        "high",
    ),

    # Deep reasoning / explanation
    _Rule(
        r"\b(why\s+(is|does|do|did|are|was)|how\s+does|explain\s+(how|why|the)|"
        r"mechanism|cause\s+of|reason\s+(for|why)|difference\s+between|"
        r"compare\s+(and\s+contrast)?|trade.?off|pros?\s+and\s+cons?|"
        r"evaluate|analys[ei]s?|analyz|logic\s+(behind)?|infer|deduce|"
        r"what\s+happens\s+when|break\s+this\s+down)\b",
        (SpecialistRole.REASONING,),
        ("reasoning", "analysis"),
        "medium",
    ),

    # Research / factual
    _Rule(
        r"\b(what\s+(is|are|was|were)|who\s+(is|was|are)|when\s+did|where\s+is|"
        r"history\s+of|facts?\s+about|research\s+(on|about)|"
        r"find\s+information|look\s+up|latest\s+(news|research|update)|"
        r"tell\s+me\s+about|overview\s+of|summary\s+of|statistics)\b",
        (SpecialistRole.RESEARCH,),
        ("research", "facts"),
        "medium",
    ),

    # Planning / strategy
    _Rule(
        r"\b(improve|enhancement|better|optimize|optimise|upgrade|evolve|"
        r"plan\s+(for|to|my|a)|create\s+a\s+(plan|roadmap)|roadmap|strategy\s+(for|to)|"
        r"timeline\s+(for)?|milestone|schedule\s+(for)?|"
        r"how\s+to\s+(achieve|accomplish|reach|build|create|start)|"
        r"break\s+(down|it\s+down)|action\s+items?|next\s+steps?|"
        r"priority|prioriti[sz]e|what\s+should\s+i\s+(do|focus|work))\b",
        (SpecialistRole.PLANNING,),
        ("planning", "strategy"),
        "medium",
    ),

    # Productivity / focus
    _Rule(
        r"\b(productivity|procrastinat|can.?t\s+focus|losing\s+focus|"
        r"distract(ed|ion)|habit\s+(of|for)|daily\s+routine|time\s+management|"
        r"deep\s+work|pomodoro|flow\s+state|overwhelm(ed)?|burnout|"
        r"motivat(ed|ion)|getting\s+things\s+done|work.?life)\b",
        (SpecialistRole.PRODUCTIVITY,),
        ("productivity", "focus"),
        "low",
    ),

    # Memory / profile / history
    _Rule(
        r"\b(remember\s+(when|that|my)|you\s+(know|mentioned|said)|"
        r"my\s+(goal|project|task|plan)|what\s+did\s+i\s+(say|tell|mention)|"
        r"last\s+time\s+(we|i)|based\s+on\s+my|my\s+progress|update\s+my|"
        r"track\s+(my|this))\b",
        (SpecialistRole.MEMORY,),
        ("memory", "context"),
        "low",
    ),

    # Pure conversation / social / emotional
    _Rule(
        r"^(hello|hi|hey|good\s+(morning|evening|afternoon|night))[.!,\s]|"
        r"\b(how\s+are\s+you|thanks|thank\s+you|you.?re\s+(welcome|great|amazing)|"
        r"i\s+feel|i.?m\s+(stressed|worried|anxious|happy|excited|sad|tired|frustrated)|"
        r"talk\s+to\s+me|just\s+checking\s+in|what.?s\s+up)\b",
        (SpecialistRole.CONVERSATION,),
        ("conversation", "social"),
        "low",
    ),
]

_COMPILED: list[tuple[re.Pattern, _Rule]] = [
    (re.compile(r.pattern, re.IGNORECASE), r)
    for r in _RULES
]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

async def classify_query(
    text:         str,
    context_hint: str = "",
    force_llm:    bool = False,   # kept for API compat, always ignored
) -> QueryAnalysis:
    """
    Classify a query into SpecialistRoles using local keyword rules only.
    No external API. No LLM. <1ms.

    force_llm is accepted but ignored — routing is always local.
    EXECUTIVE is always included.
    """
    matched_roles: list[SpecialistRole] = []
    matched_tags:  list[str]            = []
    complexity     = "low"

    for pattern, rule in _COMPILED:
        if pattern.search(text):
            for role in rule.roles:
                if role not in matched_roles:
                    matched_roles.append(role)
            for tag in rule.tags:
                if tag not in matched_tags:
                    matched_tags.append(tag)
            if rule.complexity == "high":
                complexity = "high"
            elif rule.complexity == "medium" and complexity == "low":
                complexity = "medium"

    # Multi-domain → high complexity
    if len(matched_roles) >= 2:
        complexity = "high"

    # Short conversational query with no domain → add CONVERSATION
    if not matched_roles and len(text.split()) < 15:
        matched_roles.append(SpecialistRole.CONVERSATION)
        matched_tags.append("conversation")

    # Build final list — EXECUTIVE always first
    final_roles = [SpecialistRole.EXECUTIVE]
    for r in matched_roles:
        if r not in final_roles:
            final_roles.append(r)

    reasoning = f"keyword:{','.join(matched_tags)}" if matched_tags else "no domain — conversational"

    return QueryAnalysis(
        roles       = final_roles,
        complexity  = complexity,
        domain_tags = matched_tags,
        reasoning   = reasoning,
    )
