"""
MARK III — Policy Engine (Phase 12A)

Evaluates an action request against all registered policy rules and
returns a PolicyDecision with verdict + human-readable reason.

Integration point:
    ActionRouter → PolicyEngine.evaluate() → verdict → Executor (or deny/defer)

Usage:
    from app.services.policy.policy_engine import get_policy_engine

    engine   = get_policy_engine()
    decision = await engine.evaluate(
        action_type  = "launch_app",
        safety_level = "safe",
        parameters   = {"app_name": "Spotify"},
        device_id    = device_id,
        source       = "voice",
        db           = db,
    )

    if decision.verdict == Verdict.ALLOW:
        await executor.run(...)
    elif decision.verdict == Verdict.DENY:
        return {"error": decision.reason}
    elif decision.verdict == Verdict.REQUIRE_APPROVAL:
        await approval_queue.create(action, decision)
    elif decision.verdict == Verdict.DEFER:
        await action_queue.defer_until(action, decision.defer_until_hour)

Design:
  - Single evaluator function, pure ordered rule list, first non-None wins
  - Fallback: no rule matched → ALLOW with audit note
  - All evaluations logged; caller may also inspect decision.to_dict()
  - Singleton via get_policy_engine() — zero-cost re-access
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.policy.policy_context import PolicyContext, build_policy_context
from app.services.policy.policy_rules import (
    PolicyDecision,
    Verdict,
    get_enabled_rules,
    disable_rule,
    enable_rule,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PolicyEngine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    Evaluates an action against all registered rules in priority order.

    Rules are loaded fresh from RULES_REGISTRY on every .evaluate() call
    so runtime enable/disable changes are picked up immediately.
    """

    def __init__(self) -> None:
        logger.info("Policy Engine initialized")

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        action_type:   str,
        safety_level:  str,
        parameters:    dict[str, Any],
        device_id:     str,
        source:        str              = "api",
        session_overrides: frozenset[str] | None = None,
        db=None,
    ) -> PolicyDecision:
        """
        Build a PolicyContext then evaluate rules in priority order.

        Returns the first non-None PolicyDecision from any rule.
        Falls back to ALLOW if no rule triggered.
        """
        ctx = await build_policy_context(
            action_type       = action_type,
            safety_level      = safety_level,
            parameters        = parameters,
            device_id         = device_id,
            source            = source,
            session_overrides = session_overrides,
            db                = db,
        )
        return self._run_rules(ctx)

    def evaluate_sync(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Evaluate rules against a pre-built PolicyContext (sync path).

        Use this when the caller has already built the context
        (e.g., from cached data) and wants the synchronous fast-path.
        """
        return self._run_rules(ctx)

    def _run_rules(self, ctx: PolicyContext) -> PolicyDecision:
        rules = get_enabled_rules()
        for reg in rules:
            try:
                decision = reg.fn(ctx)
            except Exception as exc:
                logger.warning("Policy rule '%s' raised an exception: %s", reg.name, exc)
                continue

            if decision is not None:
                self._audit(ctx, decision, reg.name)
                return decision

        # No rule matched — default allow
        default = PolicyDecision.allow(
            rule_name = "default_allow",
            reason    = "No policy rule blocked this action.",
        )
        self._audit(ctx, default, "default_allow")
        return default

    # ------------------------------------------------------------------
    # Batch evaluation (for queue pre-check)
    # ------------------------------------------------------------------

    async def evaluate_many(
        self,
        actions:   list[dict],
        device_id: str,
        source:    str = "api",
        db=None,
    ) -> list[PolicyDecision]:
        """
        Evaluate a list of proposed actions.  Each item must contain:
            { action_type, safety_level, parameters }
        Returns decisions in same order.
        """
        results = []
        for action in actions:
            decision = await self.evaluate(
                action_type  = action["action_type"],
                safety_level = action.get("safety_level", "safe"),
                parameters   = action.get("parameters", {}),
                device_id    = device_id,
                source       = source,
                db           = db,
            )
            results.append(decision)
        return results

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def disable(self, rule_name: str) -> bool:
        """Disable a rule at runtime (non-persistent, resets on restart)."""
        ok = disable_rule(rule_name)
        if ok:
            logger.info("Policy rule '%s' disabled", rule_name)
        return ok

    def enable(self, rule_name: str) -> bool:
        """Re-enable a previously disabled rule."""
        ok = enable_rule(rule_name)
        if ok:
            logger.info("Policy rule '%s' enabled", rule_name)
        return ok

    def list_rules(self) -> list[dict]:
        """Return current rule registry state (for /policy/rules API)."""
        from app.services.policy.policy_rules import RULES_REGISTRY
        return [
            {
                "name":     r.name,
                "category": r.category,
                "priority": r.priority,
                "enabled":  r.enabled,
            }
            for r in sorted(RULES_REGISTRY, key=lambda x: x.priority)
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _audit(ctx: PolicyContext, decision: PolicyDecision, rule_name: str) -> None:
        log = logger.debug if decision.verdict == Verdict.ALLOW else logger.info
        log(
            "POLICY [%s] %s → %s | rule=%s | %s",
            ctx.action_type,
            ctx.safety_level,
            decision.verdict.value,
            rule_name,
            decision.reason[:120],
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine


# ---------------------------------------------------------------------------
# Convenience wrapper (for callers that want a one-liner)
# ---------------------------------------------------------------------------

async def evaluate_action(
    action_type:   str,
    safety_level:  str,
    parameters:    dict[str, Any],
    device_id:     str,
    source:        str              = "api",
    session_overrides: frozenset[str] | None = None,
    db=None,
) -> PolicyDecision:
    """
    Module-level shortcut:

        from app.services.policy.policy_engine import evaluate_action, Verdict

        decision = await evaluate_action("launch_app", "safe", {...}, device_id, db=db)
        if decision.verdict != Verdict.ALLOW:
            ...
    """
    return await get_policy_engine().evaluate(
        action_type       = action_type,
        safety_level      = safety_level,
        parameters        = parameters,
        device_id         = device_id,
        source            = source,
        session_overrides = session_overrides,
        db                = db,
    )


# Re-export decision types so callers only need one import
__all__ = [
    "PolicyEngine",
    "get_policy_engine",
    "evaluate_action",
    "PolicyDecision",
    "Verdict",
]
