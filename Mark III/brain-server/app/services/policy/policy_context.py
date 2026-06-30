"""
MARK III — Policy Context (Phase 12A)

Assembles all information the Policy Engine needs to evaluate a rule.

A PolicyContext is built fresh for every action evaluation — it captures
the exact moment of the decision so rules always see current state.

Sources:
  - Current time and day
  - Live UserContext (productivity state, work block, meeting status)
  - PresenceManager (which devices are alive and their types)
  - UserProfile (user preferences, timezone, work hours)
  - Action being evaluated (type, parameters, safety level, target device)

Design principles:
  - PolicyContext is a pure data object (frozen after construction)
  - No async calls after creation — all DB lookups happen in the factory
  - Serializable to dict for logging and audit
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TimeContext:
    """Current time information used by time-based rules."""
    unix_ts:       float
    hour:          int          # 0–23
    minute:        int          # 0–59
    weekday:       int          # 0=Monday … 6=Sunday
    is_weekend:    bool
    is_after_midnight: bool     # 00:00–05:59
    is_late_night:     bool     # 22:00–23:59
    is_morning:        bool     # 06:00–09:59
    is_work_hours:     bool     # configurable, default 09:00–17:00
    date_str:      str          # YYYY-MM-DD

    @classmethod
    def now(
        cls,
        work_start: int = 9,
        work_end:   int = 17,
    ) -> "TimeContext":
        now = datetime.now()
        h   = now.hour
        wd  = now.weekday()
        return cls(
            unix_ts        = time.time(),
            hour           = h,
            minute         = now.minute,
            weekday        = wd,
            is_weekend     = wd >= 5,
            is_after_midnight = 0 <= h < 6,
            is_late_night  = h >= 22,
            is_morning     = 6 <= h < 10,
            is_work_hours  = (not wd >= 5) and (work_start <= h < work_end),
            date_str       = now.strftime("%Y-%m-%d"),
        )


@dataclass(frozen=True)
class DeviceContext:
    """Which devices are alive and what they can do."""
    connected_types:   frozenset[str]   # desktop, mobile, earbud, glasses
    has_earbuds:       bool
    has_glasses:       bool
    has_desktop:       bool
    has_mobile:        bool
    preferred_audio_output: str         # earbud | desktop | mobile | none
    target_device_id:  Optional[str]    # which device the action targets
    target_device_type: Optional[str]

    @classmethod
    def from_mesh(
        cls,
        target_device_id: Optional[str] = None,
    ) -> "DeviceContext":
        """Build from the live mesh device registry (mesh_manager.py)."""
        try:
            from app.services.mesh.mesh_manager import get_mesh_manager
            online = get_mesh_manager().get_online_devices()
        except Exception:
            online = []

        # Mesh device.type values: desktop | macbook | iphone | watch | esp32 | radar | glasses
        types = frozenset(d.type for d in online)
        mobile_types = {"iphone", "macbook", "watch"}

        if "glasses" in types:
            audio_out = "glasses"
        elif types & mobile_types:
            audio_out = "mobile"
        elif "desktop" in types:
            audio_out = "desktop"
        else:
            audio_out = "none"

        target_type = None
        if target_device_id:
            match = next((d for d in online if d.device_id == target_device_id), None)
            if match:
                target_type = match.type

        return cls(
            connected_types      = types,
            has_earbuds          = False,   # not modeled as a distinct mesh device type
            has_glasses          = "glasses" in types,
            has_desktop          = "desktop" in types,
            has_mobile           = bool(types & mobile_types),
            preferred_audio_output = audio_out,
            target_device_id     = target_device_id,
            target_device_type   = target_type,
        )

    @classmethod
    def empty(cls) -> "DeviceContext":
        return cls(
            connected_types      = frozenset(),
            has_earbuds          = False,
            has_glasses          = False,
            has_desktop          = False,
            has_mobile           = False,
            preferred_audio_output = "none",
            target_device_id     = None,
            target_device_type   = None,
        )


@dataclass(frozen=True)
class ProductivityContext:
    """Current cognitive/productivity state from UserContext."""
    state:             str        # focused | distracted | idle | unknown
    is_work_block:     bool
    in_meeting:        bool       # derived from dominant_app (Zoom, Teams, etc.)
    dominant_app:      str
    dominant_class:    str        # browser | ide | communication | media | ...
    focus_score:       float      # 0–100 from today's DailyReport
    distraction_minutes: float

    @classmethod
    def unknown(cls) -> "ProductivityContext":
        return cls(
            state              = "unknown",
            is_work_block      = False,
            in_meeting         = False,
            dominant_app       = "",
            dominant_class     = "",
            focus_score        = 0.0,
            distraction_minutes = 0.0,
        )


@dataclass(frozen=True)
class UserPreferences:
    """
    User-level policy preferences sourced from UserProfile.

    Stored as key-value pairs in UserProfile.metadata or as dedicated
    preference fields. Provides user-controlled overrides to global rules.
    """
    quiet_hours_start: int        = 22     # hour (24h) — no audio output
    quiet_hours_end:   int        = 7
    work_start:        int        = 9
    work_end:          int        = 17
    block_entertainment_in_work:  bool = True
    require_approval_for_caution: bool = False   # stricter approval
    auto_deny_dangerous_at_night: bool = True
    timezone:          str        = "UTC"
    preferred_voice:   str        = "earbud"     # earbud | desktop | mobile

    @classmethod
    def from_live_profile(cls) -> "UserPreferences":
        """Load from the live UserProfile (app.services.identity), or return defaults."""
        try:
            from app.services.identity.identity_manager import get_profile
            profile = get_profile()
            meta = getattr(profile, "metadata", None) or {}
        except Exception:
            return cls()
        return cls(
            quiet_hours_start            = meta.get("quiet_hours_start", 22),
            quiet_hours_end              = meta.get("quiet_hours_end",   7),
            work_start                   = meta.get("work_start",        9),
            work_end                     = meta.get("work_end",          17),
            block_entertainment_in_work  = meta.get("block_entertainment_in_work", True),
            require_approval_for_caution = meta.get("require_approval_for_caution", False),
            auto_deny_dangerous_at_night = meta.get("auto_deny_dangerous_at_night", True),
            timezone                     = meta.get("timezone", "UTC"),
            preferred_voice              = meta.get("preferred_voice", "desktop"),
        )

    @classmethod
    def defaults(cls) -> "UserPreferences":
        return cls()


# ---------------------------------------------------------------------------
# PolicyContext (the main object)
# ---------------------------------------------------------------------------

@dataclass
class PolicyContext:
    """
    Immutable snapshot of all context needed to evaluate policy rules.

    Built once per action evaluation via PolicyContext.build().
    Never re-fetched mid-evaluation.
    """
    # Action being evaluated
    action_type:   str
    safety_level:  str              # safe | caution | dangerous | critical
    parameters:    dict[str, Any]
    source:        str              # conversation | voice | api | schedule
    device_id:     str              # requesting device

    # Live context snapshots
    time:          TimeContext
    devices:       DeviceContext
    productivity:  ProductivityContext
    preferences:   UserPreferences

    # Session overrides (user granted temporary exceptions)
    session_overrides: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict:
        return {
            "action_type":  self.action_type,
            "safety_level": self.safety_level,
            "source":       self.source,
            "device_id":    self.device_id[:16] if self.device_id else "",
            "time": {
                "hour":           self.time.hour,
                "weekday":        self.time.weekday,
                "is_work_hours":  self.time.is_work_hours,
                "is_late_night":  self.time.is_late_night,
                "is_after_midnight": self.time.is_after_midnight,
            },
            "devices": {
                "connected":      sorted(self.devices.connected_types),
                "has_earbuds":    self.devices.has_earbuds,
                "audio_out":      self.devices.preferred_audio_output,
            },
            "productivity": {
                "state":          self.productivity.state,
                "is_work_block":  self.productivity.is_work_block,
                "in_meeting":     self.productivity.in_meeting,
                "dominant_class": self.productivity.dominant_class,
            },
        }


# ---------------------------------------------------------------------------
# Context factory
# ---------------------------------------------------------------------------

async def build_policy_context(
    action_type:   str,
    safety_level:  str,
    parameters:    dict[str, Any],
    device_id:     str,
    source:        str = "api",
    session_overrides: frozenset[str] | None = None,
) -> PolicyContext:
    """
    Assemble a PolicyContext from live mesh + identity state.

    Reads the mesh device registry (mesh_manager.py) and the identity
    profile (identity_manager.py) — both synchronous singletons in the
    live architecture. No DB session required.

    Productivity state has no live equivalent yet (the dormant UserContext/
    DailyReport tracking was never wired up) — defaults to .unknown(),
    which all productivity-gated rules already handle gracefully.
    """
    target_device = parameters.get("target_device_id") or parameters.get("device_id")

    device_ctx        = DeviceContext.from_mesh(target_device)
    productivity_ctx  = ProductivityContext.unknown()
    prefs             = UserPreferences.from_live_profile()
    time_ctx          = TimeContext.now(prefs.work_start, prefs.work_end)

    return PolicyContext(
        action_type       = action_type,
        safety_level      = safety_level,
        parameters        = parameters,
        source            = source,
        device_id         = device_id,
        time              = time_ctx,
        devices           = device_ctx,
        productivity      = productivity_ctx,
        preferences       = prefs,
        session_overrides = session_overrides or frozenset(),
    )
