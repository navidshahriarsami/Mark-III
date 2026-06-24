"""
MARK III — Career Agent (Phase 13)

Fires Monday, Wednesday, Friday at 14:00 (early afternoon).
Tracks career trajectory specifically:
  - Job application status (read from Memory rows with type="career" or tags containing "application")
  - Portfolio/showcase projects (projects tagged as "portfolio" or "showcase")
  - Learning goals progress (goals with category="learning" or "skill")
  - GitHub/code output (inferred from activity patterns)
  - Career-relevant deadlines (applications, interview prep, submissions)

Generates a focused career check-in that differs from the goal agent:
  - Strategic, not tactical
  - Connects current work to career trajectory
  - Surfaces opportunities the user may not be acting on

Anti-spam: min_interval_hours = 44 (Mon/Wed/Fri = ~every 48h)
Delivery: message + notification
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agents.base_agent import AgentResult, AgentRunContext, BaseAgent

logger = logging.getLogger(__name__)

_CAREER_GOAL_CATEGORIES  = {"career", "learning", "skill", "education", "certification"}
_CAREER_MEMORY_TYPES     = {"career", "application", "interview", "networking", "achievement"}
_PORTFOLIO_KEYWORDS      = {"portfolio", "showcase", "github", "open source", "publish", "launch"}


class CareerAgent(BaseAgent):
    agent_id           = "career_tracker"
    name               = "Career Tracker"
    description        = "Strategic career check-in: applications, learning, portfolio, trajectory"
    min_interval_hours = 44.0   # Mon/Wed/Fri
    default_delivery   = ["notification", "message"]

    async def should_run(self, ctx: AgentRunContext) -> bool:
        # Monday (0), Wednesday (2), Friday (4) — 13:00–16:00
        if ctx.weekday not in (0, 2, 4):
            return False
        if ctx.is_quiet_hours or ctx.hour < 13 or ctx.hour > 16:
            return False
        # Only if user has a career path set
        return bool(ctx.profile and ctx.profile.career)

    async def run(self, ctx: AgentRunContext, db: AsyncSession) -> AgentResult:
        import time
        t0 = time.monotonic()

        career = getattr(ctx.profile, "career", "") or "professional"
        today  = datetime.now().strftime("%Y-%m-%d")

        # Career-specific goals
        career_goals = [
            g for g in ctx.goals
            if (g.category or "").lower() in _CAREER_GOAL_CATEGORIES
        ]
        # Learning goals specifically
        learning_goals = [g for g in career_goals if (g.category or "").lower() in {"learning", "skill", "education"}]

        # Portfolio projects
        portfolio_projects = [
            p for p in ctx.projects
            if any(kw in (p.name + " " + (p.description or "")).lower() for kw in _PORTFOLIO_KEYWORDS)
            or p.status == "active"
        ]

        # Career memories (applications, interviews, achievements)
        career_memories = [
            m for m in ctx.memories
            if (m.memory_type or "").lower() in _CAREER_MEMORY_TYPES
        ]

        # Career deadlines
        cutoff = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        career_deadlines = [
            g for g in career_goals
            if g.target_date and g.target_date <= cutoff
        ]

        career_goals_block = "\n".join(
            f"  • [{g.category}] {g.title} — {g.progress}%"
            + (f" (due {g.target_date})" if g.target_date else "")
            for g in career_goals[:6]
        ) or "  (no career/learning goals set)"

        portfolio_block = "\n".join(
            f"  • {p.name} — {p.progress}% ({p.status})"
            for p in portfolio_projects[:5]
        ) or "  (no portfolio projects)"

        memory_block = "\n".join(
            f"  • [{m.memory_type}] {m.title}: {m.content[:80]}"
            for m in career_memories[:5]
        ) or "  (no career memories recorded)"

        learning_str = ", ".join(g.title for g in learning_goals[:3]) if learning_goals else "none tracked"

        system_prompt = f"""You are MARK III — {ctx.user_name}'s AI operating system with a view into their work, goals, and career trajectory.

Today's check-in is focused entirely on career strategy. {ctx.user_name} is working toward: {career}.

Your message must:
1. Give a clear, honest assessment of where their career trajectory stands right now.
2. Identify ONE thing they should have done this week that they may not have.
3. Highlight their most career-relevant active work (don't just list — interpret it).
4. Give one concrete action to move their career forward TODAY.
5. If there are skill gaps or learning goals falling behind, name them.

Tone: strategic, peer-level, honest. Like a senior colleague who wants them to succeed.
Under 200 words. Flowing prose. Direct."""

        user_prompt = f"""Career data for {ctx.user_name} ({career}):

CAREER & LEARNING GOALS:
{career_goals_block}

PORTFOLIO / ACTIVE PROJECTS:
{portfolio_block}

CAREER MEMORIES (applications, interviews, achievements):
{memory_block}

CURRENT LEARNING FOCUS: {learning_str}
CAREER DEADLINES (next 14 days): {len(career_deadlines)} item(s)
TODAY'S FOCUS SCORE: {ctx.focus_score:.0f}%

Generate the career check-in."""

        text = await self._llm_call(system_prompt, user_prompt, ctx.device_id, tier="deep")

        if not text:
            parts = [f"Career check-in, {ctx.user_name}."]
            if career_goals:
                parts.append(f"{len(career_goals)} career goal(s) active — {learning_goals[0].title if learning_goals else 'keep pushing on your learning'}.")
            if portfolio_projects:
                parts.append(f"{portfolio_projects[0].name} needs attention ({portfolio_projects[0].progress}%).")
            if not career_memories:
                parts.append("No recent applications or networking logged — add an entry.")
            text = " ".join(parts)

        day_name = datetime.now().strftime("%A")
        return AgentResult(
            agent_id  = self.agent_id,
            title     = f"Career check-in — {day_name}",
            text      = text,
            delivery  = self.default_delivery,
            priority  = "medium",
            success   = True,
            latency_ms = (time.monotonic() - t0) * 1000,
            metadata  = {
                "career_goals":      len(career_goals),
                "portfolio_projects": len(portfolio_projects),
                "career_memories":   len(career_memories),
                "deadlines_14d":     len(career_deadlines),
            },
        )
