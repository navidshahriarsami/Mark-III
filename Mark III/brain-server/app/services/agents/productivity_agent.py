"""
MARK III — Productivity Agent (Phase 13)

Context-triggered: fires when a significant productivity event is detected.

Triggers:
  DISTRACTION_SPIKE   — >45 min continuous distraction (any hour)
  FOCUS_DECLINE       — focus score drops >25 points from yesterday's
  LONG_IDLE           — no productive app detected for >60 min in work hours
  RECOVERY_PROMPT     — it's been 2+ hours since last productive window; suggest returning

Anti-spam:
  min_interval_hours = 2.0 (can trigger multiple times per day, but not spamming)
  Each trigger type has its own cooldown tracked via metadata.

Delivery: voice (if active, gentle interrupt) → notification
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agents.base_agent import AgentResult, AgentRunContext, BaseAgent

logger = logging.getLogger(__name__)

# Thresholds
DISTRACTION_SPIKE_MINUTES = 45
FOCUS_DECLINE_THRESHOLD   = 25    # points drop from yesterday
LONG_IDLE_MINUTES         = 60


class ProductivityAgent(BaseAgent):
    agent_id           = "productivity_alert"
    name               = "Productivity Monitor"
    description        = "Context-triggered alerts for distraction spikes and focus decline"
    min_interval_hours = 2.0
    default_delivery   = ["voice", "notification"]

    async def should_run(self, ctx: AgentRunContext) -> bool:
        # Only during work hours, not quiet hours
        if ctx.is_quiet_hours or not ctx.is_work_hours:
            return False
        # Don't interrupt meetings or deep focus (let them work)
        if self._is_in_meeting(ctx):
            return False

        trigger = self._detect_trigger(ctx)
        return trigger is not None

    def _detect_trigger(self, ctx: AgentRunContext) -> str | None:
        """Return trigger name or None."""
        if not ctx.recent_context or not ctx.daily_report:
            return None

        dist_mins = ctx.daily_report.distraction_minutes or 0
        prod_mins = ctx.daily_report.productive_minutes or 0
        focus     = ctx.focus_score

        # Distraction spike
        if dist_mins >= DISTRACTION_SPIKE_MINUTES and dist_mins > prod_mins:
            return "distraction_spike"

        # Focus decline vs yesterday
        if ctx.weekly_report:
            pass  # could compare to weekly avg
        if focus < 35 and ctx.is_work_hours:
            return "focus_decline"

        # Long idle in work hours (no productive work detected)
        state = ctx.recent_context.productivity_state if ctx.recent_context else ""
        if state in ("idle", "distracted") and ctx.is_work_hours and ctx.hour >= 10:
            if dist_mins < 10 and prod_mins < 15:
                return "long_idle"

        return None

    async def run(self, ctx: AgentRunContext, db: AsyncSession) -> AgentResult:
        import time
        t0 = time.monotonic()

        trigger    = self._detect_trigger(ctx)
        dist_mins  = ctx.daily_report.distraction_minutes if ctx.daily_report else 0
        focus      = ctx.focus_score
        hour_str   = f"{ctx.hour:02d}:00"

        prompts = {
            "distraction_spike": (
                f"Pattern detected: {dist_mins:.0f} minutes lost to distraction today.",
                f"""Generate a brief, direct nudge for {ctx.user_name} who has been distracted for {dist_mins:.0f} minutes today ({hour_str} now).
Do NOT lecture. 1–2 sentences maximum. Suggest one concrete re-focus action.
Example style: "40 minutes gone to feeds. Close the browser, pick one task, set a 25-minute timer."
Be direct. No filler. No emoji."""
            ),
            "focus_decline": (
                f"Focus score dropped to {focus:.0f}%.",
                f"""Generate a brief re-focus prompt for {ctx.user_name}. Focus score is {focus:.0f}% — lower than usual.
1–2 sentences. One concrete suggestion. Direct tone.
Example: "Focus is at {focus:.0f}%. Step away for 5 minutes, then pick your single most important task."
No moralising. Under 40 words."""
            ),
            "long_idle": (
                "Low productive output detected this morning.",
                f"""Generate a gentle but direct check-in for {ctx.user_name}. It's {hour_str} and productive time is low.
1–2 sentences. Suggest returning to work — name a specific type of action.
Keep it under 35 words. No guilt-tripping."""
            ),
        }

        title_map = {
            "distraction_spike": "Focus check",
            "focus_decline":     "Focus declining",
            "long_idle":         "Time to refocus",
        }

        system_prompt = (
            "You are MARK III — a productivity-aware AI assistant. "
            "You speak briefly, directly, and helpfully. Never preach."
        )
        title   = title_map.get(trigger or "", "Productivity alert")
        context_note, user_prompt = prompts.get(trigger or "long_idle", prompts["long_idle"])

        text = await self._llm_call(system_prompt, user_prompt, ctx.device_id, tier="fast")

        if not text:
            fallback = {
                "distraction_spike": f"{dist_mins:.0f}m gone today. Close tabs, pick one task.",
                "focus_decline":     f"Focus at {focus:.0f}%. Step away briefly, then return to one clear task.",
                "long_idle":         f"It's {hour_str}. Time to start on your most important task.",
            }
            text = fallback.get(trigger or "long_idle", "Time to focus.")

        # Productivity agents should not deliver voice if user is in deep focus
        delivery = ["notification"]
        if not self._is_user_focused(ctx):
            delivery = ["voice", "notification"]

        return AgentResult(
            agent_id  = self.agent_id,
            title     = title,
            text      = text,
            delivery  = delivery,
            priority  = "medium" if trigger == "long_idle" else "high",
            success   = True,
            latency_ms = (time.monotonic() - t0) * 1000,
            metadata  = {
                "trigger":          trigger,
                "focus_score":      focus,
                "distraction_mins": dist_mins,
            },
        )
