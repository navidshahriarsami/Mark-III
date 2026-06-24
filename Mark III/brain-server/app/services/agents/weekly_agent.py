"""
MARK III — Weekly Agent (Phase 13)

Fires Saturday 09:00–11:00.
Generates a comprehensive weekly review covering:
  - Week's productivity summary (from DailyReport + WeeklyReport)
  - Goal progress across all active goals
  - Project velocity (which moved, which stalled)
  - Wins worth celebrating
  - Next week's top priorities (ranked)
  - One strategic insight connecting goals to current work

Delivery: notification + message (voice optional)

Anti-spam: once per week (min_interval_hours = 120)
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agents.base_agent import AgentResult, AgentRunContext, BaseAgent

logger = logging.getLogger(__name__)


class WeeklyAgent(BaseAgent):
    agent_id           = "weekly_review"
    name               = "Weekly Review"
    description        = "Saturday deep-dive: goal progress, project velocity, next-week priorities"
    min_interval_hours = 120.0   # 5 days
    default_delivery   = ["notification", "message"]

    async def should_run(self, ctx: AgentRunContext) -> bool:
        # Saturday (weekday=5), 09:00–12:00
        return ctx.weekday == 5 and 9 <= ctx.hour < 12 and not ctx.is_quiet_hours

    async def run(self, ctx: AgentRunContext, db: AsyncSession) -> AgentResult:
        import time
        t0 = time.monotonic()

        # Pull this week's daily reports for aggregate stats
        from app.models.db import DailyReport
        from datetime import timedelta

        today      = datetime.now().date()
        week_start = today - timedelta(days=7)

        week_reports = (await db.execute(
            select(DailyReport)
            .where(DailyReport.device_id == ctx.device_id)
            .where(DailyReport.date >= week_start.strftime("%Y-%m-%d"))
            .order_by(DailyReport.date)
        )).scalars().all()

        avg_focus   = sum(r.focus_score or 0 for r in week_reports) / len(week_reports) if week_reports else 0
        total_prod  = sum(r.productive_minutes or 0 for r in week_reports)
        total_dist  = sum(r.distraction_minutes or 0 for r in week_reports)
        days_tracked = len(week_reports)

        # Goal health classification
        on_track   = [g for g in ctx.goals if (g.progress or 0) >= 50 or g.status == "active"]
        at_risk    = self._upcoming_deadlines(ctx, days=14)
        stalled    = [g for g in ctx.goals if (g.progress or 0) < 20 and g.status == "active"]

        goals_detail = "\n".join(
            f"  • [{g.category}] {g.title}: {g.progress}%"
            + (f" — due {g.target_date}" if g.target_date else "")
            for g in ctx.goals[:8]
        ) or "  (no active goals)"

        projects_detail = "\n".join(
            f"  • {p.name}: {p.progress}% ({p.status})"
            + (f" — deadline {p.deadline}" if p.deadline else "")
            for p in ctx.projects[:8]
        ) or "  (no active projects)"

        weekly_summary = ctx.weekly_report.summary if ctx.weekly_report else "(no weekly report)"

        system_prompt = f"""You are MARK III delivering {ctx.user_name}'s weekly review — a strategic, honest assessment of the week.

This is the most important MARK III message of the week. It must be:
1. Grounded in real data (the numbers below are real)
2. Honest — name what went well AND what didn't
3. Forward-looking — the last third should be about next week
4. Strategic — connect day-to-day patterns to long-term goals

Structure:
1. THIS WEEK (2–3 sentences on what happened — productivity, big wins, big misses)
2. GOALS & PROJECTS (2–3 sentences on progress — what moved, what's stuck)
3. NEXT WEEK (3 specific priorities for the coming week, ranked by importance)
4. ONE INSIGHT (a single observation connecting work patterns to long-term trajectory)

250–300 words. No bullet lists — flowing prose. Direct, personal, no filler."""

        user_prompt = f"""Weekly data for {ctx.user_name}:

WEEK OF {week_start.strftime('%B %d')} → {today.strftime('%B %d')}:
  Days tracked:       {days_tracked}
  Average focus score: {avg_focus:.0f}%
  Total productive:   {total_prod:.0f} minutes
  Total distracted:   {total_dist:.0f} minutes

GOALS:
{goals_detail}

PROJECTS:
{projects_detail}

AT-RISK DEADLINES (next 14 days): {len(at_risk)} item(s)
STALLED GOALS (<20% progress):   {len(stalled)} item(s)

SYSTEM WEEKLY SUMMARY:
{weekly_summary}

Generate the weekly review."""

        text = await self._llm_call(system_prompt, user_prompt, ctx.device_id, tier="deep")

        if not text:
            text = (
                f"Week in review, {ctx.user_name}: {days_tracked} days tracked, "
                f"{avg_focus:.0f}% average focus. "
                f"{len(ctx.goals)} goals active, {len(at_risk)} with approaching deadlines. "
                f"Next week: close the gaps on {stalled[0].title if stalled else 'your stalled work'}."
            )

        return AgentResult(
            agent_id  = self.agent_id,
            title     = f"Weekly review — {today.strftime('week of %b %d')}",
            text      = text,
            delivery  = self.default_delivery,
            priority  = "high",
            success   = True,
            latency_ms = (time.monotonic() - t0) * 1000,
            metadata  = {
                "avg_focus_score":  avg_focus,
                "total_productive": total_prod,
                "total_distracted": total_dist,
                "days_tracked":     days_tracked,
                "goals_at_risk":    len(at_risk),
                "goals_stalled":    len(stalled),
            },
        )
