"""
MARK III — Learning Engine

Extracts meaningful patterns from activity and session data
to continuously improve MARK's understanding of its owner.

Runs periodically — not on every query.
Updates the UserProfile with learned preferences.
Stores recurring patterns in ChromaDB.

Learning signals:
  - Repeated query types → infer interests
  - Peak active hours → update working pattern
  - Mentioned apps/tools → update preferred apps
  - Response style feedback → update communication prefs
  - Recurring topics → update goals/interests
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("markiii.identity.learning")


def run_learning_cycle() -> None:
    """Run a single learning cycle — call after session end or on schedule."""
    try:
        from app.services.identity.activity_tracker  import get_activity_tracker
        from app.services.identity.identity_manager  import get_identity_manager

        tracker = get_activity_tracker()
        mgr     = get_identity_manager()
        insights = tracker.get_insights()
        profile  = mgr.profile

        updates: dict = {}

        # ── Infer working hours from peak activity ─────────────────────────
        peak_hour = insights.get("peak_hour")
        if peak_hour is not None:
            hour = int(peak_hour)
            if 5 <= hour <= 11:
                updates["working_pattern"] = type(profile.working_pattern)(
                    timezone    = profile.working_pattern.timezone,
                    work_start  = f"{hour:02d}:00",
                    work_end    = profile.working_pattern.work_end,
                    focus_hours = profile.working_pattern.focus_hours,
                    working_days= profile.working_pattern.working_days,
                )

        # ── Infer technical level from query types ────────────────────────
        qt = insights.get("query_types", {})
        complex_count = qt.get("complex", 0) + qt.get("reasoning", 0)
        total         = max(insights.get("total_queries", 1), 1)
        if complex_count / total > 0.5 and profile.technical_level == "intermediate":
            updates["technical_level"] = "expert"

        if updates:
            mgr.update(**updates)
            log.info("Learning cycle: updated profile with %d fields", len(updates))
        else:
            log.debug("Learning cycle: no updates needed")

    except Exception as e:
        log.debug("Learning cycle error: %s", e)


def start_learning_scheduler(interval_hours: float = 4.0) -> None:
    """Start background thread that runs learning cycles periodically."""
    def loop():
        while True:
            time.sleep(interval_hours * 3600)
            run_learning_cycle()

    t = threading.Thread(target=loop, daemon=True, name="learning-scheduler")
    t.start()
    log.info("Learning scheduler started (every %.0fh)", interval_hours)
