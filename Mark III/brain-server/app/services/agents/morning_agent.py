"""
MARK III — Morning Agent (Phase 13)

Fires at 08:00 every weekday (configurable).
Generates a personalised daily briefing covering:
  - Today's focus plan and energy allocation
  - Deadlines within 7 days
  - Active project status snapshot
  - Yesterday's focus score + trend
  - Top 2–3 actionable priorities
  - Encouragement tailored to the user's goals

Delivery: voice (if active) → push notification → message thread

Anti-spam: once per day (min_interval_hours = 20)
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agents.base_agent import AgentResult, AgentRunContext, BaseAgent

logger = logging.getLogger(__name__)


class MorningAgent(BaseAgent):
    agent_id           = "morning_briefing"
    name               = "Morning Briefing"
    description        = "Daily morning briefing with priorities, deadlines, and focus plan"
    min_interval_hours = 20.0
    default_delivery   = ["voice", "notification", "message"]

    async def should_run(self, ctx: AgentRunContext) -> bool:
        # Run 07:30–09:30 on any day (weekends too — user may want it)
        return 7 <= ctx.hour < 10 and not ctx.is_quiet_hours

    async def run(self, ctx: AgentRunContext, db: AsyncSession) -> AgentResult:
        import time
        t0 = time.monotonic()

        deadlines     = self._upcoming_deadlines(ctx, days=7)
        at_risk       = self._at_risk_projects(ctx)
        day_name      = datetime.now().strftime("%A")
        date_str      = datetime.now().strftime("%B %-d") if datetime.now().day > 1 else datetime.now().strftime("%B %d")

        # Build data block for LLM
        goals_lines = "\n".join(
            f"  • [{g.category}] {g.title} — {g.progress}% complete"
            + (f" (deadline: {g.target_date})" if g.target_date else "")
            for g in ctx.goals[:6]
        ) or "  (no active goals)"

        project_lines = "\n".join(
            f"  • {p.name} — {p.progress}% ({p.status})"
            + (f" [deadline: {p.deadline}]" if p.deadline else "")
            for p in ctx.projects[:5]
        ) or "  (no active projects)"

        deadline_lines = "\n".join(
            f"  ⚠ {g.title} due {g.target_date}"
            for g in deadlines
        ) or "  (none this week)"

        focus_line = (
            f"Yesterday's focus score: {ctx.daily_report.focus_score:.0f}% "
            f"({ctx.daily_report.productive_minutes:.0f}m productive, "
            f"{ctx.daily_report.distraction_minutes:.0f}m distracted)"
            if ctx.daily_report else "No focus data from yesterday."
        )

        career_line = ""
        if ctx.profile and ctx.profile.career:
            career_line = f"Career path: {ctx.profile.career}"

        system_prompt = f"""You are MARK III, a proactive AI operating system delivering a personalised morning briefing.
Speak directly to {ctx.user_name} in second person. Be motivating but concise.
Today is {day_name}, {date_str}.
{career_line}

Your briefing must:
1. Open with a single sharp sentence about what kind of day this should be.
2. Name the 2–3 most important things to accomplish today.
3. Flag any deadlines in the next 7 days.
4. Give a brief focus recommendation based on yesterday's productivity data.
5. Close with one sentence of encouragement.

Keep total length under 200 words. No bullet points — write in flowing paragraphs.
Do not mention the weather. Do not add pleasantries. Be direct."""

        user_prompt = f"""Data for {ctx.user_name}'s morning briefing:

ACTIVE GOALS:
{goals_lines}

ACTIVE PROJECTS:
{project_lines}

UPCOMING DEADLINES (7 days):
{deadline_lines}

PRODUCTIVITY:
{focus_line}

Generate the morning briefing now."""

        text = await self._llm_call(system_prompt, user_prompt, ctx.device_id, tier="fast")

        if not text:
            text = (
                f"Good morning, {ctx.user_name}. "
                f"You have {len(ctx.goals)} active goals and {len(ctx.projects)} projects in flight. "
                + (f"{len(deadlines)} deadline(s) approaching this week. " if deadlines else "")
                + "Make today count."
            )

        return AgentResult(
            agent_id  = self.agent_id,
            title     = f"Good morning, {ctx.user_name}",
            text      = text,
            delivery  = self.default_delivery,
            priority  = "high",
            success   = True,
            latency_ms = (time.monotonic() - t0) * 1000,
            metadata  = {
                "goals_count":     len(ctx.goals),
                "deadlines_count": len(deadlines),
                "at_risk_count":   len(at_risk),
                "focus_score":     ctx.focus_score,
            },
        )
