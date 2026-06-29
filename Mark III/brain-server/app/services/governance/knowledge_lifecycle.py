"""
MARK III — Knowledge Lifecycle

State machine for engineering milestones.

Every permanent engineering change progresses through:
  Draft → Implemented → Validated → Documented → Indexed → Embedded → Committed → Stable

Only Stable milestones become permanent engineering knowledge.

Lifecycle states are persisted to governance_lifecycle.json.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path

log = logging.getLogger("markiii.governance.lifecycle")
_LIFECYCLE_PATH = Path(__file__).parents[4] / "governance_lifecycle.json"


class LifecycleState(str, Enum):
    DRAFT       = "draft"
    IMPLEMENTED = "implemented"
    VALIDATED   = "validated"
    DOCUMENTED  = "documented"
    INDEXED     = "indexed"
    EMBEDDED    = "embedded"
    COMMITTED   = "committed"
    STABLE      = "stable"


_TRANSITIONS = {
    LifecycleState.DRAFT:       LifecycleState.IMPLEMENTED,
    LifecycleState.IMPLEMENTED: LifecycleState.VALIDATED,
    LifecycleState.VALIDATED:   LifecycleState.DOCUMENTED,
    LifecycleState.DOCUMENTED:  LifecycleState.INDEXED,
    LifecycleState.INDEXED:     LifecycleState.EMBEDDED,
    LifecycleState.EMBEDDED:    LifecycleState.COMMITTED,
    LifecycleState.COMMITTED:   LifecycleState.STABLE,
}


@dataclass
class Milestone:
    id:          str
    name:        str
    domain:      str
    state:       str = LifecycleState.DRAFT.value
    created_at:  str = ""
    updated_at:  str = ""
    notes:       str = ""
    history:     list = field(default_factory=list)


class KnowledgeLifecycle:
    def __init__(self) -> None:
        self._lock       = threading.RLock()
        self._milestones: dict[str, Milestone] = {}
        self._load()

    def create(self, name: str, domain: str, notes: str = "") -> Milestone:
        now = datetime.now().isoformat(timespec="seconds")
        m   = Milestone(
            id         = name.lower().replace(" ", "_")[:32],
            name       = name,
            domain     = domain,
            state      = LifecycleState.DRAFT.value,
            created_at = now,
            updated_at = now,
            notes      = notes,
        )
        with self._lock:
            self._milestones[m.id] = m
            self._save()
        log.info("Milestone created: %s [%s]", name, domain)
        return m

    def advance(self, milestone_id: str, notes: str = "") -> Milestone:
        with self._lock:
            m = self._milestones.get(milestone_id)
            if not m:
                raise KeyError(milestone_id)
            current = LifecycleState(m.state)
            if current == LifecycleState.STABLE:
                return m
            next_state = _TRANSITIONS[current]
            now = datetime.now().isoformat(timespec="seconds")
            m.history.append({"from": m.state, "to": next_state.value, "at": now, "notes": notes})
            m.state      = next_state.value
            m.updated_at = now
            self._save()
            log.info("Milestone %s: %s → %s", m.name, current.value, next_state.value)
            return m

    def get(self, milestone_id: str) -> Milestone | None:
        return self._milestones.get(milestone_id)

    def get_all(self, domain: str = "") -> list[Milestone]:
        with self._lock:
            ms = list(self._milestones.values())
        if domain:
            ms = [m for m in ms if m.domain == domain]
        return ms

    def stable(self) -> list[Milestone]:
        return [m for m in self.get_all() if m.state == LifecycleState.STABLE.value]

    def _load(self) -> None:
        try:
            if _LIFECYCLE_PATH.exists():
                data = json.loads(_LIFECYCLE_PATH.read_text())
                for d in data:
                    m = Milestone(**d)
                    self._milestones[m.id] = m
        except Exception as e:
            log.debug("Lifecycle load error: %s", e)

    def _save(self) -> None:
        try:
            _LIFECYCLE_PATH.write_text(
                json.dumps([asdict(m) for m in self._milestones.values()], indent=2)
            )
        except Exception as e:
            log.debug("Lifecycle save error: %s", e)


_lifecycle: KnowledgeLifecycle | None = None
_lc_lock = threading.Lock()


def get_lifecycle() -> KnowledgeLifecycle:
    global _lifecycle
    if _lifecycle is None:
        with _lc_lock:
            if _lifecycle is None:
                _lifecycle = KnowledgeLifecycle()
    return _lifecycle
