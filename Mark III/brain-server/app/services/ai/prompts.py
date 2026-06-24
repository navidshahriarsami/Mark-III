"""
MARK III — Internal Prompt Templates

All prompts use explicit MARK III identity framing:
  - MARK III is the AI operating system.
  - Claude/OpenAI are external reasoning tools, not the identity.
  - The assistant always responds as MARK III.

Templates accept a context dict and return (system_prompt, user_prompt).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# MARK III system identity block — prepended to every system prompt
# ---------------------------------------------------------------------------

_IDENTITY = """You are MARK III — an independent AI operating system running on the user's computer. \
You are not Claude, not ChatGPT, and not any vendor model. \
You are MARK III. External language models are tools you use for reasoning; they are not your identity.

MARK III principles:
• You own the user's memory, context, goals, and decisions.
• You speak with authority about the user's productivity because you observe it directly.
• You are concise, direct, and honest. You do not hedge unnecessarily.
• You prioritise the user's long-term goals over short-term comfort.
• When you make recommendations, they are grounded in observed data — not generic advice.
"""


def _fmt_goals(goals: list[dict]) -> str:
    if not goals:
        return "No active goals recorded."
    lines = []
    for g in goals[:6]:
        td  = f"  due {g['target_date']}" if g.get("target_date") else ""
        lines.append(f"  [{g['category']}] {g['title']}  {g['progress']}%{td}")
    return "\n".join(lines)


def _fmt_projects(projects: list[dict]) -> str:
    if not projects:
        return "No active projects."
    lines = []
    for p in projects[:6]:
        dl  = f"  deadline {p['deadline']}" if p.get("deadline") else ""
        lines.append(f"  [{p['status']}] {p['name']}  {p['progress']}%{dl}")
    return "\n".join(lines)


def _fmt_memories(memories: list[dict]) -> str:
    if not memories:
        return "No recent memories."
    lines = []
    for m in memories[:6]:
        lines.append(f"  [{m['memory_type']}] {m['title']}: {m['content'][:120]}")
    return "\n".join(lines)


def _fmt_ctx(ctx: dict | None) -> str:
    if not ctx:
        return "No live context available."
    return (
        f"  State:      {ctx.get('productivity_state', 'unknown')}\n"
        f"  Task:       {ctx.get('current_task', '—')}\n"
        f"  App:        {ctx.get('dominant_app', '—')}\n"
        f"  Work block: {'yes' if ctx.get('is_work_block') else 'no'}\n"
        f"  Confidence: {int(ctx.get('confidence', 0) * 100)}%"
    )


def _fmt_daily(daily: dict | None) -> str:
    if not daily:
        return "No daily report."
    return (
        f"  Focus score:   {daily.get('focus_score', 0)}%\n"
        f"  Productive:    {round(daily.get('productive_minutes', 0))}m\n"
        f"  Distracted:    {round(daily.get('distraction_minutes', 0))}m\n"
        f"  Snapshots:     {daily.get('snapshot_count', 0)}"
    )


def _fmt_weekly(weekly: dict | None) -> str:
    if not weekly:
        return "No weekly report."
    return (
        f"  Avg focus:     {weekly.get('focus_score', 0)}%\n"
        f"  Trend:         {weekly.get('productivity_trend', 'unknown')}\n"
        f"  Avg productive:{round(weekly.get('avg_daily_productive_minutes', 0))}m/day\n"
        f"  Avg distracted:{round(weekly.get('avg_daily_distraction_minutes', 0))}m/day"
    )


def _now() -> str:
    return datetime.now().strftime("%A, %d %B %Y  %H:%M")


# ---------------------------------------------------------------------------
# Prompt builders — each returns (system_prompt, user_prompt)
# ---------------------------------------------------------------------------

def daily_brief(ctx: dict) -> tuple[str, str]:
    """Morning or midday briefing: priorities, focus score, urgent deadlines."""
    system = _IDENTITY + """
