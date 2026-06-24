"""
MARK III Cognitive Engine — Daily & Weekly Report Generator

Aggregates raw Snapshot rows into human-readable productivity metrics.
Reports are generated on-demand and cached in DailyReport / WeeklyReport tables.

Assumptions:
  - Each Snapshot represents ~10s of foreground activity (daemon poll interval).
  - "Productive" classifications: ide, terminal, communication, productivity,
    career_development, research.
  - "Distraction" classifications: distraction, entertainment, media.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger("markiii.cognitive.reports")

INTERVAL_MIN = 10.0 / 60.0     # minutes represented by one snapshot row

PRODUCTIVE_CLASSES  = {"ide", "terminal", "communication", "productivity", "browser", "unknown"}
DISTRACTION_CLASSES = {"distraction", "media"}

# Classification → colour hint for timeline rendering
CLASS_COLOURS = {
    "ide":           "#00C896",
    "terminal":      "#888888",
    "browser":       "#4A9EFF",
    "communication": "#A855F7",
    "productivity":  "#22D3EE",
    "distraction":   "#FF4C4C",
    "media":         "#F59E0B",
    "system":        "#333333",
    "unknown":       "#444444",
}


def _date_str(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _hour(ts: float) -> int:
    return datetime.fromtimestamp(ts).hour


# ---------------------------------------------------------------------------
# Daily report
# ---------------------------------------------------------------------------

async def generate_daily_report(device_id: str, target_date: str, db) -> dict:
    """
    Aggregate all snapshots for device_id on target_date (YYYY-MM-DD).
    Returns a dict ready to serialise as JSON or persist to DailyReport.
    """
    from sqlalchemy import select
    from app.models.db import Snapshot

    dt        = datetime.strptime(target_date, "%Y-%m-%d")
    day_start = dt.replace(hour=0,  minute=0,  second=0).timestamp()
    day_end   = dt.replace(hour=23, minute=59, second=59).timestamp()

    result    = await db.execute(
        select(Snapshot)
        .where(Snapshot.device_id == device_id)
        .where(Snapshot.ts >= day_start)
        .where(Snapshot.ts <= day_end)
        .order_by(Snapshot.ts)
    )
    snapshots = result.scalars().all()

    if not snapshots:
        return _empty_daily(device_id, target_date)

    class_minutes: dict[str, float] = defaultdict(float)
    app_minutes:   dict[str, float] = defaultdict(float)
    hourly:        dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for snap in snapshots:
        cls = snap.classification or "unknown"
        app = snap.process_name   or "unknown"
        h   = _hour(snap.ts)

        class_minutes[cls] += INTERVAL_MIN
        app_minutes[app]   += INTERVAL_MIN
        hourly[h][cls]     += INTERVAL_MIN

    productive_minutes  = sum(class_minutes.get(c, 0) for c in PRODUCTIVE_CLASSES)
    distraction_minutes = sum(class_minutes.get(c, 0) for c in DISTRACTION_CLASSES)
    total_active        = productive_minutes + distraction_minutes
    focus_score         = round((productive_minutes / total_active * 100) if total_active > 0 else 0.0, 1)

    major_activities = sorted(
        [{"classification": k, "minutes": round(v, 1), "colour": CLASS_COLOURS.get(k, "#555")}
         for k, v in class_minutes.items()],
        key=lambda x: -x["minutes"],
    )[:5]

    top_apps = sorted(
        [{"app": k, "minutes": round(v, 1)} for k, v in app_minutes.items()],
        key=lambda x: -x["minutes"],
    )[:6]

    # Build hourly timeline (0-23), each entry has dominant class + minutes active
    hourly_breakdown = []
    for h in range(24):
        bucket = hourly.get(h, {})
        if not bucket:
            hourly_breakdown.append({"hour": h, "dominant_classification": None, "minutes": 0, "colour": None})
            continue
        dominant = max(bucket, key=bucket.get)
        hourly_breakdown.append({
            "hour":                   h,
            "dominant_classification": dominant,
            "minutes":                round(sum(bucket.values()), 1),
            "colour":                 CLASS_COLOURS.get(dominant, "#555"),
            "breakdown":              {k: round(v, 1) for k, v in bucket.items()},
        })

    recommendations = _daily_recommendations(
        focus_score, class_minutes, productive_minutes, distraction_minutes
    )

    return {
        "date":                  target_date,
        "device_id":             device_id,
        "productive_minutes":    round(productive_minutes, 1),
        "distraction_minutes":   round(distraction_minutes, 1),
        "focus_score":           focus_score,
        "major_activities":      major_activities,
        "top_apps":              top_apps,
        "hourly_breakdown":      hourly_breakdown,
        "recommendations":       recommendations,
        "snapshot_count":        len(snapshots),
        "classification_breakdown": {k: round(v, 1) for k, v in class_minutes.items()},
    }


def _empty_daily(device_id: str, date: str) -> dict:
    return {
        "date":                  date,
        "device_id":             device_id,
        "productive_minutes":    0.0,
        "distraction_minutes":   0.0,
        "focus_score":           0.0,
        "major_activities":      [],
        "top_apps":              [],
        "hourly_breakdown":      [{"hour": h, "dominant_classification": None, "minutes": 0, "colour": None} for h in range(24)],
        "recommendations":       ["No activity recorded for this day."],
        "snapshot_count":        0,
        "classification_breakdown": {},
    }


def _daily_recommendations(
    focus_score: float,
    class_minutes: dict,
    productive_minutes: float,
    distraction_minutes: float,
) -> list[str]:
    recs = []

    if focus_score >= 80:
        recs.append("Excellent focus today. Maintain this work pattern.")
    elif focus_score >= 60:
        recs.append("Solid focus today. A few more deep-work blocks would push it higher.")
    elif focus_score >= 40:
        recs.append("Moderate focus. Identify the two biggest distractions and eliminate them tomorrow.")
    else:
        recs.append("Low focus score today. Try time-blocking your work sessions tomorrow.")

    if distraction_minutes > 90:
        recs.append(f"Spent {int(distraction_minutes)}m on distractions — consider a site blocker during work blocks.")
    elif distraction_minutes > 45:
        recs.append(f"Spent {int(distraction_minutes)}m distracted. Set a 5-minute distraction budget next session.")

    if class_minutes.get("communication", 0) > 120:
        recs.append("Heavy communication load. Schedule two fixed messaging windows tomorrow.")

    if productive_minutes > 300:
        recs.append("Outstanding productive day — over 5 hours of focused work.")

    if not recs:
        recs.append("Keep up the consistent work pattern.")

    return recs[:4]


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------

async def generate_weekly_report(device_id: str, week_start: str, db, goals: list | None = None, projects: list | None = None) -> dict:
    """
    Aggregate all snapshots for device_id from week_start (Monday, YYYY-MM-DD)
    through the following Sunday.
    """
    from sqlalchemy import select
    from app.models.db import Snapshot

    dt_start  = datetime.strptime(week_start, "%Y-%m-%d")
    dt_end    = dt_start + timedelta(days=7)
    ts_start  = dt_start.timestamp()
    ts_end    = dt_end.timestamp()
    week_end  = (dt_end - timedelta(days=1)).strftime("%Y-%m-%d")

    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.device_id == device_id)
        .where(Snapshot.ts >= ts_start)
        .where(Snapshot.ts <  ts_end)
        .order_by(Snapshot.ts)
    )
    snapshots = result.scalars().all()

    if not snapshots:
        return _empty_weekly(device_id, week_start, week_end)

    daily_class:   dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    app_totals:    dict[str, float]             = defaultdict(float)
    class_totals:  dict[str, float]             = defaultdict(float)

    for snap in snapshots:
        day = _date_str(snap.ts)
        cls = snap.classification or "unknown"
        app = snap.process_name   or "unknown"
        daily_class[day][cls]  += INTERVAL_MIN
        app_totals[app]        += INTERVAL_MIN
        class_totals[cls]      += INTERVAL_MIN

    # Per-day scores
    daily_scores = []
    for i in range(7):
        day      = (dt_start + timedelta(days=i)).strftime("%Y-%m-%d")
        dc       = daily_class.get(day, {})
        prod     = sum(dc.get(c, 0) for c in PRODUCTIVE_CLASSES)
        dist     = sum(dc.get(c, 0) for c in DISTRACTION_CLASSES)
        total    = prod + dist
        score    = round((prod / total * 100) if total > 0 else 0.0, 1)
        daily_scores.append({
            "date":                day,
            "score":               score,
            "productive_minutes":  round(prod, 1),
            "distraction_minutes": round(dist, 1),
        })

    valid   = [d["score"] for d in daily_scores if d["productive_minutes"] > 0]
    avg     = round(sum(valid) / len(valid), 1) if valid else 0.0

    # Trend: compare first half vs second half of valid days
    trend = "insufficient_data"
    if len(valid) >= 4:
        mid        = len(valid) // 2
        first_avg  = sum(valid[:mid]) / mid
        second_avg = sum(valid[mid:]) / (len(valid) - mid)
        if second_avg > first_avg + 5:
            trend = "improving"
        elif second_avg < first_avg - 5:
            trend = "declining"
        else:
            trend = "stable"

    top_apps  = sorted(
        [{"app": k, "minutes": round(v, 1)} for k, v in app_totals.items()],
        key=lambda x: -x["minutes"],
    )[:6]

    top_class = sorted(
        [{"classification": k, "minutes": round(v, 1), "colour": CLASS_COLOURS.get(k, "#555")}
         for k, v in class_totals.items()],
        key=lambda x: -x["minutes"],
    )[:6]

    total_prod = sum(class_totals.get(c, 0) for c in PRODUCTIVE_CLASSES)
    total_dist = sum(class_totals.get(c, 0) for c in DISTRACTION_CLASSES)

    suggestions = _weekly_suggestions(avg, trend, total_prod, total_dist, class_totals)

    # ── Goal progress snapshot ─────────────────────────────────────────────────
    goal_summary = []
    for g in (goals or []):
        if g.get("status") == "active":
            goal_summary.append({
                "id":          g["id"],
                "title":       g["title"],
                "category":    g.get("category", "personal"),
                "progress":    g.get("progress", 0),
                "target_date": g.get("target_date"),
            })

    project_summary = []
    for p in (projects or []):
        if p.get("status") in ("active", "planning"):
            project_summary.append({
                "id":       p["id"],
                "name":     p["name"],
                "progress": p.get("progress", 0),
                "deadline": p.get("deadline"),
                "goal_id":  p.get("goal_id"),
            })

    return {
        "week_start":                    week_start,
        "week_end":                      week_end,
        "device_id":                     device_id,
        "focus_score":                   avg,
        "productivity_trend":            trend,
        "avg_daily_productive_minutes":  round(total_prod / 7, 1),
        "avg_daily_distraction_minutes": round(total_dist / 7, 1),
        "daily_scores":                  daily_scores,
        "top_applications":              top_apps,
        "top_classifications":           top_class,
        "improvement_suggestions":       suggestions,
        "snapshot_count":                len(snapshots),
        "active_goals":                  goal_summary,
        "active_projects":               project_summary,
    }


def _empty_weekly(device_id: str, week_start: str, week_end: str) -> dict:
    dt_start = datetime.strptime(week_start, "%Y-%m-%d")
    return {
        "week_start": week_start,
        "week_end":   week_end,
        "device_id":  device_id,
        "focus_score": 0.0,
        "productivity_trend": "insufficient_data",
        "avg_daily_productive_minutes":  0.0,
        "avg_daily_distraction_minutes": 0.0,
        "daily_scores": [
            {"date": (dt_start + timedelta(days=i)).strftime("%Y-%m-%d"),
             "score": 0.0, "productive_minutes": 0.0, "distraction_minutes": 0.0}
            for i in range(7)
        ],
        "top_applications":        [],
        "top_classifications":     [],
        "improvement_suggestions": ["No activity recorded for this week."],
        "snapshot_count":          0,
    }


def _weekly_suggestions(
    avg_score: float,
    trend: str,
    total_prod: float,
    total_dist: float,
    class_totals: dict,
) -> list[str]:
    suggestions = []

    if trend == "improving":
        suggestions.append("Productivity is trending upward this week. Keep the momentum.")
    elif trend == "declining":
        suggestions.append("Productivity dropped this week. Review your task list and remove blockers.")
    elif trend == "stable":
        suggestions.append("Productivity is stable. Consider one change to push the score higher next week.")

    if avg_score < 40:
        suggestions.append("Below 40% average focus. Try strict 90-minute work blocks with phone out of reach.")
    elif avg_score < 60:
        suggestions.append("Moderate focus score. Identify your single biggest time drain and address it.")
    elif avg_score >= 80:
        suggestions.append("Strong focus score this week. Excellent consistency.")

    if total_dist > total_prod * 0.35:
        suggestions.append("Distraction exceeds 35% of active time. A site blocker during work hours would help.")

    if class_totals.get("communication", 0) > 300:
        suggestions.append("Heavy communication load this week. Schedule two fixed messaging windows per day.")

    if not suggestions:
        suggestions.append("Solid week. Maintain the current work pattern.")

    return suggestions[:4]
