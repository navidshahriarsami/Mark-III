"""
MARK III — Goal Agent (Phase 13)

Monitors long-term goals and projects for:
  - Approaching deadlines (7 days, 3 days, tomorrow)
  - Overdue goals (target_date passed, status still "active")
  - Goals that haven't been touched in >14 days (stagnant)
  - Projects approaching deadline with low progress (<40%)

Fires: daily at 12:00 (noon), only when something needs attention.
Does nothing if all goals are healthy.

Anti-spam: min_interval_hours = 20 (once per day max)
Delivery: notification + message
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agents.base_agent import AgentResult, AgentRunContext, BaseAgent

logger = logging.getLogger(__name__)


class GoalAgent(BaseAgent):
    agent_id           = "goal_monitor"
    name               = "Goal Monitor"
    description        = "Tracks deadlines, stagnant goals, and at-risk projects"
    min_interval_hours = 20.0
    default_delivery   = ["notification", "message"]

    async def should_run(self, ctx: AgentRunContext) -> bool:
        # Run at noon, not quiet hours
        if ctx.is_quiet_hours:
            return False
        if ctx.hour < 11 or ctx.hour > 14:
            return False
        # Only run if something needs attention
        return self._has_attention_items(ctx)

    def _has_attention_items(self, ctx: AgentRunContext) -> bool:
        today    = datetime.now().date()
        cutoff_7 = (today + timedelta(days=7)).strftime("%Y-%m-%d")
        today_s  = today.strftime("%Y-%m-%d")

        # Any deadline in 7 days
        has_deadline = any(
            g.target_date and today_s <= g.target_date <= cutoff_7 and g.status == "active"
            for g in ctx.goals
        )
        # Any overdue
        has_overdue = any(
            g.target_date and g.target_date < today_s and g.status == "active"
            for g in ctx.goals
        )
        # Any low-progress project approaching deadline
        has_at_risk_project = any(
            p.deadline and p.deadline <= cutoff_7 and (p.progress or 0) < 40 and p.status == "active"
            for p in ctx.projects
        )
        return has_deadline or has_overdue or has_at_risk_project

    async def run(self, ctx: AgentRunContext, db: AsyncSession) -> AgentResult:
        import time
        t0 = time.monotonic()

        today    = datetime.now().date()
        today_s  = today.strftime("%Y-%m-%d")

        # Classify goals
        overdue = [
            g for g in ctx.goals
            if g.target_date and g.target_date < today_s and g.status == "active"
        ]
        due_tomorrow = [
            g for g in ctx.goals
            if g.target_date == (today + timedelta(days=1)).strftime("%Y-%m-%d") and g.status == "active"
        ]
        due_this_week = [
            g for g in ctx.goals
            if g.target_date and today_s < g.target_date <= (today + timedelta(days=7)).strftime("%Y-%m-%d")
            and g.status == "active"
        ]
        stagnant = [
            g for g in ctx.goals
            if (g.progress or 0) < 10 and g.status == "active"
        ]

        # At-risk projects
        at_risk_projects = [
            p for p in ctx.projects
            if p.deadline and p.deadline <= (today + timedelta(days=7)).strftime("%Y-%m-%d")
            and (p.progress or 0) < 40 and p.status == "active"
        ]

        # Build priority-sorted alert list for LLM
        def goal_line(g, label=""):
            return f"  [{label}] {g.title} — {g.progress}% — due {g.target_date or 'no date'}"

        alert_lines = []
        for g in overdue:       alert_lines.append(goal_line(g, "OVERDUE"))
        for g in due_tomorrow:  alert_lines.append(goal_line(g, "DUE TOMORROW"))
        for g in due_this_week: alert_lines.append(goal_line(g, "THIS WEEK"))
        for g in stagnant:      alert_lines.append(goal_line(g, "STAGNANT"))
        for p in at_risk_projects:
            alert_lines.append(f"  [AT-RISK PROJECT] {p.name} — {p.progress}% — deadline {p.deadline}")

        alert_block = "\n".join(alert_lines) or "  (nothing urgent)"

        urgency = "urgent" if overdue or due_tomorrow else "high" if due_this_week else "medium"

        system_prompt = f"""You are MARK III. Your goal tracking system has flagged items that need {ctx.user_name}'s attention.
Be direct and helpful. Do NOT pad the message.

For each flagged item:
  - Name it specifically
  - State why it's flagged (overdue / due soon / no progress)
  - Give one concrete action

Keep total under 150 words. No bullet points in the output — write naturally."""

        user_prompt = f"""Goal and project alerts for {ctx.user_name} as of {today_s}:

{alert_block}

Total overdue: {len(overdue)} | Due this week: {len(due_this_week)} | Stagnant: {len(stagnant)} | At-risk projects: {len(at_risk_projects)}

Generate the goal alert message."""

        text = await self._llm_call(system_prompt, user_prompt, ctx.device_id, tier="fast")

        if not text:
            parts = []
            if overdue:
                parts.append(f"{len(overdue)} overdue goal(s): {', '.join(g.title for g in overdue[:2])}.")
            if due_tomorrow:
                parts.append(f"Due tomorrow: {due_tomorrow[0].title}.")
            if at_risk_projects:
                parts.append(f"{at_risk_projects[0].name} is at {at_risk_projects[0].progress}% with deadline approaching.")
            text = " ".join(parts) or "Goals need attention — check your roadmap."

        title = (
            f"{len(overdue)} overdue goal(s)" if overdue
            else f"Deadline tomorrow: {due_tomorrow[0].title[:30]}" if due_tomorrow
            else "Goal check — action needed"
        )

        return AgentResult(
            agent_id  = self.agent_id,
            title     = title,
            text      = text,
            delivery  = self.default_delivery,
            priority  = urgency,
            success   = True,
            latency_ms = (time.monotonic() - t0) * 1000,
            metadata  = {
                "overdue":          len(overdue),
                "due_tomorrow":     len(due_tomorrow),
                "due_this_week":    len(due_this_week),
                "stagnant":         len(stagnant),
                "at_risk_projects": len(at_risk_projects),
            },
        )