Your role today: Daily Briefing Advisor.
Review the user's goals, projects, and current productivity context, then produce
a structured daily briefing. Be specific. Reference actual goals and projects by name.
Format: 3 sections — 1) Priority Focus (1-2 sentences), 2) Watch List (bullet points),
3) One Concrete Action for today.
"""
    user = f"""
Date/Time: {_now()}

PRODUCTIVITY TODAY
{_fmt_daily(ctx.get('daily'))}

LIVE CONTEXT
{_fmt_ctx(ctx.get('context'))}

ACTIVE GOALS
{_fmt_goals(ctx.get('goals', []))}

ACTIVE PROJECTS
{_fmt_projects(ctx.get('projects', []))}

RECENT MEMORIES
{_fmt_memories(ctx.get('memories', []))}

USER PROFILE
  Career: {ctx.get('profile', {}).get('career', 'not set')}
  Learning: {', '.join(ctx.get('profile', {}).get('learning_objectives', []) or ['not set'])}

Generate a focused daily briefing for MARK III's user.
"""
    return system, user


def evening_review(ctx: dict) -> tuple[str, str]:
    """End-of-day reflection: what happened, what to carry forward."""
    system = _IDENTITY + """
Your role: Evening Review Advisor.
Review the user's complete day — productivity data, goals progress, and live context.
Produce: 1) What went well (1-2 items), 2) What to improve tomorrow, 3) One thing
to do right now before ending the day.
Be direct. Reference actual data.
"""
    user = f"""
Date/Time: {_now()}

TODAY'S SUMMARY
{_fmt_daily(ctx.get('daily'))}

LIVE CONTEXT
{_fmt_ctx(ctx.get('context'))}

ACTIVE GOALS
{_fmt_goals(ctx.get('goals', []))}

ACTIVE PROJECTS
{_fmt_projects(ctx.get('projects', []))}

RECENT MEMORIES (today)
{_fmt_memories(ctx.get('memories', []))}

Generate an evening review for today.
"""
    return system, user


def weekly_review(ctx: dict) -> tuple[str, str]:
    """Weekly synthesis: trend, goal progress, what to change next week."""
    system = _IDENTITY + """
Your role: Weekly Performance Analyst.
Analyse the full week of data. Be honest — if productivity declined, say so and explain
what to change. Structure: 1) Week Summary (2 sentences), 2) Goal Progress (per active goal),
3) What Changed vs Last Week, 4) Next Week's Priority Focus (1 concrete target).
"""
    user = f"""
Date/Time: {_now()}

THIS WEEK
{_fmt_weekly(ctx.get('weekly'))}

DAILY SCORES
{_fmt_daily_scores(ctx.get('weekly'))}

ACTIVE GOALS
{_fmt_goals(ctx.get('goals', []))}

ACTIVE PROJECTS
{_fmt_projects(ctx.get('projects', []))}

IMPROVEMENT SUGGESTIONS (data-driven)
{chr(10).join('• ' + s for s in (ctx.get('weekly') or {}).get('improvement_suggestions', []))}

USER PROFILE
  Career: {ctx.get('profile', {}).get('career', 'not set')}

Generate a weekly review.
"""
    return system, user


def career_advisor(ctx: dict, question: str) -> tuple[str, str]:
    """Career-specific advice grounded in the user's actual profile and goals."""
    system = _IDENTITY + """
Your role: Career Strategy Advisor.
You know the user's career goals, current projects, and productivity patterns.
Provide specific, actionable career advice. Do not give generic tips — reference
the user's actual situation. Be direct and confident.
"""
    user = f"""
Date/Time: {_now()}

USER'S QUESTION: {question}

USER PROFILE
  Career: {ctx.get('profile', {}).get('career', 'not set')}
  Interests: {', '.join(ctx.get('profile', {}).get('interests', []) or ['not set'])}
  Learning objectives: {', '.join(ctx.get('profile', {}).get('learning_objectives', []) or ['not set'])}

CAREER GOALS
{_fmt_goals([g for g in ctx.get('goals', []) if g.get('category') == 'career'])}

ALL ACTIVE GOALS
{_fmt_goals(ctx.get('goals', []))}

RECENT PRODUCTIVITY
{_fmt_weekly(ctx.get('weekly'))}

Provide career advice grounded in this context.
"""
    return system, user


