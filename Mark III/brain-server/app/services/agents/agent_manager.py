"""
MARK III — Agent Manager (Phase 13)

Central hub for:
  - Registering all agents
  - Executing agents (run + deliver + persist)
  - Routing delivery to voice / notification / message channels
  - Manual trigger API

Delivery routing:
  "voice"        → voice_daemon.speak() if device has active session
                   → falls back to notification if voice unavailable
  "notification" → NotificationExecutor (desktop toast + push)
  "message"      → insert AgentResult as assistant message in conversation
  "none"         → log only (quiet hours, user focused)

Anti-spam: scheduler enforces min_interval before calling execute().
Agent manager does NOT re-check — interval is scheduler's responsibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agents.base_agent import BaseAgent, AgentResult, AgentRunContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AgentManager
# ---------------------------------------------------------------------------

class AgentManager:

    def __init__(self) -> None:
        self._agents:     dict[str, "BaseAgent"] = {}
        self._db_factory  = None
        self._running     = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def register(self, agent: "BaseAgent") -> None:
        self._agents[agent.agent_id] = agent
        logger.info("AgentManager: registered '%s'", agent.agent_id)

    def set_db_factory(self, factory) -> None:
        self._db_factory = factory

    def get_agent(self, agent_id: str) -> Optional["BaseAgent"]:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[dict]:
        return [
            {
                "agent_id":           a.agent_id,
                "name":               a.name,
                "description":        a.description,
                "min_interval_hours": a.min_interval_hours,
                "default_delivery":   a.default_delivery,
            }
            for a in self._agents.values()
        ]

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        agent:         "BaseAgent",
        ctx:           "AgentRunContext",
        manual:        bool = False,
    ) -> "AgentResult":
        """
        Run the agent, deliver its output, and persist the run log.
        If manual=True, bypasses quiet-hours delivery suppression.
        """
        from app.services.agents.base_agent import AgentResult

        t0 = time.monotonic()
        logger.info(
            "Agent '%s' executing  device=%s  manual=%s",
            agent.agent_id, ctx.device_id[:16], manual,
        )

        try:
            async with self._db_ctx() as db:
                result = await agent.run(ctx, db)
        except Exception as exc:
            result = AgentResult(
                agent_id = agent.agent_id,
                title    = agent.name,
                text     = "",
                success  = False,
                error    = str(exc),
            )
            logger.error("Agent '%s' run() raised: %s", agent.agent_id, exc)

        result.latency_ms = (time.monotonic() - t0) * 1000

        # Suppress delivery during quiet hours unless manual trigger
        delivery = result.delivery if (manual or not ctx.is_quiet_hours) else ["none"]

        await self._deliver(result, ctx, delivery)
        await self._persist(result, ctx)

        logger.info(
            "Agent '%s' done  success=%s  latency=%.0fms  delivery=%s",
            agent.agent_id, result.success, result.latency_ms, delivery,
        )
        return result

    async def manual_trigger(
        self,
        agent_id:  str,
        device_id: str,
    ) -> Optional["AgentResult"]:
        """
        Manually trigger an agent (API endpoint, debug/admin).
        Bypasses should_run() and min_interval.
        """
        agent = self._agents.get(agent_id)
        if not agent:
            return None

        try:
            async with self._db_ctx() as db:
                from app.services.agents.scheduler import build_agent_context
                ctx = await build_agent_context(device_id, db)
            return await self.execute(agent, ctx, manual=True)
        except Exception as exc:
            logger.error("Manual trigger '%s' failed: %s", agent_id, exc)
            return None

    # ------------------------------------------------------------------
    # Delivery routing
    # ------------------------------------------------------------------

    async def _deliver(
        self,
        result:   "AgentResult",
        ctx:      "AgentRunContext",
        delivery: list[str],
    ) -> None:
        if not result.success or not result.text:
            return

        tasks = []
        for channel in delivery:
            if channel == "voice":
                tasks.append(self._deliver_voice(result, ctx))
            elif channel == "notification":
                tasks.append(self._deliver_notification(result, ctx))
            elif channel == "message":
                tasks.append(self._deliver_message(result, ctx))
            # "none" → skip silently

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.warning("Delivery channel failed (%s): %s", delivery[i], r)

    async def _deliver_voice(self, result: "AgentResult", ctx: "AgentRunContext") -> None:
        try:
            from app.services.voice.voice_daemon import get_voice_daemon
            daemon = get_voice_daemon()
            if daemon.is_active_for(ctx.device_id):
                await daemon.speak(ctx.device_id, result.text)
            else:
                # Voice unavailable — fall through to notification
                await self._deliver_notification(result, ctx)
        except Exception as exc:
            logger.debug("Voice delivery failed (non-fatal): %s", exc)
            await self._deliver_notification(result, ctx)

    async def _deliver_notification(self, result: "AgentResult", ctx: "AgentRunContext") -> None:
        try:
            from app.services.actions.base_action import Action, ActionRequest, ActionState
            from app.services.actions.executors.notification_executor import get_notification_executor
            import uuid, time

            executor = get_notification_executor()
            # Build a minimal Action object for the executor
            action = Action(
                id            = str(uuid.uuid4()),
                action_type   = "send_notification",
                safety_level  = "caution",
                parameters    = {"title": result.title[:50], "body": result.text[:200], "sound": True},
                state         = ActionState.RUNNING.value,
                source        = "agent",
                device_id     = ctx.device_id,
                session_id    = None,
                context_hint  = result.agent_id,
                created_at    = time.time(),
                updated_at    = time.time(),
            )
            await executor.run(action)
        except Exception as exc:
            logger.warning("Notification delivery failed: %s", exc)

    async def _deliver_message(self, result: "AgentResult", ctx: "AgentRunContext") -> None:
        """
        Insert the agent output as an assistant message in the user's most recent
        conversation session (or create a new 'MARK III Proactive' session).
        """
        try:
            async with self._db_ctx() as db:
                from app.models.db import ConversationSession, ConversationMessage
                from sqlalchemy import select, desc
                import time

                # Find most recent active session
                session = (await db.execute(
                    select(ConversationSession)
                    .where(ConversationSession.device_id == ctx.device_id)
                    .where(ConversationSession.is_active == True)
                    .order_by(desc(ConversationSession.updated_at))
                    .limit(1)
                )).scalar_one_or_none()

                if not session:
                    # Create a proactive session
                    session = ConversationSession(
                        id         = str(uuid.uuid4()),
                        device_id  = ctx.device_id,
                        title      = "MARK III — Proactive",
                        created_at = time.time(),
                        updated_at = time.time(),
                    )
                    db.add(session)
                    await db.flush()

                # Insert as assistant message
                msg = ConversationMessage(
                    session_id    = session.id,
                    device_id     = ctx.device_id,
                    role          = "assistant",
                    content       = f"**{result.title}**\n\n{result.text}",
                    provider      = "agent",
                    model         = result.agent_id,
                    ts            = time.time(),
                )
                db.add(msg)
                session.message_count += 1
                session.updated_at     = time.time()
                await db.commit()
                logger.debug(
                    "Agent message delivered to session=%s", session.id[:8]
                )
        except Exception as exc:
            logger.warning("Message delivery failed: %s", exc)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist(self, result: "AgentResult", ctx: "AgentRunContext") -> None:
        try:
            async with self._db_ctx() as db:
                from app.models.db import AgentRun
                row = AgentRun(
                    agent_id    = result.agent_id,
                    device_id   = ctx.device_id,
                    ran_at      = time.time(),
                    success     = result.success,
                    title       = result.title[:128],
                    text_snippet = result.text[:512],
                    delivery    = json.dumps(result.delivery),
                    priority    = result.priority,
                    latency_ms  = result.latency_ms,
                    error       = result.error,
                    metadata_json = json.dumps(result.metadata),
                )
                db.add(row)
                await db.commit()
        except Exception as exc:
            logger.error("Failed to persist AgentRun: %s", exc)

    # ------------------------------------------------------------------
    # DB context
    # ------------------------------------------------------------------

    class _NullCtx:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): pass

    def _db_ctx(self):
        if self._db_factory:
            return self._db_factory()
        return self._NullCtx()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: Optional[AgentManager] = None

def get_agent_manager() -> AgentManager:
    global _manager
    if _manager is None:
        _manager = AgentManager()
    return _manager


# ---------------------------------------------------------------------------
# Bootstrap: create manager + scheduler + register all agents
# ---------------------------------------------------------------------------

def bootstrap_agents(db_factory) -> tuple[AgentManager, "AgentScheduler"]:
    """
    Called from main.py lifespan.
    Creates the manager and scheduler, registers all agents, wires up DB.
    """
    from app.services.agents.morning_agent import MorningAgent
    from app.services.agents.evening_agent import EveningAgent
    from app.services.agents.weekly_agent import WeeklyAgent
    from app.services.agents.productivity_agent import ProductivityAgent
    from app.services.agents.goal_agent import GoalAgent
    from app.services.agents.career_agent import CareerAgent
    from app.services.agents.scheduler import get_scheduler

    manager   = get_agent_manager()
    scheduler = get_scheduler()

    manager.set_db_factory(db_factory)
    scheduler.set_db_factory(db_factory)

    agents = [
        MorningAgent(),
        EveningAgent(),
        WeeklyAgent(),
        ProductivityAgent(),
        GoalAgent(),
        CareerAgent(),
    ]
    for agent in agents:
        manager.register(agent)
        scheduler.register(agent)

    logger.info("Agent system bootstrapped: %d agents registered", len(agents))
    return manager, scheduler
