"""
MARK III — Agent Scheduler (Phase 13)

Drives when agents run.  Runs in the background as an asyncio task.

Loop cadence: every 60 seconds.

Per-device per-tick:
  1. Build AgentRunContext (one DB round-trip)
  2. For each registered agent (in priority order):
     a. Check min_interval_hours (last run from DB)
     b. Call agent.should_run(ctx)
     c. If both pass: fire agent (non-blocking — runs in its own task)
     d. Log to AgentRun table

Anti-spam guarantees:
  - min_interval enforced at scheduler level, not trust-based
  - is_quiet_hours check in AgentRunContext
  - Meeting / deep-focus suppression for interrupting agents
  - Agents can optionally skip delivery while still logging
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.services.agents.base_agent import BaseAgent, AgentRunContext

logger = logging.getLogger(__name__)

SCHEDULER_INTERVAL = 60   # seconds between ticks


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

async def build_agent_context(device_id: str, db: AsyncSession) -> "AgentRunContext":
    """
    Build AgentRunContext with a single DB round-trip (parallel selects).
    """
    from app.models.db import (
        UserProfile, LongTermGoal, Project, Memory,
        UserContext, DailyReport, WeeklyReport,
    )
    from app.services.policy.policy_context import UserPreferences
    from app.services.agents.base_agent import AgentRunContext

    now        = datetime.now()
    today_str  = now.strftime("%Y-%m-%d")

    # All reads in parallel
    profile_row, goals_rows, project_rows, memory_rows, context_row, daily_row, weekly_row = await asyncio.gather(
        db.execute(select(UserProfile).where(UserProfile.device_id == device_id)),
        db.execute(
            select(LongTermGoal)
            .where(LongTermGoal.device_id == device_id)
            .where(LongTermGoal.status.in_(["active", "in_progress"]))
            .order_by(LongTermGoal.updated_at.desc())
            .limit(20)
        ),
        db.execute(
            select(Project)
            .where(Project.device_id == device_id)
            .where(Project.status.in_(["active", "planning", "in_progress"]))
            .order_by(Project.updated_at.desc())
            .limit(20)
        ),
        db.execute(
            select(Memory)
            .where(Memory.device_id == device_id)
            .where(Memory.importance >= 3)
            .order_by(Memory.importance.desc(), Memory.ts.desc())
            .limit(15)
        ),
        db.execute(
            select(UserContext)
            .where(UserContext.device_id == device_id)
            .order_by(UserContext.ts.desc())
            .limit(1)
        ),
        db.execute(
            select(DailyReport)
            .where(DailyReport.device_id == device_id)
            .where(DailyReport.date == today_str)
            .order_by(DailyReport.generated_at.desc())
            .limit(1)
        ),
        db.execute(
            select(WeeklyReport)
            .where(WeeklyReport.device_id == device_id)
            .order_by(WeeklyReport.generated_at.desc())
            .limit(1)
        ),
    )

    profile     = profile_row.scalar_one_or_none()
    goals       = list(goals_rows.scalars().all())
    projects    = list(project_rows.scalars().all())
    memories    = list(memory_rows.scalars().all())
    recent_ctx  = context_row.scalar_one_or_none()
    daily       = daily_row.scalar_one_or_none()
    weekly      = weekly_row.scalar_one_or_none()

    prefs     = UserPreferences.from_profile(profile)
    hour      = now.hour
    weekday   = now.weekday()
    is_weekend = weekday >= 5

    # Work hours: Mon–Fri, prefs.work_start–work_end
    is_work_hours = (not is_weekend) and (prefs.work_start <= hour < prefs.work_end)

    # Quiet hours (wrap midnight)
    qs, qe = prefs.quiet_hours_start, prefs.quiet_hours_end
    is_quiet = (hour >= qs) or (hour < qe)

    # Focus score from today's daily report
    focus_score         = daily.focus_score if daily else 0.0
    distraction_minutes = daily.distraction_minutes if daily else 0.0
    productive_minutes  = daily.productive_minutes if daily else 0.0

    user_name = (profile.name.split()[0] if profile and profile.name else "there")

    return AgentRunContext(
        device_id         = device_id,
        ts                = time.time(),
        profile           = profile,
        goals             = goals,
        projects          = projects,
        memories          = memories,
        recent_context    = recent_ctx,
        daily_report      = daily,
        weekly_report     = weekly,
        preferences       = prefs,
        user_name         = user_name,
        hour              = hour,
        weekday           = weekday,
        is_weekend        = is_weekend,
        is_work_hours     = is_work_hours,
        is_quiet_hours    = is_quiet,
        focus_score       = focus_score,
        distraction_minutes = distraction_minutes,
        productive_minutes  = productive_minutes,
    )


# ---------------------------------------------------------------------------
# Last-run lookup
# ---------------------------------------------------------------------------

async def get_last_run(agent_id: str, device_id: str, db: AsyncSession) -> Optional[float]:
    """Return unix timestamp of most recent successful run for this agent+device."""
    from app.models.db import AgentRun
    row = (await db.execute(
        select(AgentRun.ran_at)
        .where(AgentRun.agent_id  == agent_id)
        .where(AgentRun.device_id == device_id)
        .where(AgentRun.success   == True)
        .order_by(AgentRun.ran_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return float(row) if row is not None else None


def is_within_interval(last_ran: Optional[float], min_hours: float) -> bool:
    """Return True if agent should be suppressed (ran too recently)."""
    if last_ran is None:
        return False   # never ran → allow
    elapsed_hours = (time.time() - last_ran) / 3600.0
    return elapsed_hours < min_hours


# ---------------------------------------------------------------------------
# AgentScheduler
# ---------------------------------------------------------------------------

class AgentScheduler:
    """
    Background loop that evaluates all agents every SCHEDULER_INTERVAL seconds.

    Agents are evaluated per registered device (devices with a UserProfile).
    """

    def __init__(self) -> None:
        self._agents:  list["BaseAgent"] = []
        self._task:    Optional[asyncio.Task] = None
        self._db_factory = None

    def register(self, agent: "BaseAgent") -> None:
        self._agents.append(agent)
        logger.info("Scheduler: registered agent '%s'", agent.agent_id)

    def set_db_factory(self, factory) -> None:
        self._db_factory = factory

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="agent-scheduler")
        logger.info("Agent Scheduler started (%d agents, interval=%ds)", len(self._agents), SCHEDULER_INTERVAL)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Agent Scheduler stopped.")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        await asyncio.sleep(30)   # let the server boot fully first
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Scheduler tick error: %s", exc)
            await asyncio.sleep(SCHEDULER_INTERVAL)

    async def _tick(self) -> None:
        if not self._db_factory or not self._agents:
            return

        async with self._db_factory() as db:
            # Get all devices with profiles (= devices MARK III knows about)
            from app.models.db import UserProfile
            devices = (await db.execute(select(UserProfile.device_id))).scalars().all()

        for device_id in devices:
            asyncio.create_task(
                self._evaluate_device(device_id),
                name=f"agent-eval-{device_id[:8]}",
            )

    async def _evaluate_device(self, device_id: str) -> None:
        if not self._db_factory:
            return
        try:
            async with self._db_factory() as db:
                ctx = await build_agent_context(device_id, db)

            for agent in self._agents:
                asyncio.create_task(
                    self._try_run(agent, ctx),
                    name=f"agent-{agent.agent_id}-{device_id[:8]}",
                )
        except Exception as exc:
            logger.error("Device evaluation failed device=%s: %s", device_id[:16], exc)

    async def _try_run(self, agent: "BaseAgent", ctx: "AgentRunContext") -> None:
        """Check interval + should_run, then execute if both pass."""
        try:
            async with self._db_factory() as db:
                last_ran = await get_last_run(agent.agent_id, ctx.device_id, db)

            if is_within_interval(last_ran, agent.min_interval_hours):
                return   # too soon

            should = await agent.should_run(ctx)
            if not should:
                return

            # Execute
            from app.services.agents.agent_manager import get_agent_manager
            manager = get_agent_manager()
            await manager.execute(agent, ctx)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Agent '%s' evaluation error for device=%s: %s",
                         agent.agent_id, ctx.device_id[:16], exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_scheduler: Optional[AgentScheduler] = None

def get_scheduler() -> AgentScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AgentScheduler()
    return _scheduler
