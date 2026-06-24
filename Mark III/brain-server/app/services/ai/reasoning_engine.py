"""
MARK III — Reasoning Engine

Assembles the full user context from the database, routes it to the
appropriate prompt template and AI provider, caches expensive results,
and persists every interaction to AIInsight + ReasoningLog.

MARK III controls the context. LLMs provide reasoning on demand.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import (
    UserProfile, LongTermGoal, Project, Memory,
    UserContext, DailyReport, WeeklyReport,
    AIInsight, ReasoningLog, ProviderUsage,
)
from app.services.report_engine import generate_daily_report, generate_weekly_report
from .base_provider import GenerateRequest, GenerateResponse, TaskTier
from .provider_manager import get_provider_manager
from .task_router import TaskType, route, needs_llm
from . import prompts

logger = logging.getLogger("markiii.ai.reasoning")

# Cache TTLs
_CACHE_BRIEF_S   = 300     # daily brief: 5 min
_CACHE_EVENING_S = 600     # evening review: 10 min
_CACHE_WEEKLY_S  = 900     # weekly review: 15 min
_CACHE_INSIGHT_S = 600     # general insights: 10 min


async def _load_context(device_id: str, db: AsyncSession) -> dict:
    """
    Build the full context dict that prompt templates consume.
    Pulls from DB: profile, goals, projects, memories, live context,
    daily report, weekly report.
    """
    # Profile
    prow = (await db.execute(
        select(UserProfile).where(UserProfile.device_id == device_id)
    )).scalar_one_or_none()
    profile = {
        "name":                prow.name if prow else None,
        "career":              prow.career if prow else None,
        "interests":           (prow.interests or []) if prow else [],
        "learning_objectives": (prow.learning_objectives or []) if prow else [],
        "goals_summary":       prow.goals_summary if prow else None,
    }

    # Active goals
    goals_rows = (await db.execute(
        select(LongTermGoal)
        .where(LongTermGoal.device_id == device_id)
        .where(LongTermGoal.status == "active")
        .order_by(LongTermGoal.updated_at.desc())
        .limit(10)
    )).scalars().all()
    goals = [
        {"id": g.id, "title": g.title, "category": g.category,
         "progress": g.progress, "target_date": g.target_date,
         "description": g.description}
        for g in goals_rows
    ]

    # Active/planning projects
    proj_rows = (await db.execute(
        select(Project)
        .where(Project.device_id == device_id)
        .where(Project.status.in_(["active", "planning"]))
        .order_by(Project.updated_at.desc())
        .limit(10)
    )).scalars().all()
    projects = [
        {"id": p.id, "name": p.name, "status": p.status,
         "progress": p.progress, "deadline": p.deadline, "goal_id": p.goal_id}
        for p in proj_rows
    ]

    # Recent memories (high importance first)
    mem_rows = (await db.execute(
        select(Memory)
        .where(Memory.device_id == device_id)
        .order_by(Memory.importance.desc(), Memory.ts.desc())
        .limit(8)
    )).scalars().all()
    memories = [
        {"title": m.title, "content": m.content,
         "memory_type": m.memory_type, "importance": m.importance}
        for m in mem_rows
    ]

    # Latest live context
    ctx_row = (await db.execute(
        select(UserContext)
        .where(UserContext.device_id == device_id)
        .order_by(UserContext.ts.desc())
        .limit(1)
    )).scalar_one_or_none()
    context = {
        "productivity_state":     ctx_row.productivity_state      if ctx_row else "unknown",
        "current_task":           ctx_row.current_task             if ctx_row else "—",
        "dominant_app":           ctx_row.dominant_app             if ctx_row else "—",
        "dominant_classification":ctx_row.dominant_classification  if ctx_row else "—",
        "is_work_block":          ctx_row.is_work_block            if ctx_row else False,
        "confidence":             ctx_row.confidence               if ctx_row else 0.0,
        "suggested_action":       ctx_row.suggested_action         if ctx_row else "",
    } if ctx_row else None

    # Daily report (cached)
    today    = datetime.now().strftime("%Y-%m-%d")
    daily_db = (await db.execute(
        select(DailyReport)
        .where(DailyReport.device_id == device_id)
        .where(DailyReport.date == today)
        .order_by(DailyReport.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if daily_db and (time.time() - daily_db.generated_at) < 300:
        daily = {
            "focus_score":          daily_db.focus_score,
            "productive_minutes":   daily_db.productive_minutes,
            "distraction_minutes":  daily_db.distraction_minutes,
            "snapshot_count":       daily_db.snapshot_count,
            "recommendations":      daily_db.recommendations,
            "major_activities":     daily_db.major_activities,
        }
    else:
        daily_raw = await generate_daily_report(device_id, today, db)
        daily = {
            "focus_score":          daily_raw["focus_score"],
            "productive_minutes":   daily_raw["productive_minutes"],
            "distraction_minutes":  daily_raw["distraction_minutes"],
            "snapshot_count":       daily_raw["snapshot_count"],
            "recommendations":      daily_raw["recommendations"],
            "major_activities":     daily_raw["major_activities"],
        }

    # Weekly report (cached)
    now      = datetime.now()
    wk_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    weekly_db = (await db.execute(
        select(WeeklyReport)
        .where(WeeklyReport.device_id == device_id)
        .where(WeeklyReport.week_start == wk_start)
        .order_by(WeeklyReport.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if weekly_db and (time.time() - weekly_db.generated_at) < 900:
        weekly = {
            "focus_score":                   weekly_db.focus_score,
            "productivity_trend":            weekly_db.productivity_trend,
            "avg_daily_productive_minutes":  weekly_db.avg_daily_productive_minutes,
            "avg_daily_distraction_minutes": weekly_db.avg_daily_distraction_minutes,
            "daily_scores":                  weekly_db.daily_scores,
            "improvement_suggestions":       weekly_db.improvement_suggestions,
        }
    else:
        weekly_raw = await generate_weekly_report(device_id, wk_start, db, goals=goals, projects=projects)
        weekly = {
            "focus_score":                   weekly_raw["focus_score"],
            "productivity_trend":            weekly_raw["productivity_trend"],
            "avg_daily_productive_minutes":  weekly_raw["avg_daily_productive_minutes"],
            "avg_daily_distraction_minutes": weekly_raw["avg_daily_distraction_minutes"],
            "daily_scores":                  weekly_raw["daily_scores"],
            "improvement_suggestions":       weekly_raw["improvement_suggestions"],
        }

    return {
        "profile":  profile,
        "goals":    goals,
        "projects": projects,
        "memories": memories,
        "context":  context,
        "daily":    daily,
        "weekly":   weekly,
    }


async def _check_cache(
    device_id: str,
    task_type: TaskType,
    ttl: int,
    db: AsyncSession,
) -> Optional[str]:
    """Return cached insight text if fresh enough, else None."""
    row = (await db.execute(
        select(AIInsight)
        .where(AIInsight.device_id == device_id)
        .where(AIInsight.task_type == task_type.value)
        .order_by(AIInsight.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if row and (time.time() - row.generated_at) < ttl:
        return row.text
    return None


async def _persist_result(
    device_id: str,
    task_type: TaskType,
    resp: GenerateResponse,
    db: AsyncSession,
) -> None:
    """Write AIInsight + ReasoningLog + ProviderUsage rows."""
    now = time.time()

    db.add(AIInsight(
        device_id    = device_id,
        task_type    = task_type.value,
        text         = resp.text,
        provider     = resp.provider.value,
        model        = resp.model,
        input_tokens = resp.input_tokens,
        output_tokens= resp.output_tokens,
        cost_usd     = resp.cost_usd,
        generated_at = now,
    ))

    db.add(ReasoningLog(
        device_id    = device_id,
        task_type    = task_type.value,
        provider     = resp.provider.value,
        model        = resp.model,
        latency_ms   = resp.latency_ms,
        input_tokens = resp.input_tokens,
        output_tokens= resp.output_tokens,
        cost_usd     = resp.cost_usd,
        error        = resp.error,
        ts           = now,
    ))

    db.add(ProviderUsage(
        provider     = resp.provider.value,
        model        = resp.model,
        task_type    = task_type.value,
        input_tokens = resp.input_tokens,
        output_tokens= resp.output_tokens,
        cost_usd     = resp.cost_usd,
        ts           = now,
    ))

    try:
        await db.commit()
    except Exception as e:
        logger.warning("Failed to persist AI result: %s", e)
        await db.rollback()


# ---------------------------------------------------------------------------
# Public entry points — one per task type
# ---------------------------------------------------------------------------

async def run_daily_brief(device_id: str, db: AsyncSession, force: bool = False) -> dict:
    task_type = TaskType.DAILY_BRIEF
    if not force:
        cached = await _check_cache(device_id, task_type, _CACHE_BRIEF_S, db)
        if cached:
            return {"text": cached, "cached": True, "task_type": task_type.value}

    ctx  = await _load_context(device_id, db)
    sys_p, usr_p = prompts.daily_brief(ctx)
    tier, max_tokens, temp = route(task_type)

    mgr  = get_provider_manager()
    resp = await mgr.generate(GenerateRequest(
        system_prompt = sys_p,
        user_prompt   = usr_p,
        task_tier     = tier,
        max_tokens    = max_tokens,
        temperature   = temp,
        task_label    = task_type.value,
        device_id     = device_id,
    ))

    if not resp.error:
        await _persist_result(device_id, task_type, resp, db)
    return {"text": resp.text or resp.error, "cached": False, "task_type": task_type.value,
            "provider": resp.provider.value, "model": resp.model, "cost_usd": resp.cost_usd}


async def run_evening_review(device_id: str, db: AsyncSession, force: bool = False) -> dict:
    task_type = TaskType.EVENING_REVIEW
    if not force:
        cached = await _check_cache(device_id, task_type, _CACHE_EVENING_S, db)
        if cached:
            return {"text": cached, "cached": True, "task_type": task_type.value}

    ctx  = await _load_context(device_id, db)
    sys_p, usr_p = prompts.evening_review(ctx)
    tier, max_tokens, temp = route(task_type)

    mgr  = get_provider_manager()
    resp = await mgr.generate(GenerateRequest(
        system_prompt = sys_p,
        user_prompt   = usr_p,
        task_tier     = tier,
        max_tokens    = max_tokens,
        temperature   = temp,
        task_label    = task_type.value,
        device_id     = device_id,
    ))

    if not resp.error:
        await _persist_result(device_id, task_type, resp, db)
    return {"text": resp.text or resp.error, "cached": False, "task_type": task_type.value,
            "provider": resp.provider.value, "model": resp.model, "cost_usd": resp.cost_usd}


async def run_weekly_review(device_id: str, db: AsyncSession, force: bool = False) -> dict:
    task_type = TaskType.WEEKLY_REVIEW
    if not force:
        cached = await _check_cache(device_id, task_type, _CACHE_WEEKLY_S, db)
        if cached:
            return {"text": cached, "cached": True, "task_type": task_type.value}

    ctx  = await _load_context(device_id, db)
    sys_p, usr_p = prompts.weekly_review(ctx)
    tier, max_tokens, temp = route(task_type)

    mgr  = get_provider_manager()
    resp = await mgr.generate(GenerateRequest(
        system_prompt = sys_p,
        user_prompt   = usr_p,
        task_tier     = tier,
        max_tokens    = max_tokens,
        temperature   = temp,
        task_label    = task_type.value,
        device_id     = device_id,
    ))

    if not resp.error:
        await _persist_result(device_id, task_type, resp, db)
    return {"text": resp.text or resp.error, "cached": False, "task_type": task_type.value,
            "provider": resp.provider.value, "model": resp.model, "cost_usd": resp.cost_usd}


async def run_insights(device_id: str, db: AsyncSession, force: bool = False) -> dict:
    task_type = TaskType.INSIGHT_SYNTHESIS
    if not force:
        cached = await _check_cache(device_id, task_type, _CACHE_INSIGHT_S, db)
        if cached:
            return {"text": cached, "cached": True, "task_type": task_type.value}

    ctx  = await _load_context(device_id, db)
    sys_p, usr_p = prompts.insight_synthesis(ctx)
    tier, max_tokens, temp = route(task_type)

    mgr  = get_provider_manager()
    resp = await mgr.generate(GenerateRequest(
        system_prompt = sys_p,
        user_prompt   = usr_p,
        task_tier     = tier,
        max_tokens    = max_tokens,
        temperature   = temp,
        task_label    = task_type.value,
        device_id     = device_id,
    ))

    if not resp.error:
        await _persist_result(device_id, task_type, resp, db)
    return {"text": resp.text or resp.error, "cached": False, "task_type": task_type.value,
            "provider": resp.provider.value, "model": resp.model, "cost_usd": resp.cost_usd}


async def run_ask(device_id: str, question: str, db: AsyncSession) -> dict:
    """
    Free-form query from the user. Classifies intent, selects prompt,
    routes to correct provider tier.
    """
    from .task_router import classify_intent
    task_type = classify_intent(question)

    # LOCAL tier handled without LLM
    if not needs_llm(task_type):
        return {
            "text":      "This is a local query. Check your Dashboard or Insights tab for live data.",
            "cached":    False,
            "task_type": task_type.value,
            "provider":  "local",
            "model":     "rule-engine",
            "cost_usd":  0.0,
        }

    ctx = await _load_context(device_id, db)
    tier, max_tokens, temp = route(task_type)

    # Select prompt template based on detected intent
    if task_type == TaskType.FREE_FORM_QUERY:
        sys_p, usr_p = prompts.free_form(ctx, question)
    else:
        sys_p, usr_p = prompts.productivity_coach(ctx, question)

    mgr  = get_provider_manager()
    resp = await mgr.generate(GenerateRequest(
        system_prompt = sys_p,
        user_prompt   = usr_p,
        task_tier     = tier,
        max_tokens    = max_tokens,
        temperature   = temp,
        task_label    = task_type.value,
        device_id     = device_id,
    ))

    if not resp.error:
        await _persist_result(device_id, task_type, resp, db)
    return {"text": resp.text or resp.error, "cached": False, "task_type": task_type.value,
            "provider": resp.provider.value, "model": resp.model, "cost_usd": resp.cost_usd}
