"""
MARK III — Action Queue (Phase 12B)

AsyncActionQueue: submits, schedules, and executes actions.

Worker pipeline per action:
  1. Validate params  (registry schema check)
  2. Policy check     (PolicyEngine.evaluate → ALLOW|DENY|REQUIRE_APPROVAL|DEFER)
  3. If DENY          → mark FAILED, return
  4. If REQUIRE_APPROVAL → create ApprovalRecord, wait, then continue or deny
  5. If DEFER         → re-queue at defer_until timestamp
  6. If ALLOW         → get executor (registry), run with timeout
  7. Persist result to DB (Action row)

The queue runs a background asyncio Task (start/stop with lifecycle).
Up to MAX_CONCURRENT actions execute simultaneously.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from app.services.actions.base_action import Action, ActionRequest, ActionResult, ActionState
from app.services.actions.action_registry import lookup_required, validate_params, get_executor
from app.services.actions.approval_manager import get_approval_manager, APPROVAL_TIMEOUT_SECONDS
from app.services.policy.policy_engine import evaluate_action
from app.services.policy.policy_rules import Verdict

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 4
_DEFER_RETRY_INTERVAL = 10.0   # seconds between defer re-check polls


class AsyncActionQueue:
    """
    Singleton background queue.  Start with .start(), stop with .stop().
    """

    def __init__(self) -> None:
        self._queue:    asyncio.Queue[Action]         = asyncio.Queue()
        self._deferred: list[tuple[float, Action]]    = []   # (run_after_ts, action)
        self._active:   dict[str, Action]             = {}   # action_id → Action
        self._results:  dict[str, Action]             = {}   # recent completed/failed
        self._sem:      asyncio.Semaphore             = asyncio.Semaphore(MAX_CONCURRENT)
        self._worker_task:  Optional[asyncio.Task]    = None
        self._defer_task:   Optional[asyncio.Task]    = None
        self._db_factory    = None   # injected by main.py via set_db_factory()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker_loop(), name="action-queue-worker")
        self._defer_task  = asyncio.create_task(self._defer_loop(),  name="action-queue-defer")
        logger.info("Action Queue started (max_concurrent=%d)", MAX_CONCURRENT)

    async def stop(self) -> None:
        for task in (self._worker_task, self._defer_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("Action Queue stopped")

    def set_db_factory(self, factory) -> None:
        """Inject the async DB session factory from main.py lifespan."""
        self._db_factory = factory

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def submit(
        self,
        request: ActionRequest,
        session_overrides: Optional[frozenset] = None,
    ) -> Action:
        """
        Validate, build an Action, enqueue it, and return immediately.

        Raises ValueError if action_type is unknown or required params missing.
        """
        entry = lookup_required(request.action_type)   # raises KeyError if unknown
        missing = validate_params(request.action_type, request.parameters)
        if missing:
            raise ValueError(f"Missing required parameters for '{request.action_type}': {missing}")

        action = Action.create(
            request        = request,
            safety_level   = entry.safety_level.value,
            timeout_seconds = entry.timeout,
            max_retries    = entry.max_retries,
        )
        action._session_overrides = session_overrides   # pass through to policy eval

        self._active[action.id] = action
        await self._queue.put(action)
        logger.info(
            "Action submitted: %s [%s/%s] src=%s",
            action.id[:8], action.action_type, action.safety_level, action.source,
        )
        return action

    # ------------------------------------------------------------------
    # Status queries
    # ------------------------------------------------------------------

    def get_action(self, action_id: str) -> Optional[Action]:
        return self._active.get(action_id) or self._results.get(action_id)

    def list_active(self) -> list[Action]:
        return list(self._active.values())

    def list_recent(self, limit: int = 20) -> list[Action]:
        return sorted(self._results.values(), key=lambda a: a.updated_at, reverse=True)[:limit]

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    async def cancel(self, action_id: str) -> bool:
        action = self._active.get(action_id)
        if not action:
            return False
        if action.state in (ActionState.RUNNING.value,):
            # Running actions can't be cancelled mid-executor (no cancellation token yet)
            return False
        action.transition(ActionState.CANCELLED)
        self._move_to_results(action)
        await self._persist(action)
        logger.info("Action %s cancelled", action_id[:8])
        return True

    # ------------------------------------------------------------------
    # Main worker loop
    # ------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        while True:
            try:
                action = await self._queue.get()
                asyncio.create_task(self._process(action))
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Worker loop error: %s", exc)

    async def _process(self, action: Action) -> None:
        async with self._sem:
            await self._run_pipeline(action)

    async def _run_pipeline(self, action: Action) -> None:
        overrides = getattr(action, "_session_overrides", None)

        # ── 1. Policy evaluation ────────────────────────────────────────
        try:
            async with self._db_ctx() as db:
                decision = await evaluate_action(
                    action_type       = action.action_type,
                    safety_level      = action.safety_level,
                    parameters        = action.parameters,
                    device_id         = action.device_id,
                    source            = action.source,
                    session_overrides = overrides,
                    db                = db,
                )
        except Exception as exc:
            logger.error("Policy evaluation failed for %s: %s", action.id[:8], exc)
            decision = None   # fail open — continue (policy errors should not block safe actions)

        verdict = decision.verdict if decision else Verdict.ALLOW

        # ── 2. DENY ─────────────────────────────────────────────────────
        if verdict == Verdict.DENY:
            action.error_message = decision.reason if decision else "Policy denied"
            action.transition(ActionState.FAILED)
            self._move_to_results(action)
            await self._persist(action)
            logger.info("Action %s DENIED: %s", action.id[:8], action.error_message)
            return

        # ── 3. DEFER ────────────────────────────────────────────────────
        if verdict == Verdict.DEFER:
            delay = (decision.defer_seconds or 3600.0) if decision else 3600.0
            run_after = time.time() + delay
            if decision and decision.defer_until_hour is not None:
                from datetime import datetime, timedelta
                now = datetime.now()
                target = now.replace(
                    hour=decision.defer_until_hour, minute=0, second=0, microsecond=0
                )
                if target <= now:
                    target += timedelta(days=1)
                run_after = target.timestamp()

            action.deferred_until = run_after
            action.transition(ActionState.DEFERRED)
            self._deferred.append((run_after, action))
            await self._persist(action)
            logger.info(
                "Action %s DEFERRED until %.0f (%s)",
                action.id[:8], run_after,
                decision.reason if decision else "policy",
            )
            return

        # ── 4. REQUIRE_APPROVAL ─────────────────────────────────────────
        if verdict == Verdict.REQUIRE_APPROVAL:
            action.transition(ActionState.AWAITING_APPROVAL)
            approval_mgr = get_approval_manager()
            approval = approval_mgr.create_approval(
                action_id    = action.id,
                device_id    = action.device_id,
                action_type  = action.action_type,
                parameters   = action.parameters,
                safety_level = action.safety_level,
            )
            action.approval_id = approval.approval_id
            await self._persist(action)

            # Notify via TTS if voice session active
            await self._voice_notify(action.device_id, approval.prompt)

            # Block until user responds or timeout
            user_verdict = await approval_mgr.wait_for_response(
                approval.approval_id, APPROVAL_TIMEOUT_SECONDS
            )
            if user_verdict != "approved":
                reason = f"Action denied by user (verdict: {user_verdict})"
                action.error_message = reason
                action.transition(ActionState.FAILED)
                self._move_to_results(action)
                await self._persist(action)
                logger.info("Action %s approval DENIED", action.id[:8])
                return
            logger.info("Action %s approval GRANTED", action.id[:8])

        # ── 5. Execute ──────────────────────────────────────────────────
        entry    = lookup_required(action.action_type)
        executor = get_executor(entry.executor_key)
        action.transition(ActionState.RUNNING)
        await self._persist(action)

        try:
            result: ActionResult = await asyncio.wait_for(
                executor.run(action),
                timeout=action.timeout_seconds,
            )
        except asyncio.TimeoutError:
            result = ActionResult(
                success=False, error=f"Action timed out after {action.timeout_seconds}s"
            )
        except Exception as exc:
            result = ActionResult(success=False, error=str(exc))

        action.result = result

        if result.success:
            action.transition(ActionState.COMPLETED)
        else:
            if action.retry_count < action.max_retries:
                action.retry_count += 1
                action.transition(ActionState.PENDING)
                await self._queue.put(action)
                logger.info("Action %s retrying (%d/%d)", action.id[:8], action.retry_count, action.max_retries)
                return
            action.error_message = result.error
            action.transition(ActionState.FAILED)

        self._move_to_results(action)
        await self._persist(action)
        logger.info(
            "Action %s → %s (%.0fms)",
            action.id[:8], action.state,
            result.latency_ms,
        )

    # ------------------------------------------------------------------
    # Defer loop: re-queue deferred actions when their time comes
    # ------------------------------------------------------------------

    async def _defer_loop(self) -> None:
        while True:
            try:
                now      = time.time()
                ready    = [(ts, a) for ts, a in self._deferred if ts <= now]
                remaining = [(ts, a) for ts, a in self._deferred if ts > now]
                self._deferred = remaining
                for _, action in ready:
                    action.transition(ActionState.PENDING)
                    self._active[action.id] = action
                    await self._queue.put(action)
                    logger.info("Action %s re-queued from defer", action.id[:8])
                await asyncio.sleep(_DEFER_RETRY_INTERVAL)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Defer loop error: %s", exc)
                await asyncio.sleep(_DEFER_RETRY_INTERVAL)

    # ------------------------------------------------------------------
    # Voice notification helper
    # ------------------------------------------------------------------

    async def _voice_notify(self, device_id: str, prompt: str) -> None:
        """Speak the approval prompt if a voice session is active for this device."""
        try:
            from app.services.voice.voice_daemon import get_voice_daemon
            daemon = get_voice_daemon()
            if daemon.is_active_for(device_id):
                await daemon.speak(device_id, prompt)
        except Exception as exc:
            logger.debug("Voice notify for approval failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------

    async def _persist(self, action: Action) -> None:
        if not self._db_factory:
            return
        try:
            async with self._db_factory() as db:
                await self._upsert_action(db, action)
                await db.commit()
        except Exception as exc:
            logger.error("Failed to persist action %s: %s", action.id[:8], exc)

    async def _upsert_action(self, db, action: Action) -> None:
        from sqlalchemy import select
        from app.models.db import ActionRecord

        result_json   = json.dumps(action.result.to_dict()) if action.result else None
        params_json   = action.params_to_json(action.parameters)

        existing = (await db.execute(
            select(ActionRecord).where(ActionRecord.id == action.id)
        )).scalar_one_or_none()

        if existing:
            existing.state          = action.state
            existing.updated_at     = action.updated_at
            existing.started_at     = action.started_at
            existing.completed_at   = action.completed_at
            existing.result_json    = result_json
            existing.error_message  = action.error_message
            existing.retry_count    = action.retry_count
            existing.approval_id    = action.approval_id
            existing.deferred_until = action.deferred_until
        else:
            db.add(ActionRecord(
                id              = action.id,
                action_type     = action.action_type,
                safety_level    = action.safety_level,
                parameters_json = params_json,
                state           = action.state,
                source          = action.source,
                device_id       = action.device_id,
                session_id      = action.session_id,
                context_hint    = action.context_hint[:200] if action.context_hint else "",
                result_json     = result_json,
                error_message   = action.error_message,
                retry_count     = action.retry_count,
                max_retries     = action.max_retries,
                timeout_seconds = action.timeout_seconds,
                approval_id     = action.approval_id,
                deferred_until  = action.deferred_until,
                created_at      = action.created_at,
                updated_at      = action.updated_at,
                started_at      = action.started_at,
                completed_at    = action.completed_at,
            ))

    # ------------------------------------------------------------------
    # DB context helper
    # ------------------------------------------------------------------

    class _NullCtx:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): pass

    def _db_ctx(self):
        if self._db_factory:
            return self._db_factory()
        return self._NullCtx()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _move_to_results(self, action: Action) -> None:
        self._active.pop(action.id, None)
        self._results[action.id] = action
        # Trim results cache
        if len(self._results) > 500:
            oldest_id = min(self._results, key=lambda k: self._results[k].updated_at)
            self._results.pop(oldest_id, None)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_queue: Optional[AsyncActionQueue] = None

def get_action_queue() -> AsyncActionQueue:
    global _queue
    if _queue is None:
        _queue = AsyncActionQueue()
    return _queue
