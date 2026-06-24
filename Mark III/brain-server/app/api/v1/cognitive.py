"""
MARK III — Cognitive Engine API

Endpoints:
  GET /api/v1/cognitive/context?device_id=
  GET /api/v1/cognitive/recommendations?device_id=
  GET /api/v1/cognitive/daily-report?device_id=&date=YYYY-MM-DD
  GET /api/v1/cognitive/weekly-report?device_id=&week_start=YYYY-MM-DD
"""

import logging
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import Device, Snapshot, UserContext, Recommendation, DailyReport, WeeklyReport, LongTermGoal, Project
from app.services.context_engine import derive_context
from app.services.recommendation_engine import generate_recommendations
from app.services.report_engine import generate_daily_report, generate_weekly_report, PRODUCTIVE_CLASSES, DISTRACTION_CLASSES, INTERVAL_MIN

logger = logging.getLogger("markiii.cognitive.api")
router = APIRouter(prefix="/cognitive", tags=["cognitive"])

# Work blocks (mirrors daemon_config.yaml defaults)
_WORK_BLOCKS = [{"start": 9, "end": 12}, {"start": 13, "end": 17}]
_CONTEXT_WINDOW = 900   # 15 minutes


# ---------------------------------------------------------------------------
# GET /cognitive/context
# ---------------------------------------------------------------------------

