"""
MARK III — Goal Tracker

Maintains the owner's active goals, current projects, and milestones.
Goals are part of identity — not memory.

Goals are injected into every Qwen call so MARK always knows
what the owner is working toward without being reminded.

Goals can be:
  - Set via voice: "MARK, add a goal: launch PathwayAU by Q3"
  - Updated via voice: "MARK, PathwayAU MVP is done"
  - Queried: "What are my current goals?"

Goals are stored in UserProfile and persisted in user_profile.json.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

log = logging.getLogger("markiii.identity.goals")


@dataclass
class Goal:
    id:          str
    title:       str
    category:    str        # "project" | "milestone" | "personal" | "technical"
    status:      str        # "active" | "completed" | "paused" | "cancelled"
    priority:    int        = 1    # 1=highest
    description: str        = ""
    deadline:    str        = ""
    created_at:  str        = ""
    completed_at: str       = ""
    tags:        list[str]  = field(default_factory=list)

    def complete(self) -> None:
        self.status       = "completed"
        self.completed_at = datetime.now().isoformat(timespec="seconds")

    def pause(self) -> None:
        self.status = "paused"


class GoalTracker:
    """
    Manages active goals and milestones for the owner.
    Reads from and writes to UserProfile.
    """

    def add_goal(
        self,
        title:       str,
        category:    str = "project",
        description: str = "",
        priority:    int = 1,
        deadline:    str = "",
        tags:        list[str] = None,
    ) -> Goal:
        from app.services.identity.identity_manager import get_identity_manager
        import uuid

        goal = Goal(
            id          = str(uuid.uuid4())[:8],
            title       = title,
            category    = category,
            status      = "active",
            priority    = priority,
            description = description,
            deadline    = deadline,
            created_at  = datetime.now().isoformat(timespec="seconds"),
            tags        = tags or [],
        )

        mgr     = get_identity_manager()
        profile = mgr.profile

        # Store in current_projects if it's a project
        if category == "project" and title not in profile.current_projects:
            mgr.update(current_projects=[title] + profile.current_projects[:9])

        # Store in goals list
        existing = list(profile.goals)
        existing.insert(0, f"{title} [{category}]")
        mgr.update(goals=existing[:10])

        log.info("Goal added: %r (%s)", title, category)
        return goal

    def get_active_goals_summary(self) -> str:
        """Returns a formatted goal summary for Qwen context injection."""
        try:
            from app.services.identity.identity_manager import get_profile
            profile = get_profile()

            lines = []
            if profile.current_projects:
                lines.append(f"Current projects: {', '.join(profile.current_projects[:4])}")
            if profile.goals:
                lines.append(f"Active goals: {', '.join(profile.goals[:4])}")

            return "\n".join(lines)
        except Exception:
            return ""

    def mark_complete(self, title_fragment: str) -> bool:
        """Mark a goal as complete by matching a fragment of its title."""
        try:
            from app.services.identity.identity_manager import get_identity_manager
            mgr     = get_identity_manager()
            profile = mgr.profile

            # Remove from goals list
            updated_goals = [g for g in profile.goals if title_fragment.lower() not in g.lower()]
            if len(updated_goals) < len(profile.goals):
                mgr.update(goals=updated_goals)
                # Store completion in vector memory
                try:
                    from app.services.memory.chroma_store import get_chroma_store
                    get_chroma_store().add(
                        content    = f"Completed goal: {title_fragment}",
                        doc_id     = f"goal_complete_{title_fragment[:20]}_{datetime.now().strftime('%Y%m%d')}",
                        collection = "user_prefs",
                        metadata   = {"type": "goal_completion", "date": datetime.now().isoformat()},
                    )
                except Exception:
                    pass
                log.info("Goal completed: %r", title_fragment)
                return True
        except Exception as e:
            log.debug("Goal complete error: %s", e)
        return False


_tracker: Optional[GoalTracker] = None


def get_goal_tracker() -> GoalTracker:
    global _tracker
    if _tracker is None:
        _tracker = GoalTracker()
    return _tracker