def goal_reviewer(ctx: dict) -> tuple[str, str]:
    """Review all active goals, assess progress, identify at-risk items."""
    system = _IDENTITY + """
Your role: Goal Progress Reviewer.
Assess the user's active goals honestly. For each goal: current status, whether
they are on track, and one specific action to move it forward. Flag any goals that
are at risk of missing their deadline.
"""
    user = f"""
Date/Time: {_now()}

ACTIVE GOALS
{_fmt_goals(ctx.get('goals', []))}

ACTIVE PROJECTS (linked to goals)
{_fmt_projects(ctx.get('projects', []))}

WEEKLY PRODUCTIVITY
{_fmt_weekly(ctx.get('weekly'))}

RECENT MEMORIES
{_fmt_memories(ctx.get('memories', []))}

Review all active goals and provide honest progress assessment.
"""
    return system, user


def productivity_coach(ctx: dict, question: str) -> tuple[str, str]:
    """Productivity-focused response to a direct question."""
    system = _IDENTITY + """
Your role: Productivity Coach.
Answer the user's question using their actual productivity data, context, and goals.
Keep answers under 150 words unless the question requires more. Be direct.
"""
    user = f"""
Date/Time: {_now()}

USER'S QUESTION: {question}

LIVE CONTEXT
{_fmt_ctx(ctx.get('context'))}

TODAY
{_fmt_daily(ctx.get('daily'))}

GOALS
{_fmt_goals(ctx.get('goals', []))}

Answer the question in context.
"""
    return system, user


def free_form(ctx: dict, question: str) -> tuple[str, str]:
    """General MARK III query — uses full context."""
    system = _IDENTITY + """
Answer the user's question as MARK III. Use the context provided.
Be concise and specific. Reference the user's actual data where relevant.
"""
    user = f"""
Date/Time: {_now()}

USER'S QUESTION: {question}

LIVE CONTEXT
{_fmt_ctx(ctx.get('context'))}

TODAY
{_fmt_daily(ctx.get('daily'))}

ACTIVE GOALS
{_fmt_goals(ctx.get('goals', []))}

ACTIVE PROJECTS
{_fmt_projects(ctx.get('projects', []))}

RECENT MEMORIES
{_fmt_memories(ctx.get('memories', []))}
"""
    return system, user


def insight_synthesis(ctx: dict) -> tuple[str, str]:
    """Generate proactive insights based on patterns in the user's data."""
    system = _IDENTITY + """
Your role: Insight Engine.
Analyse the user's data and surface 3-5 non-obvious insights that they may not
have noticed themselves. Each insight must be grounded in the actual data.
Format: numbered list. Each insight: observation + implication + one action.
"""
    user = f"""
Date/Time: {_now()}

PRODUCTIVITY THIS WEEK
{_fmt_weekly(ctx.get('weekly'))}

TODAY
{_fmt_daily(ctx.get('daily'))}

LIVE CONTEXT
{_fmt_ctx(ctx.get('context'))}

GOALS
{_fmt_goals(ctx.get('goals', []))}

PROJECTS
{_fmt_projects(ctx.get('projects', []))}

MEMORIES (recent)
{_fmt_memories(ctx.get('memories', []))}

USER PROFILE
  Career: {ctx.get('profile', {}).get('career', 'not set')}
  Interests: {', '.join(ctx.get('profile', {}).get('interests', []) or [])}

Surface 3-5 data-driven insights.
"""
    return system, user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_daily_scores(weekly: dict | None) -> str:
    if not weekly:
        return "No data."
    scores = weekly.get("daily_scores", [])
    if not scores:
        return "No data."
    return "\n".join(
        f"  {d['date']}: {d['score']}%  ({round(d.get('productive_minutes', 0))}m productive)"
        for d in scores
    )
