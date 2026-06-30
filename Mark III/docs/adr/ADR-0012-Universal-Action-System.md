# ADR-0012 — Universal Action System Integration

**Status:** Accepted
**Date:** 2026-06-30
**Author:** Navid Shahriar Sami
**Supersedes:** ADR-0010 (Planned) — this ADR documents the as-built architecture

## Context

Phase 17 (Universal Actions) was planned as new development. During scoping, a
complete, unused action/policy/agent engine was discovered already in the
repository — Phase 12A/12B/13 scaffolding (`app/services/actions/`,
`app/services/policy/`, `app/services/agents/`) built for an async FastAPI
backend (`app/api/v1/`, `app/models/db.py` SQLAlchemy) that `mark_service.py`
never imported. Two parallel, undocumented architectures existed for the same
responsibility — the exact failure mode the Knowledge Governance System
(ADR-0011) exists to catch.

## Decision

Absorb the existing action engine into the live synchronous architecture rather
than build new or stand up the dormant FastAPI app.

1. **Thread bridge, not rewrite.** `action_loop.py` runs the unmodified async
   `AsyncActionQueue` on a dedicated background thread with its own event loop.
   The synchronous voice loop bridges in via `asyncio.run_coroutine_threadsafe`.
2. **Persistence swap.** `action_store.py` (plain `sqlite3`, mirroring
   `fact_store.py`) replaces `app.models.db.ActionRecord`. No ORM, no async DB
   session, anywhere in the live action pipeline.
3. **Context swap.** `policy_context.py` reads device state from the live mesh
   registry and user preferences from the live identity profile, replacing the
   dormant `presence_manager.py` and SQLAlchemy `UserContext`/`DailyReport` queries.
   Productivity-state rules degrade gracefully to `.unknown()` — there is no live
   equivalent of that tracking yet.
4. **Tiered Approval Framework.** CRITICAL-tier approvals are gated by a new
   `Capability.APPROVAL_AUTHORITY` mesh capability, not hardcoded device identity.
   Desktop is the only device carrying it today. MARK Mobile iOS registers the
   same capability when it ships — zero changes to the Policy Engine or Approval
   Manager required.
5. **Superseded, not deleted.** `app/api/v1/` and `app/models/db.py` remain in
   the repository with explicit superseded notices in their `__init__.py` files.
   They must not be wired into `mark_service.py` without a new ADR.
6. **Phase 13 deferred.** The proactive Agent System depends on the same dormant
   stack and `voice_daemon.py`. It was not absorbed — left dormant pending a
   dedicated phase.

## A Bug Caught By Integration Testing

`ApprovalManager.respond()` originally called `asyncio.Event.set()` directly.
Since voice approval responses arrive from the synchronous voice thread — not
the action loop's own thread — this silently failed to wake the waiting
coroutine. Every approval would have hung until the 120s timeout regardless of
the user's actual answer. Fixed by routing `.set()` through
`action_loop.schedule_threadsafe()`, which uses `loop.call_soon_threadsafe()`.
Caught only because the integration was tested end-to-end with a real
cross-thread approval flow, not just unit-tested in isolation.

## Consequences

- "Open Chrome," "delete X," "restart the computer" all execute today via voice
- SAFE-tier actions execute with zero added latency over the existing pipeline
- DANGEROUS/CRITICAL actions block on spoken approval, resolved by "yes"/"no"
- CRITICAL actions cannot be approved by a non-desktop device, by design
- The dormant FastAPI stack remains importable but inert; future sessions are
  warned via `__init__.py` docstrings before they could mistake it for live code
- Phase 13 Agent System integration is explicitly out of scope and undecided

---

[[action_system]] · [[device_mesh]] · [[cognitive_pipeline]] · [[ADR-0010-Universal-Actions]] · [[ADR-0011-Knowledge-Governance-System]] · [[ADR-0003-Device-Mesh]] · [[future]]
