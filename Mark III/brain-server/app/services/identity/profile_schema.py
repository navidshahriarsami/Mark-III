"""
MARK III — User Profile Schema

The canonical identity model for a MARK owner.
Stored as JSON, human-readable, versioned.
One profile per MARK installation — no cross-user data ever.

Designed so the future MARK Mobile app can populate this during onboarding
without requiring any architecture changes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


PROFILE_VERSION = "1.0.0"


@dataclass
class NotificationPrefs:
    morning_brief:  bool = True
    device_alerts:  bool = True
    weather_alerts: bool = True
    do_not_disturb_start: str = "22:00"
    do_not_disturb_end:   str = "07:00"


@dataclass
class PrivacyPrefs:
    store_conversations: bool = True
    store_location:      bool = False
    obsidian_indexing:   bool = True
    analytics:           bool = False


@dataclass
class AutomationPrefs:
    auto_open_apps:      bool = True
    proactive_briefings: bool = True
    smart_defaults:      bool = True


@dataclass
class CommunicationStyle:
    response_length:   str = "concise"        # concise | balanced | detailed
    explanation_depth: str = "intermediate"   # beginner | intermediate | expert
    tone:              str = "professional"   # casual | professional | technical
    language:          str = "en"
    prefers_examples:  bool = True
    prefers_bullet_points: bool = False


@dataclass
class WorkingPattern:
    timezone:      str = ""
    work_start:    str = "09:00"
    work_end:      str = "18:00"
    focus_hours:   list[str] = field(default_factory=lambda: ["09:00-12:00"])
    working_days:  list[str] = field(default_factory=lambda: ["Mon","Tue","Wed","Thu","Fri"])


@dataclass
class VoiceProfile:
    enrolled:         bool  = False
    enrollment_date:  str   = ""
    confidence_threshold: float = 0.85
    model_version:    str   = ""
    # Biometric data is never stored here — only metadata


@dataclass
class UserProfile:
    # ── Identity ──────────────────────────────────────────────────────────────
    user_id:           str  = field(default_factory=lambda: str(uuid.uuid4()))
    display_name:      str  = ""
    preferred_name:    str  = ""
    email:             str  = ""

    # ── Context ───────────────────────────────────────────────────────────────
    timezone:          str  = ""
    languages:         list[str] = field(default_factory=lambda: ["en"])
    occupation:        str  = ""
    organisation:      str  = ""
    technical_level:   str  = "intermediate"  # beginner | intermediate | expert | engineer

    # ── Goals & interests ────────────────────────────────────────────────────
    goals:             list[str] = field(default_factory=list)
    interests:         list[str] = field(default_factory=list)
    current_projects:  list[str] = field(default_factory=list)

    # ── Devices & tools ───────────────────────────────────────────────────────
    primary_devices:   list[str] = field(default_factory=list)
    preferred_apps:    list[str] = field(default_factory=list)
    preferred_ide:     str  = ""
    preferred_browser: str  = ""
    preferred_shell:   str  = ""

    # ── Working pattern ───────────────────────────────────────────────────────
    working_pattern:   WorkingPattern = field(default_factory=WorkingPattern)

    # ── Communication ────────────────────────────────────────────────────────
    communication:     CommunicationStyle = field(default_factory=CommunicationStyle)

    # ── Preferences ───────────────────────────────────────────────────────────
    notifications:     NotificationPrefs   = field(default_factory=NotificationPrefs)
    privacy:           PrivacyPrefs        = field(default_factory=PrivacyPrefs)
    automation:        AutomationPrefs     = field(default_factory=AutomationPrefs)

    # ── Infrastructure ────────────────────────────────────────────────────────
    obsidian_vault:    str  = ""
    mesh_devices:      list[str] = field(default_factory=list)

    # ── Voice ─────────────────────────────────────────────────────────────────
    voice_profile:     VoiceProfile = field(default_factory=VoiceProfile)

    # ── Meta ──────────────────────────────────────────────────────────────────
    profile_version:   str  = PROFILE_VERSION
    created_at:        str  = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at:        str  = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    onboarded:         bool = False  # True once mobile/setup flow is completed
    onboarding_source: str  = ""     # "desktop" | "mobile" | "manual"

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """One-paragraph owner summary for injection into Qwen context."""
        name    = self.preferred_name or self.display_name or "the owner"
        parts   = [f"Owner: {name}."]
        if self.occupation:
            parts.append(f"Occupation: {self.occupation}.")
        if self.organisation:
            parts.append(f"Organisation: {self.organisation}.")
        if self.goals:
            parts.append(f"Goals: {', '.join(self.goals[:3])}.")
        if self.current_projects:
            parts.append(f"Current projects: {', '.join(self.current_projects[:3])}.")
        if self.preferred_ide:
            parts.append(f"Preferred IDE: {self.preferred_ide}.")
        parts.append(f"Communication style: {self.communication.response_length}, {self.communication.explanation_depth}.")
        if self.working_pattern.timezone:
            parts.append(f"Timezone: {self.working_pattern.timezone}.")
        return " ".join(parts)

    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        """Reconstruct from JSON dict, tolerating missing fields."""
        p = cls()
        for k, v in d.items():
            if not hasattr(p, k):
                continue
            attr = getattr(p, k)
            if isinstance(attr, WorkingPattern) and isinstance(v, dict):
                setattr(p, k, WorkingPattern(**{kk: vv for kk, vv in v.items() if hasattr(WorkingPattern(), kk)}))
            elif isinstance(attr, CommunicationStyle) and isinstance(v, dict):
                setattr(p, k, CommunicationStyle(**{kk: vv for kk, vv in v.items() if hasattr(CommunicationStyle(), kk)}))
            elif isinstance(attr, VoiceProfile) and isinstance(v, dict):
                setattr(p, k, VoiceProfile(**{kk: vv for kk, vv in v.items() if hasattr(VoiceProfile(), kk)}))
            elif isinstance(attr, (NotificationPrefs, PrivacyPrefs, AutomationPrefs)) and isinstance(v, dict):
                setattr(p, k, type(attr)(**{kk: vv for kk, vv in v.items() if hasattr(type(attr)(), kk)}))
            else:
                setattr(p, k, v)
        return p
