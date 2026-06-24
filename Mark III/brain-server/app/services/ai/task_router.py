"""
MARK III — Task Router & Intent Classifier

MARK III decides whether an LLM is necessary.

LOCAL tasks (handled by rule engine, no LLM call):
  - Focus score calculation
  - Context derivation
  - Window classification
  - Breach detection
  - Simple reminders & time checks
  - Notification dispatch

FAST tasks (light LLM call — Haiku / gpt-4o-mini):
  - Daily productivity summary
  - Short-form advice
  - Quick answers to direct questions
  - App/task suggestions

DEEP tasks (high-quality LLM call — Sonnet / gpt-4o):
  - Weekly review with trend analysis
  - Career guidance
  - Goal progress review
  - Strategic priorities
  - Complex questions requiring full context

Routing is keyword-based + task-type enumeration.
No LLM is used for classification — pure Python logic.
"""

from __future__ import annotations

from enum import Enum
from .base_provider import TaskTier


class TaskType(str, Enum):
    # LOCAL — rule-engine handled
    FOCUS_SCORE        = "focus_score"
    CONTEXT_DERIVE     = "context_derive"
    RECOMMENDATION     = "recommendation"
    BREACH_CHECK       = "breach_check"
    SIMPLE_REMINDER    = "simple_reminder"
    NOTIFICATION       = "notification"

    # FAST — quick LLM
    DAILY_BRIEF        = "daily_brief"
    QUICK_ANSWER       = "quick_answer"
    TASK_SUGGESTION    = "task_suggestion"
    EVENING_REVIEW     = "evening_review"

    # DEEP — quality LLM
    WEEKLY_REVIEW      = "weekly_review"
    CAREER_ADVICE      = "career_advice"
    GOAL_REVIEW        = "goal_review"
    STRATEGIC_PLAN     = "strategic_plan"
    INSIGHT_SYNTHESIS  = "insight_synthesis"
    FREE_FORM_QUERY    = "free_form_query"


# Maps TaskType → TaskTier
_TIER_MAP: dict[TaskType, TaskTier] = {
    TaskType.FOCUS_SCORE:       TaskTier.LOCAL,
    TaskType.CONTEXT_DERIVE:    TaskTier.LOCAL,
    TaskType.RECOMMENDATION:    TaskTier.LOCAL,
    TaskType.BREACH_CHECK:      TaskTier.LOCAL,
    TaskType.SIMPLE_REMINDER:   TaskTier.LOCAL,
    TaskType.NOTIFICATION:      TaskTier.LOCAL,

    TaskType.DAILY_BRIEF:       TaskTier.FAST,
    TaskType.QUICK_ANSWER:      TaskTier.FAST,
    TaskType.TASK_SUGGESTION:   TaskTier.FAST,
    TaskType.EVENING_REVIEW:    TaskTier.FAST,

    TaskType.WEEKLY_REVIEW:     TaskTier.DEEP,
    TaskType.CAREER_ADVICE:     TaskTier.DEEP,
    TaskType.GOAL_REVIEW:       TaskTier.DEEP,
    TaskType.STRATEGIC_PLAN:    TaskTier.DEEP,
    TaskType.INSIGHT_SYNTHESIS: TaskTier.DEEP,
    TaskType.FREE_FORM_QUERY:   TaskTier.DEEP,
}

# Max tokens budget per tier
_TOKEN_BUDGET: dict[TaskTier, int] = {
    TaskTier.LOCAL: 0,
    TaskTier.FAST:  512,
    TaskTier.DEEP:  2048,
}

# Temperature per tier
_TEMPERATURE: dict[TaskTier, float] = {
    TaskTier.LOCAL: 0.0,
    TaskTier.FAST:  0.5,
    TaskTier.DEEP:  0.3,
}

# ---------------------------------------------------------------------------
# Keyword-based intent classifier for free-form /ask queries
# ---------------------------------------------------------------------------

_DEEP_KEYWORDS = {
    "career", "job", "interview", "resume", "cv", "salary",
    "goal", "goals", "milestone", "target", "vision",
    "week", "weekly", "month", "quarter", "strategy",
    "advice", "guidance", "review", "analyse", "analyze",
    "priority", "priorities", "plan", "roadmap",
    "should i", "what should", "help me decide",
}

_FAST_KEYWORDS = {
    "today", "summary", "summarise", "summarize", "brief",
    "remind", "reminder", "suggest", "tip", "idea",
    "focus", "distracted", "productivity",
}

_LOCAL_PATTERNS = {
    "what time", "what is the time", "how long", "current score",
    "focus score", "my score", "am i productive",
}


def classify_intent(user_text: str) -> TaskType:
    """
    Classify a free-form user query into a TaskType.
    Pure rule-based — no LLM call.
    """
    lower = user_text.lower().strip()

    for pat in _LOCAL_PATTERNS:
        if pat in lower:
            return TaskType.SIMPLE_REMINDER

    words = set(lower.split())
    if words & _DEEP_KEYWORDS:
        return TaskType.FREE_FORM_QUERY

    if words & _FAST_KEYWORDS:
        return TaskType.QUICK_ANSWER

    # Default for unknown queries — use DEEP for quality
    return TaskType.FREE_FORM_QUERY


def route(task_type: TaskType) -> tuple[TaskTier, int, float]:
    """
    Return (tier, max_tokens, temperature) for a task.
    Used by the reasoning engine to build the GenerateRequest.
    """
    tier   = _TIER_MAP.get(task_type, TaskTier.FAST)
    tokens = _TOKEN_BUDGET.get(tier, 512)
    temp   = _TEMPERATURE.get(tier, 0.4)
    return tier, tokens, temp


def needs_llm(task_type: TaskType) -> bool:
    """True if this task requires an LLM call."""
    return _TIER_MAP.get(task_type, TaskTier.FAST) != TaskTier.LOCAL
