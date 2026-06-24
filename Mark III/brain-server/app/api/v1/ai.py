"""
MARK III — AI Reasoning API (Phase 9)

Endpoints:
  POST /api/v1/ai/ask              — free-form query to MARK III
  GET  /api/v1/ai/insights         — proactive AI-generated insights
  GET  /api/v1/ai/daily-brief      — morning/midday AI briefing
  GET  /api/v1/ai/evening-review   — end-of-day AI reflection
  GET  /api/v1/ai/weekly-review    — AI-powered weekly performance review
  GET  /api/v1/ai/provider-status  — health of all AI providers

All responses include:
  - text:       the AI output
  - cached:     True if served from cache
  - task_type:  what reasoning mode was used
  - provider:   which LLM provider was called
  - model:      exact model ID
  - cost_usd:   estimated inference cost
"""

import logging
import time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import ProviderUsage, ReasoningLog
from app.services.ai.provider_manager import get_provider_manager
from app.services.ai.reasoning_engine import (
    run_ask, run_daily_brief, run_evening_review,
    run_weekly_review, run_insights,
)

logger = logging.getLogger("markiii.ai.api")
router = APIRouter(prefix="/ai", tags=["ai"])


class AskRequest(BaseModel):
    device_id: str
    question:  str
    session_id: str = ""   # optional conversation session grouping


# ---------------------------------------------------------------------------
# POST /ai/ask
# ---------------------------------------------------------------------------

@router.post("/ask")
async def ask(body: AskRequest, db: AsyncSession = Depends(get_db)):
    """
    Route a free-form user query through MARK III's reasoning engine.
    MARK III classifies intent, selects the appropriate prompt + provider tier,
    and returns the response with full traceability.
    """
    logger.info("Ask  device=%s  q=%s", body.device_id[:16], body.question[:60])
    result = await run_ask(body.device_id, body.question, db)
    return result


# ---------------------------------------------------------------------------
# GET /ai/insights
# ---------------------------------------------------------------------------

@router.get("/insights")
async def get_insights(
    device_id: str  = Query(...),
    force:     bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate proactive insights from MARK III's full context.
    Cached for 10 minutes — pass ?force=true to regenerate immediately.
    """
    return await run_insights(device_id, db, force=force)


# ---------------------------------------------------------------------------
# GET /ai/daily-brief
# ---------------------------------------------------------------------------

@router.get("/daily-brief")
async def get_daily_brief(
    device_id: str  = Query(...),
    force:     bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a morning briefing: priorities, deadlines, one concrete action.
    Cached for 5 minutes.
    """
    return await run_daily_brief(device_id, db, force=force)


# ---------------------------------------------------------------------------
# GET /ai/evening-review
# ---------------------------------------------------------------------------

@router.get("/evening-review")
async def get_evening_review(
    device_id: str  = Query(...),
    force:     bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an end-of-day reflection: what went well, what to improve, one action.
    Cached for 10 minutes.
    """
    return await run_evening_review(device_id, db, force=force)


# ---------------------------------------------------------------------------
# GET /ai/weekly-review
# ---------------------------------------------------------------------------

@router.get("/weekly-review")
async def get_weekly_review(
    device_id: str  = Query(...),
    force:     bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a full weekly performance review with goal progress analysis.
    Cached for 15 minutes.
    """
    return await run_weekly_review(device_id, db, force=force)


# ---------------------------------------------------------------------------
# GET /ai/provider-status
# ---------------------------------------------------------------------------

@router.get("/provider-status")
async def get_provider_status(db: AsyncSession = Depends(get_db)):
    """
    Return health + usage stats for all registered AI providers.
    Includes 30-day cost totals from the provider_usage table.
    """
    mgr    = get_provider_manager()
    health = await mgr.health_all()

    # 30-day cost per provider from DB
    cutoff_30d = time.time() - 30 * 86400
    cost_rows  = (await db.execute(
        select(
            ProviderUsage.provider,
            func.sum(ProviderUsage.cost_usd).label("total_cost"),
            func.sum(ProviderUsage.input_tokens).label("total_input"),
            func.sum(ProviderUsage.output_tokens).label("total_output"),
            func.count().label("total_calls"),
        )
        .where(ProviderUsage.ts >= cutoff_30d)
        .group_by(ProviderUsage.provider)
    )).all()

    usage_30d = {row.provider: {
        "cost_usd_30d":     round(row.total_cost or 0, 6),
        "tokens_in_30d":    row.total_input or 0,
        "tokens_out_30d":   row.total_output or 0,
        "calls_30d":        row.total_calls or 0,
    } for row in cost_rows}

    # Merge health + usage
    for name, h in health.items():
        h["usage_30d"] = usage_30d.get(name, {
            "cost_usd_30d": 0, "tokens_in_30d": 0,
            "tokens_out_30d": 0, "calls_30d": 0,
        })

    # All-time totals
    total_cost = (await db.execute(
        select(func.sum(ProviderUsage.cost_usd))
    )).scalar_one_or_none() or 0.0

    total_calls = (await db.execute(
        select(func.count()).select_from(ReasoningLog)
    )).scalar_one() or 0

    return {
        "preferred_provider": __import__("app.config", fromlist=["settings"]).settings.ai_preferred_provider,
        "providers":          health,
        "totals": {
            "cost_usd_all_time": round(total_cost, 6),
            "calls_all_time":    total_calls,
        },
    }
