"""
MARK III Brain Server — Async Database Engine

DATABASE_URL examples:
  SQLite  (local dev):   sqlite+aiosqlite:///./markiii.db
  Postgres (production): postgresql+asyncpg://user:pass@localhost:5432/markiii

All route handlers receive an AsyncSession via FastAPI's Depends(get_db).
Never import the engine directly in route code — always go through get_db.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ---------------------------------------------------------------------------
# Engine — connect_args only needed for SQLite
# ---------------------------------------------------------------------------

_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_async_engine(
    settings.database_url,
    echo=False,           # set True to see raw SQL in logs
    pool_pre_ping=True,   # discard stale connections before use
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Base class for all ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Table creation helper — called from lifespan on startup
# ---------------------------------------------------------------------------

async def create_all_tables() -> None:
    """Create all tables that don't already exist. Safe to call every boot."""
    async with engine.begin() as conn:
        from app.models import db as _db_models   # noqa: F401 — registers metadata
        await conn.run_sync(Base.metadata.create_all)
