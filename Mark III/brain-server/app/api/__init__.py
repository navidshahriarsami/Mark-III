"""
MARK III — app/api/ — SUPERSEDED, not run by mark_service.py

This FastAPI route tree (app/api/v1/*.py) and its SQLAlchemy models
(app/models/db.py) were original Phase 12/13 scaffolding for an async
backend. mark_service.py — the actual running entry point — never
imported this package.

Phase 17 (Universal Action System) absorbed the underlying action engine
(action_queue.py, policy_engine.py, executors/) into the live synchronous
architecture instead of standing up this FastAPI app. See ADR-0012.

These files are kept for reference and are not deleted, but should not
be wired into mark_service.py without a new ADR revisiting this decision.
"""
