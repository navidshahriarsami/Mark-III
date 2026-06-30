# MARK III — Universal Action System

**Phase:** 17 | **Status:** Live | **Version:** 0.20.0

MARK can act on the world, not just talk about it. "Open Chrome," "delete report.pdf,"
"restart the computer" all flow through a single pipeline: classify → evaluate policy →
execute → speak the result.

---

## Origin

The action engine (types, registry, regex router, async queue, policy engine, 4
executors) was originally built as Phase 12A/12B/13 scaffolding for a dormant async
FastAPI backend (`app/api/v1/`, `app/models/db.py`) that `mark_service.py` never ran.
Phase 17 absorbed the engine into the live synchronous architecture instead of
standing up the FastAPI app. See [ADR-0012](../adr/ADR-0012-Universal-Action-System.md).

---

## Pipeline

```
Voice utterance
    ↓
action_router.classify_intent(text, device_id)   ← pure regex, <1ms, no I/O
    ↓ (ActionRequest, or None → falls through to normal query pipeline)
action_loop.submit_action_sync(request)          ← thread-safe bridge into the
    ↓                                                background asyncio loop
AsyncActionQueue.submit()
    ↓
policy_engine.evaluate_action()                  ← rule-based verdict
    ↓
   ALLOW ──────────► executor.run(action) ──► ActionResult
   DENY ───────────► FAILED (reason recorded)
   DEFER ──────────► re-queued at a later time
   REQUIRE_APPROVAL ► approval_manager creates a pending approval,
                       prompt is spoken as the IMMEDIATE response,
                       queue worker blocks (up to 120s) for resolution
    ↓
action_store.upsert()                            ← SQLite persistence
```

## Safety Tiers

| Tier | Examples | Approval |
|---|---|---|
| SAFE | launch/close/focus app, open URL, web search, search/read/open files | None — auto-execute |
| CAUTION | notification, create/copy/move file, browser click/fill, clipboard | Configurable (user preference) |
| DANGEROUS | delete file, run command, install software, kill process, rename | Always — any device that triggered it may resolve |
| CRITICAL | shutdown, restart, format drive, modify registry | Always — **only a device with `approval_authority` capability** |

## Tiered Approval Framework

CRITICAL-tier approvals are capability-gated, not device-hardcoded. The mesh
`Capability.APPROVAL_AUTHORITY` flag determines who may resolve them.

```python
# mesh_manager.py — Desktop self-registration
_DESKTOP_CAPABILITIES = [..., Capability.APPROVAL_AUTHORITY.value]
```

Today only the Desktop carries this capability. When MARK Mobile iOS ships, it
registers the same capability and becomes a trusted approver — **zero changes**
to the Policy Engine, the Action Queue, or the Approval Manager are required.

`approval_manager.handle_voice_response()` checks this capability before resolving
any CRITICAL-tier approval; an utterance from an untrusted device is logged and
ignored rather than silently denied or approved.

## Thread Model

The action engine is internally async (asyncio.Queue, Semaphore, Event — needed
for concurrent execution, retries, and approval waits). Rather than rewriting that
machinery synchronously, `action_loop.py` runs ONE dedicated background thread with
its own event loop, hosting `AsyncActionQueue`. The synchronous voice loop
(`always_listening_loop.py`) bridges into it via `asyncio.run_coroutine_threadsafe`.

**Critical gotcha (caught during integration testing):** `asyncio.Event.set()` is
not safe to call directly from a thread other than the one running its owning event
loop — the waiting coroutine may never wake. `approval_manager.respond()` schedules
the `.set()` call via `action_loop.schedule_threadsafe()` instead of calling it
directly, since voice approval responses arrive from the synchronous voice thread.

## Persistence

`action_store.py` — plain `sqlite3`, same pattern as `fact_store.py`. Replaced the
original `app.models.db.ActionRecord` (SQLAlchemy) dependency entirely; no DB session
or ORM is required anywhere in the live action pipeline.

## Policy Context

`policy_context.py` reads device state from the live mesh registry
(`mesh_manager.get_online_devices()`) and user preferences from the live identity
profile (`identity_manager.get_profile()`) — replacing the dormant `presence_manager.py`
and SQLAlchemy `UserContext`/`DailyReport`/`UserProfile` queries.

Productivity-state rules (focus blocks, meeting detection) default to
`ProductivityContext.unknown()` — there is no live equivalent of the dormant
activity-tracking tables yet. All productivity-gated rules already handle this
gracefully (they simply don't fire).

## Out of Scope (Phase 17)

The Phase 13 proactive Agent System (`app/services/agents/` — morning/evening/weekly/
productivity/goal/career agents, scheduler, 3-channel delivery) depends on the same
dormant SQLAlchemy stack and `voice_daemon.py`. It was **not** absorbed in this phase —
it remains dormant pending a dedicated phase to decide its integration path.

---

[[device_mesh]] · [[cognitive_pipeline]] · [[memory_architecture]] · [[ADR-0012-Universal-Action-System]] · [[ADR-0010-Universal-Actions]] · [[ADR-0003-Device-Mesh]] · [[future]]