@router.get("/context")
async def get_context(
    device_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the live cognitive context for a device derived from the last 15
    minutes of snapshot activity.
    """
    cutoff = time.time() - _CONTEXT_WINDOW
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.device_id == device_id)
        .where(Snapshot.ts >= cutoff)
        .order_by(desc(Snapshot.ts))
        .limit(120)
    )
    snapshots = result.scalars().all()
    ctx       = derive_context(snapshots, _WORK_BLOCKS)

    return {
        "device_id":              device_id,
        "ts":                     time.time(),
        "current_task":           ctx.current_task,
        "productivity_state":     ctx.productivity_state.value,
        "confidence":             ctx.confidence,
        "suggested_action":       ctx.suggested_action,
        "dominant_app":           ctx.dominant_app,
        "dominant_classification": ctx.dominant_classification,
        "window_count":           ctx.window_count,
        "is_work_block":          ctx.is_work_block,
    }


# ---------------------------------------------------------------------------
# GET /cognitive/recommendations
# ---------------------------------------------------------------------------

@router.get("/recommendations")
async def get_recommendations(
    device_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Return prioritised recommendations for a device based on its current
    context and today's accumulated metrics.
    """
    # Derive live context
    cutoff = time.time() - _CONTEXT_WINDOW
    snap_result = await db.execute(
        select(Snapshot)
        .where(Snapshot.device_id == device_id)
        .where(Snapshot.ts >= cutoff)
        .order_by(desc(Snapshot.ts))
        .limit(120)
    )
    snapshots = snap_result.scalars().all()
    ctx = derive_context(snapshots, _WORK_BLOCKS)

    # Today's distraction / productive minutes
    today_str  = datetime.now().strftime("%Y-%m-%d")
    dt         = datetime.strptime(today_str, "%Y-%m-%d")
    day_start  = dt.replace(hour=0, minute=0, second=0).timestamp()

    today_snaps = await db.execute(
        select(Snapshot)
        .where(Snapshot.device_id == device_id)
        .where(Snapshot.ts >= day_start)
    )
    today_rows = today_snaps.scalars().all()

    productive_today  = sum(INTERVAL_MIN for s in today_rows if (s.classification or "unknown") in PRODUCTIVE_CLASSES)
    distraction_today = sum(INTERVAL_MIN for s in today_rows if (s.classification or "unknown") in DISTRACTION_CLASSES)

    # Fetch active goals + projects for deadline-aware recommendations
    goals_result = await db.execute(
        select(LongTermGoal)
        .where(LongTermGoal.device_id == device_id)
        .where(LongTermGoal.status == "active")
    )
    active_goals = [
        {"id": g.id, "title": g.title, "category": g.category,
         "progress": g.progress, "target_date": g.target_date}
        for g in goals_result.scalars().all()
    ]

    proj_result = await db.execute(
        select(Project)
        .where(Project.device_id == device_id)
        .where(Project.status.in_(["active", "planning"]))
    )
    active_projects = [
        {"id": p.id, "name": p.name, "progress": p.progress,
         "deadline": p.deadline, "status": p.status, "goal_id": p.goal_id}
        for p in proj_result.scalars().all()
    ]

    items = generate_recommendations(
        state                     = ctx.productivity_state,
        is_work_block             = ctx.is_work_block,
        distraction_minutes_today = distraction_today,
        productive_minutes_today  = productive_today,
        goals                     = active_goals,
        projects                  = active_projects,
    )

    # Persist to DB (replace today's recommendations for this device)
    new_recs = []
    for item in items:
        rec = Recommendation(
            device_id     = device_id,
            ts            = time.time(),
            text          = item.text,
            category      = item.category,
            priority      = item.priority,
            context_state = item.context_state,
        )
        db.add(rec)
        new_recs.append(rec)

    await db.commit()

    return {
        "device_id":       device_id,
        "ts":              time.time(),
        "context_state":   ctx.productivity_state.value,
        "is_work_block":   ctx.is_work_block,
        "recommendations": [
            {"text": r.text, "category": r.category, "priority": r.priority}
            for r in new_recs
        ],
    }


# ---------------------------------------------------------------------------
# GET /cognitive/daily-report
# ---------------------------------------------------------------------------

@router.get("/daily-report")
async def get_daily_report(
    device_id: str = Query(...),
    date:      str = Query(default=None, description="YYYY-MM-DD (defaults to today)"),
    db: AsyncSession = Depends(get_db),
):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    # Check cache
    cached = await db.execute(
        select(DailyReport)
        .where(DailyReport.device_id == device_id)
        .where(DailyReport.date == date)
        .order_by(desc(DailyReport.generated_at))
        .limit(1)
    )
    row = cached.scalar_one_or_none()

    # Regenerate if older than 5 minutes or missing
    if row and (time.time() - row.generated_at) < 300:
        return {
            "date":                  row.date,
            "device_id":             row.device_id,
            "productive_minutes":    row.productive_minutes,
            "distraction_minutes":   row.distraction_minutes,
            "focus_score":           row.focus_score,
            "major_activities":      row.major_activities,
            "top_apps":              row.top_apps,
            "hourly_breakdown":      row.hourly_breakdown,
            "recommendations":       row.recommendations,
            "snapshot_count":        row.snapshot_count,
            "cached":                True,
        }

    report = await generate_daily_report(device_id, date, db)

    # Upsert cache
    if row:
        row.productive_minutes  = report["productive_minutes"]
        row.distraction_minutes = report["distraction_minutes"]
        row.focus_score         = report["focus_score"]
        row.major_activities    = report["major_activities"]
        row.top_apps            = report["top_apps"]
        row.hourly_breakdown    = report["hourly_breakdown"]
        row.recommendations     = report["recommendations"]
        row.snapshot_count      = report["snapshot_count"]
        row.generated_at        = time.time()
    else:
        db.add(DailyReport(
            device_id           = device_id,
            date                = date,
            productive_minutes  = report["productive_minutes"],
            distraction_minutes = report["distraction_minutes"],
            focus_score         = report["focus_score"],
            major_activities    = report["major_activities"],
            top_apps            = report["top_apps"],
            hourly_breakdown    = report["hourly_breakdown"],
            recommendations     = report["recommendations"],
            snapshot_count      = report["snapshot_count"],
            generated_at        = time.time(),
        ))

    await db.commit()
    report["cached"] = False
    return report


# ---------------------------------------------------------------------------
# GET /cognitive/weekly-report
# ---------------------------------------------------------------------------

@router.get("/weekly-report")
async def get_weekly_report(
    device_id:  str = Query(...),
    week_start: str = Query(default=None, description="Monday YYYY-MM-DD (defaults to current week)"),
    db: AsyncSession = Depends(get_db),
):
    if week_start is None:
        today      = datetime.now()
        week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")

    try:
        dt = datetime.strptime(week_start, "%Y-%m-%d")
        if dt.weekday() != 0:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="week_start must be a Monday in YYYY-MM-DD format")

    # Cache check (15-minute TTL for weekly)
    cached = await db.execute(
        select(WeeklyReport)
        .where(WeeklyReport.device_id == device_id)
        .where(WeeklyReport.week_start == week_start)
        .order_by(desc(WeeklyReport.generated_at))
        .limit(1)
    )
    row = cached.scalar_one_or_none()

    if row and (time.time() - row.generated_at) < 900:
        return {
            "week_start":                    row.week_start,
            "week_end":                      row.week_end,
            "device_id":                     row.device_id,
            "focus_score":                   row.focus_score,
            "productivity_trend":            row.productivity_trend,
            "avg_daily_productive_minutes":  row.avg_daily_productive_minutes,
            "avg_daily_distraction_minutes": row.avg_daily_distraction_minutes,
            "daily_scores":                  row.daily_scores,
            "top_applications":              row.top_applications,
            "top_classifications":           row.top_classifications,
            "improvement_suggestions":       row.improvement_suggestions,
            "snapshot_count":                row.snapshot_count,
            "cached":                        True,
        }

    # Fetch active goals + projects for weekly report goal progress
    wg_result = await db.execute(
        select(LongTermGoal)
        .where(LongTermGoal.device_id == device_id)
        .where(LongTermGoal.status == "active")
    )
    weekly_goals = [
        {"id": g.id, "title": g.title, "category": g.category,
         "progress": g.progress, "target_date": g.target_date}
        for g in wg_result.scalars().all()
    ]

    wp_result = await db.execute(
        select(Project)
        .where(Project.device_id == device_id)
        .where(Project.status.in_(["active", "planning"]))
    )
    weekly_projects = [
        {"id": p.id, "name": p.name, "progress": p.progress,
         "deadline": p.deadline, "status": p.status, "goal_id": p.goal_id}
        for p in wp_result.scalars().all()
    ]

    report = await generate_weekly_report(device_id, week_start, db, goals=weekly_goals, projects=weekly_projects)

    if row:
        row.week_end                      = report["week_end"]
        row.focus_score                   = report["focus_score"]
        row.productivity_trend            = report["productivity_trend"]
        row.avg_daily_productive_minutes  = report["avg_daily_productive_minutes"]
        row.avg_daily_distraction_minutes = report["avg_daily_distraction_minutes"]
        row.daily_scores                  = report["daily_scores"]
        row.top_applications              = report["top_applications"]
        row.top_classifications           = report["top_classifications"]
        row.improvement_suggestions       = report["improvement_suggestions"]
        row.snapshot_count                = report["snapshot_count"]
        row.generated_at                  = time.time()
    else:
        db.add(WeeklyReport(
            device_id                     = device_id,
            week_start                    = week_start,
            week_end                      = report["week_end"],
            focus_score                   = report["focus_score"],
            productivity_trend            = report["productivity_trend"],
            avg_daily_productive_minutes  = report["avg_daily_productive_minutes"],
            avg_daily_distraction_minutes = report["avg_daily_distraction_minutes"],
            daily_scores                  = report["daily_scores"],
            top_applications              = report["top_applications"],
            top_classifications           = report["top_classifications"],
            improvement_suggestions       = report["improvement_suggestions"],
            snapshot_count                = report["snapshot_count"],
            generated_at                  = time.time(),
        ))

    await db.commit()
    report["cached"] = False
    return report
