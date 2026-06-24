"""
MARK III Cognitive Engine — Recommendation Engine

Generates prioritised action suggestions from:
  - Current productivity state
  - Work-block status
  - Today's accumulated distraction / productive minutes

Returns at most 5 recommendations, sorted by priority descending.
"""

from dataclasses import dataclass
from .context_engine import ProductivityState


@dataclass
class RecommendationItem:
    text:          str
    category:      str    # focus | break | career | health | admin
    priority:      int    # 0 = low  1 = medium  2 = high
    context_state: str


# (state, is_work_block, category, priority, text)
_RULES: list[tuple] = [
    # ── Distraction ──────────────────────────────────────────────────────────
    (ProductivityState.DISTRACTION, True,
     "focus", 2,
     "You're off-track during a work block. Close the tab and reopen your last project."),

    (ProductivityState.DISTRACTION, False,
     "focus", 0,
     "Distraction detected outside work hours. Stay aware of how long this runs."),

    # ── Entertainment ─────────────────────────────────────────────────────────
    (ProductivityState.ENTERTAINMENT, True,
     "focus", 2,
     "Entertainment during a work block. Return to a work task now."),

    (ProductivityState.ENTERTAINMENT, False,
     "health", 0,
     "Entertainment mode. Set a timer so it does not run over."),

    # ── Software development ──────────────────────────────────────────────────
    (ProductivityState.SOFTWARE_DEVELOPMENT, True,
     "focus", 0,
     "Deep work in progress. Protect this session — silence notifications."),

    (ProductivityState.SOFTWARE_DEVELOPMENT, False,
     "focus", 0,
     "Coding outside work hours. Make sure you rest before tomorrow."),

    # ── Communication ─────────────────────────────────────────────────────────
    (ProductivityState.COMMUNICATION, True,
     "focus", 1,
     "High communication load. Batch your messages and return to focused work."),

    # ── Idle during work block ────────────────────────────────────────────────
    (ProductivityState.IDLE, True,
     "focus", 1,
     "Work block active but no activity detected. What is the plan for today?"),

    # ── Break during work block ───────────────────────────────────────────────
    (ProductivityState.BREAK, True,
     "focus", 1,
     "Break during a work block. Your schedule is waiting."),

    # ── Career development ────────────────────────────────────────────────────
    (ProductivityState.CAREER_DEVELOPMENT, True,
     "career", 0,
     "Job search in progress. Set a 45-minute timer so it does not overrun your work block."),

    (ProductivityState.CAREER_DEVELOPMENT, False,
     "career", 0,
     "Job search active. Keep a list of applications so nothing slips through."),

    # ── Administrative ────────────────────────────────────────────────────────
    (ProductivityState.ADMINISTRATIVE, True,
     "admin", 0,
     "Admin tasks detected. Finish quickly and return to your primary goal."),

    # ── Research ─────────────────────────────────────────────────────────────
    (ProductivityState.RESEARCH, True,
     "focus", 0,
     "Research session active. Write down key findings as you go."),

    # ── Unknown ──────────────────────────────────────────────────────────────
    (ProductivityState.UNKNOWN, True,
     "focus", 1,
     "Activity is unclear. Open a concrete work task to get started."),
]


def generate_recommendations(
    state:                     ProductivityState,
    is_work_block:             bool,
    distraction_minutes_today: float,
    productive_minutes_today:  float,
    goals:                     list | None = None,
    projects:                  list | None = None,
) -> list[RecommendationItem]:

    results: list[RecommendationItem] = []

    for rule_state, rule_wb, cat, pri, text in _RULES:
        if rule_state == state and rule_wb == is_work_block:
            results.append(RecommendationItem(
                text          = text,
                category      = cat,
                priority      = pri,
                context_state = state.value,
            ))

    # ── Data-driven extras ────────────────────────────────────────────────────
    if distraction_minutes_today > 60:
        results.append(RecommendationItem(
            text          = f"You have spent {int(distraction_minutes_today)}m distracted today. Try a 25-minute Pomodoro block next.",
            category      = "focus",
            priority      = 2,
            context_state = state.value,
        ))

    if productive_minutes_today > 180 and is_work_block:
        results.append(RecommendationItem(
            text          = "Three or more hours of productive work today. A 15-minute break will sustain this.",
            category      = "health",
            priority      = 1,
            context_state = state.value,
        ))

    if productive_minutes_today < 30 and is_work_block:
        results.append(RecommendationItem(
            text          = "Less than 30 minutes of productive work so far. Pick one task and start a focused 25-minute session.",
            category      = "focus",
            priority      = 2,
            context_state = state.value,
        ))

    # ── Memory-aware extras ───────────────────────────────────────────────────
    if goals or projects:
        from datetime import date as _date
        today = _date.today().isoformat()

        for goal in (goals or []):
            if goal.get("status") != "active":
                continue
            td = goal.get("target_date")
            if td and td >= today:
                from datetime import date as _d
                days_left = (_d.fromisoformat(td) - _d.fromisoformat(today)).days
                if days_left <= 7:
                    results.append(RecommendationItem(
                        text          = f"Goal '{goal['title'][:40]}' deadline in {days_left}d. Check your progress.",
                        category      = "focus",
                        priority      = 2,
                        context_state = state.value,
                    ))
                elif days_left <= 30:
                    results.append(RecommendationItem(
                        text          = f"Goal '{goal['title'][:40]}' due in {days_left}d ({int(goal.get('progress', 0))}% done).",
                        category      = "focus",
                        priority      = 1,
                        context_state = state.value,
                    ))

        for proj in (projects or []):
            if proj.get("status") not in ("active", "planning"):
                continue
            dl = proj.get("deadline")
            if dl and dl >= today:
                from datetime import date as _d
                days_left = (_d.fromisoformat(dl) - _d.fromisoformat(today)).days
                if days_left <= 3:
                    results.append(RecommendationItem(
                        text          = f"Project '{proj['name'][:40]}' deadline in {days_left}d. Wrap it up.",
                        category      = "focus",
                        priority      = 2,
                        context_state = state.value,
                    ))
                elif days_left <= 14:
                    results.append(RecommendationItem(
                        text          = f"Project '{proj['name'][:40]}' due in {days_left}d ({int(proj.get('progress', 0))}% done).",
                        category      = "focus",
                        priority      = 1,
                        context_state = state.value,
                    ))

    results.sort(key=lambda r: -r.priority)
    return results[:5]
