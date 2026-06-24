"""
MARK III — Agent Base (Phase 13)

All agents inherit from BaseAgent.  The framework guarantees:
  - AgentRunContext is pre-loaded with all DB data needed (single round-trip)
  - Anti-spam: last_ran is checked before should_run() is called
  - Quiet hours: delivery is suppressed during quiet hours
  - LLM access: _llm_call() helper wraps the multi-turn provider system

Agent contract:
  should_run(ctx) → bool    — pure, fast, no I/O (ctx already loaded)
  run(ctx, db)    → AgentResult — can do additional DB reads + LLM call

Delivery channels (set in AgentResult.delivery):
  "voice"        — speak via VoiceDaemon if device has active voice session
  "notification" — OS toast / push notification
  "message"      — insert into user's active conversation as assistant turn
  "none"         — log only, no delivery (used in quiet hours fallback)
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AgentRunContext — snapshot of everything an agent needs
# ---------------------------------------------------------------------------

@dataclass
class AgentRunContext:
    """
    Pre-loaded snapshot of all state an agent may need.
    Built once per device per scheduler tick.  Agents must not do additional
    DB reads in should_run() (but may in run()).
    """
    device_id:      str
    ts:             float       # unix timestamp when context was built

    # User data
    profile:        Optional[Any]   # UserProfile row | None
    goals:          list[Any]       # LongTermGoal rows
    projects:       list[Any]       # Project rows
    memories:       list[Any]       # Memory rows (high-importance)
    recent_context: Optional[Any]   # Latest UserContext row | None
    daily_report:   Optional[Any]   # Today's DailyReport | None
    weekly_report:  Optional[Any]   # Most recent WeeklyReport | None

    # Preferences
    preferences:    Any             # UserPreferences dataclass

    # Derived convenience
    user_name:      str             = "there"
    hour:           int             = 0
    weekday:        int             = 0     # 0=Mon … 6=Sun
    is_weekend:     bool            = False
    is_work_hours:  bool            = False
    is_quiet_hours: bool            = False
    focus_score:    float           = 0.0
    distraction_minutes: float      = 0.0
    productive_minutes:  float      = 0.0


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    agent_id:   str
    title:      str
    text:       str
    delivery:   list[str]       = field(default_factory=lambda: ["notification"])
    priority:   str             = "medium"  # low | medium | high | urgent
    success:    bool            = True
    error:      Optional[str]   = None
    latency_ms: float           = 0.0
    metadata:   dict[str, Any]  = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_id":   self.agent_id,
            "title":      self.title,
            "text":       self.text[:500],
            "delivery":   self.delivery,
            "priority":   self.priority,
            "success":    self.success,
            "error":      self.error,
            "latency_ms": round(self.latency_ms, 1),
        }


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """
    Abstract base for all MARK III agents.

    Subclasses set class attributes:
        agent_id:           str  — unique snake_case identifier
        name:               str  — human-readable display name
        description:        str  — what the agent does
        min_interval_hours: float — minimum hours between runs (anti-spam)
        default_delivery:   list  — default channels if not overridden per run
    """

    agent_id:           str
    name:               str
    description:        str
    min_interval_hours: float       = 12.0
    default_delivery:   list[str]   = field(default_factory=lambda: ["notification"])

    @abstractmethod
    async def should_run(self, ctx: AgentRunContext) -> bool:
        """
        Return True if this agent should run now given ctx.

        Must be fast and pure — ctx is already loaded, no I/O allowed here.
        The scheduler calls this after checking min_interval.
        """
        ...

    @abstractmethod
    async def run(self, ctx: AgentRunContext, db: AsyncSession) -> AgentResult:
        """
        Execute the agent.  May do additional DB reads and LLM calls.
        Must return an AgentResult regardless of success/failure.
        """
        ...

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------

    async def _llm_call(
        self,
        system_prompt: str,
        user_prompt:   str,
        device_id:     str,
        tier:          str = "fast",   # "fast" | "deep"
    ) -> str:
        """
        Call the configured LLM provider.  Returns text or empty string on error.
        Uses the same provider abstraction as conversation_engine.
        """
        from app.services.ai.provider_manager import get_provider_manager
        from app.services.ai.base_provider import GenerateRequest, TaskTier, ProviderName
        from app.config import settings

        t0  = time.monotonic()
        mgr = get_provider_manager()

        task_tier    = TaskTier.DEEP if tier == "deep" else TaskTier.FAST
        preferred    = ProviderName(settings.ai_preferred_provider)
        order        = [preferred] + [n for n in [ProviderName.CLAUDE, ProviderName.OPENAI, ProviderName.LOCAL]
                                      if n != preferred]

        model_map = {
            "fast": {
                ProviderName.CLAUDE: "claude-haiku-4-5-20251001",
                ProviderName.OPENAI: "gpt-4o-mini",
                ProviderName.LOCAL:  settings.local_fast_model,
            },
            "deep": {
                ProviderName.CLAUDE: "claude-sonnet-4-6",
                ProviderName.OPENAI: "gpt-4o",
                ProviderName.LOCAL:  settings.local_deep_model,
            },
        }

        messages = [
            {"role": "user", "content": user_prompt}
        ]

        for provider_name in order:
            provider = mgr.get_provider(provider_name)
            if not provider:
                continue
            model = model_map.get(tier, model_map["fast"]).get(provider_name, "")
            try:
                if provider_name == ProviderName.CLAUDE:
                    import anthropic
                    client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)
                    resp = await client.messages.create(
                        model=model, max_tokens=1024,
                        system=system_prompt,
                        messages=messages,
                    )
                    text = resp.content[0].text if resp.content else ""
                elif provider_name == ProviderName.OPENAI:
                    import openai
                    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "system", "content": system_prompt}] + messages,
                        max_tokens=1024,
                    )
                    text = resp.choices[0].message.content or ""
                else:
                    req = GenerateRequest(
                        system=system_prompt,
                        user=user_prompt,
                        tier=task_tier,
                        device_id=device_id,
                    )
                    result = await provider.generate_async(req)
                    text = result.text or ""

                ms = (time.monotonic() - t0) * 1000
                logger.debug("%s LLM call %.0fms provider=%s", self.agent_id, ms, provider_name.value)
                return text.strip()

            except Exception as exc:
                logger.warning("%s LLM call failed (%s): %s", self.agent_id, provider_name.value, exc)
                continue

        return ""

    # ------------------------------------------------------------------
    # Guard helpers
    # ------------------------------------------------------------------

    def _in_quiet_hours(self, ctx: AgentRunContext) -> bool:
        return ctx.is_quiet_hours

    def _is_user_focused(self, ctx: AgentRunContext) -> bool:
        """True if user is in deep focus — don't interrupt."""
        if not ctx.recent_context:
            return False
        return (
            ctx.recent_context.productivity_state == "focused"
            and ctx.focus_score > 75
        )

    def _is_in_meeting(self, ctx: AgentRunContext) -> bool:
        if not ctx.recent_context:
            return False
        meeting_apps = {"zoom", "teams", "meet", "webex", "skype"}
        return any(m in (ctx.recent_context.dominant_app or "").lower() for m in meeting_apps)

    def _upcoming_deadlines(self, ctx: AgentRunContext, days: int = 7) -> list:
        """Return goals with target_date within `days` days."""
        from datetime import datetime, timedelta
        cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        today  = datetime.now().strftime("%Y-%m-%d")
        return [
            g for g in ctx.goals
            if g.target_date and today <= g.target_date <= cutoff and g.status == "active"
        ]

    def _at_risk_projects(self, ctx: AgentRunContext) -> list:
        """Return projects that are active but stalled (progress < 30%, status active)."""
        return [
            p for p in ctx.projects
            if p.status == "active" and (p.progress or 0) < 30
        ]
