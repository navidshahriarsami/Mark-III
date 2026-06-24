"""
MARK III — Evening Agent (Phase 13)

Fires 19:00–20:30 every day.
Generates an end-of-day debrief covering:
  - What was accomplished (wins)
  - Productivity score vs goal
  - What slipped (unfinished work, distraction patterns)
  - Suggestions for tomorrow
  - Optional: update on goal progress trend

Delivery: notification → message (voice is usually lower priority at evening)

Anti-spam: once per day (min_interval_hours = 20)
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agents.base_agent import AgentResult, AgentRunContext, BaseAgent

logger = logging.getLogger(__name__)


class EveningAgent(BaseAgent):
    agent_id           = "evening_debrief"
    name               = "Evening Debrief"
    description        = "End-of-day summary with wins, missed items, and tomorrow's suggestions"
    min_interval_hours = 20.0
    default_delivery   = ["notification", "message"]

    async def should_run(self, ctx: AgentRunContext) -> bool:
        # Run 19:00–21:00, not during quiet hours
        return 19 <= ctx.hour < 21 and not ctx.is_quiet_hours

    async def run(self, ctx: AgentRunContext, db: AsyncSession) -> AgentResult:
        import time
        t0 = time.monotonic()

        day_name = datetime.now().strftime("%A")

        # Build data
        focus_score = ctx.daily_report.focus_score if ctx.daily_report else 0
        prod_mins   = ctx.daily_report.productive_minutes if ctx.daily_report else 0
        dist_mins   = ctx.daily_report.distraction_minutes if ctx.daily_report else 0

        goals_lines = "\n".join(
            f"  • [{g.category}] {g.title} — {g.progress}%"
            for g in ctx.goals[:6]
        ) or "  (no active goals)"

        project_lines = "\n".join(
            f"  • {p.name} — {p.progress}% ({p.status})"
            for p in ctx.projects[:5]
        ) or "  (no active projects)"

        # Identify stalled projects (low progress, active)
        stalled = [p for p in ctx.projects if p.status == "active" and (p.progress or 0) < 20]
        stalled_lines = "\n".join(f"  ⚠ {p.name}" for p in stalled) or "  (none)"

        productivity_note = (
            f"Focus score: {focus_score:.0f}% | "
            f"Productive: {prod_mins:.0f}m | "
            f"Distracted: {dist_mins:.0f}m"
        )

        system_prompt = f"""You are MARK III delivering a concise end-of-day debrief to {ctx.user_name}.
Today is {day_name}.

Your debrief must:
1. Acknowledge what went well today (draw from the productivity data).
2. Be honest about what didn't — distraction time, stalled projects.
3. Give 2 specific suggestions for tomorrow.
4. Keep the tone constructive and grounded — not preachy.

Under 180 words. No bullet lists — flowing paragraphs. Direct second-person voice."""

        user_prompt = f"""End-of-day data for {ctx.user_name}:

PRODUCTIVITY:
{productivity_note}

GOAL STATUS:
{goals_lines}

PROJECT STATUS:
{project_lines}

STALLED PROJECTS (active but <20% progress):
{stalled_lines}

Generate the evening debrief."""

        text = await self._llm_call(system_prompt, user_prompt, ctx.device_id, tier="fast")

        if not text:
            if focus_score >= 70:
                text = f"Solid day, {ctx.user_name}. Focus score: {focus_score:.0f}%. {len(stalled)} project(s) still need attention. Tomorrow, start with your hardest task first."
            else:
                text = f"Tough one today, {ctx.user_name} — {dist_mins:.0f} minutes lost to distraction. Tomorrow: one goal, no switching."

        return AgentResult(
            agent_id  = self.agent_id,
            title     = f"Day wrap — {day_name}",
            text      = text,
            delivery  = self.default_delivery,
            priority  = "medium",
            success   = True,
            latency_ms = (time.monotonic() - t0) * 1000,
            metadata  = {
                "focus_score":   focus_score,
                "prod_minutes":  prod_mins,
                "dist_minutes":  dist_mins,
                "stalled_count": len(stalled),
            },
        )
