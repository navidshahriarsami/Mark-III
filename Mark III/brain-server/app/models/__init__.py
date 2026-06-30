"""
MARK III — app/models/ — SUPERSEDED, not run by mark_service.py

SQLAlchemy ORM models (db.py) written for the dormant FastAPI backend
(app/api/v1/). The live architecture persists state with plain sqlite3
instead — see app/services/memory/fact_store.py and
app/services/actions/action_store.py for the pattern in active use.

See ADR-0012 (Universal Action System) for why this was not adopted.
"""
