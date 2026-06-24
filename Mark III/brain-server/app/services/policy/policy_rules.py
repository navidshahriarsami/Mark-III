"""
MARK III — Policy Rules (Phase 12A)

Each rule is a pure synchronous function:

    rule(ctx: PolicyContext) -> Optional[PolicyDecision]

Returns None if the rule does not apply (pass-through).
Returns a PolicyDecision if the rule triggers.

Rules are evaluated in priority order. First non-None result wins.
All rules are registered in RULES_REGISTRY at the bottom of this file.

Rule categories:
  1. Safety rules     — enforce minimum safety thresholds globally
  2. Time rules       — quiet hours, night restrictions, work hours
  3. Work block rules — no entertainment/distraction during focus
  4. Device rules     — audio routing, meeting sensitivity
  5. Context rules    — productivity state influences action decisions
  6. User preference  — loaded from UserPreferences, may tighten defaults

Adding a new rule:
  1. Write a function: def my_rule(ctx) -> Optional[PolicyDecision]
  2. Register in RULES_REGISTRY with a priority (lower = higher priority)
  3. No restart needed — rules are loaded at engine init

Design principles:
  - No I/O, no async, no side effects in rules
  - Rules are composable and unit-testable in isolation
  - Every decision includes a human-readable reason
  - override_allowed marks decisions the user can bypass
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from app.services.policy.policy_context import PolicyContext


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    ALLOW            = "allow"
    DENY             = "deny"
    REQUIRE_APPROVAL = "require_approval"
    DEFER            = "defer"


@dataclass
class PolicyDecision:
    verdict:          Verdict
    reason:           str
    rule_name:        str
    conditions:       list[str]            = field(default_factory=list)
    defer_until_hour: Optional[int]        = None    # hour to defer to (e.g., 9 = next 9am)
    defer_seconds:    Optional[float]      = None    # or defer by N seconds
    override_allowed: bool                 = True    # can user override?
    suggested_action: Optional[str]        = None    # "try again after 9am"
    audio_device_override: Optional[str]   = None    # used by device rules

    @classmethod
    def allow(cls, rule_name: str, reason: str = "All policies passed") -> "PolicyDecision":
        return cls(verdict=Verdict.ALLOW, reason=reason, rule_name=rule_name)

    @classmethod
    def deny(
        cls, rule_name: str, reason: str,
        override_allowed: bool = True,
        suggested_action: Optional[str] = None,
    ) -> "PolicyDecision":
        return cls(
            verdict=Verdict.DENY, reason=reason, rule_name=rule_name,
            override_allowed=override_allowed, suggested_action=suggested_action,
        )

    @classmethod
    def require_approval(
        cls, rule_name: str, reason: str,
        override_allowed: bool = True,
    ) -> "PolicyDecision":
        return cls(
            verdict=Verdict.REQUIRE_APPROVAL, reason=reason,
            rule_name=rule_name, override_allowed=override_allowed,
        )

    @classmethod
    def defer(
        cls, rule_name: str, reason: str,
        defer_until_hour: Optional[int] = None,
        defer_seconds:    Optional[float] = None,
        suggested_action: Optional[str] = None,
    ) -> "PolicyDecision":
        return cls(
            verdict=Verdict.DEFER, reason=reason, rule_name=rule_name,
            defer_until_hour=defer_until_hour, defer_seconds=defer_seconds,
            suggested_action=suggested_action,
        )

    def to_dict(self) -> dict:
        return {
            "verdict":         self.verdict.value,
            "reason":          self.reason,
            "rule":            self.rule_name,
            "override_allowed": self.override_allowed,
            "defer_until_hour": self.defer_until_hour,
            "defer_seconds":   self.defer_seconds,
            "suggested_action": self.suggested_action,
            "audio_device":    self.audio_device_override,
        }


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

RuleFn = Callable[[PolicyContext], Optional[PolicyDecision]]


# ---------------------------------------------------------------------------
# 1. SAFETY RULES — enforce minimum thresholds globally
# ---------------------------------------------------------------------------

def rule_critical_always_approval(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    CRITICAL actions always require approval, no exceptions.
    Covers: delete files, install software, system changes, registry edits.
    """
    if ctx.safety_level == "critical":
        return PolicyDecision.require_approval(
            rule_name        = "critical_always_approval",
            reason           = f"Action is CRITICAL safety level — human approval required before MARK III can proceed.",
            override_allowed = False,   # cannot be overridden
        )
    return None


def rule_dangerous_requires_approval(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    DANGEROUS actions require approval unless the user has explicitly
    granted a session override for this action type.
    """
    if ctx.safety_level == "dangerous":
        override_key = f"dangerous:{ctx.action_type}"
        if override_key in ctx.session_overrides:
            return None  # user has pre-approved this type for this session
        return PolicyDecision.require_approval(
            rule_name        = "dangerous_requires_approval",
            reason           = f"Action is DANGEROUS — approval required. ({ctx.action_type})",
            override_allowed = True,
        )
    return None


def rule_caution_user_preference(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    If user has opted into stricter approval mode, CAUTION actions
    also require approval.
    """
    if ctx.safety_level == "caution" and ctx.preferences.require_approval_for_caution:
        return PolicyDecision.require_approval(
            rule_name = "caution_user_preference",
            reason    = "Your preference requires approval for cautious actions.",
        )
    return None


# ---------------------------------------------------------------------------
# 2. TIME RULES
# ---------------------------------------------------------------------------

def rule_quiet_hours_no_audio(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    No audio output (TTS, notifications with sound) during quiet hours.
    Quiet hours: quiet_hours_start → quiet_hours_end (wraps midnight).
    """
    audio_action_types = {
        "speak_aloud", "play_audio", "push_notification", "toast_notification",
        "voice_response",
    }
    if ctx.action_type not in audio_action_types:
        return None

    h     = ctx.time.hour
    start = ctx.preferences.quiet_hours_start   # e.g. 22
    end   = ctx.preferences.quiet_hours_end     # e.g. 7

    # Handle wrap-around (22 → 7 crosses midnight)
    in_quiet = (h >= start) or (h < end)

    if in_quiet:
        return PolicyDecision.deny(
            rule_name        = "quiet_hours_no_audio",
            reason           = f"Quiet hours ({start:02d}:00–{end:02d}:00) — audio output suppressed.",
            override_allowed = True,
            suggested_action = f"Audio output will resume at {end:02d}:00.",
        )
    return None


def rule_dangerous_auto_deny_at_night(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    Auto-deny dangerous actions at night if user preference is set.
    Rationale: accidental voice commands at 3am shouldn't delete files.
    """
    if not ctx.preferences.auto_deny_dangerous_at_night:
        return None
    if ctx.safety_level not in ("dangerous", "critical"):
        return None
    if ctx.time.is_after_midnight:
        return PolicyDecision.deny(
            rule_name        = "dangerous_auto_deny_at_night",
            reason           = "Dangerous actions are blocked between midnight and 6am for safety.",
            override_allowed = True,
            suggested_action = "This action will be available from 06:00.",
        )
    return None


def rule_defer_non_urgent_outside_work_hours(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    Non-urgent CAUTION actions triggered from voice/conversation outside
    work hours are deferred to next work session (avoids 11pm file moves).
    SAFE actions are never deferred.
    """
    deferrable_sources = {"voice", "conversation"}
    if ctx.source not in deferrable_sources:
        return None
    if ctx.safety_level not in ("caution", "dangerous"):
        return None
    # Only defer if outside work hours and it's late (after 21:00)
    if ctx.time.hour < 21 or ctx.time.is_work_hours:
        return None

    return PolicyDecision.defer(
        rule_name        = "defer_outside_work_hours",
        reason           = "It's late — this action will be queued for your next work session.",
        defer_until_hour = ctx.preferences.work_start,
        suggested_action = f"Action deferred to {ctx.preferences.work_start:02d}:00 tomorrow.",
        override_allowed = True,
    )


# ---------------------------------------------------------------------------
# 3. WORK BLOCK RULES
# ---------------------------------------------------------------------------

#: Apps/categories considered entertainment or distraction
_ENTERTAINMENT_APPS = frozenset({
    "spotify", "netflix", "youtube", "steam", "discord",
    "reddit", "twitter", "tiktok", "instagram", "facebook",
    "twitch", "vlc", "media player", "game", "games",
})

_ENTERTAINMENT_CATEGORIES = frozenset({"media", "social_media", "gaming", "distraction"})


def rule_no_entertainment_in_work_block(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    Do not open entertainment apps or websites during a work block.
    Applies to: launch_app, open_url, web_search.
    """
    if not (ctx.productivity.is_work_block and ctx.preferences.block_entertainment_in_work):
        return None

    applicable_types = {"launch_app", "open_url", "web_search", "open_file"}
    if ctx.action_type not in applicable_types:
        return None

    # Check target app/URL against entertainment list
    target = (
        ctx.parameters.get("app_name", "")
        or ctx.parameters.get("url", "")
        or ctx.parameters.get("query", "")
    ).lower()

    is_entertainment = (
        any(e in target for e in _ENTERTAINMENT_APPS) or
        ctx.parameters.get("category", "") in _ENTERTAINMENT_CATEGORIES
    )

    if is_entertainment:
        return PolicyDecision.deny(
            rule_name        = "no_entertainment_in_work_block",
            reason           = f"'{target or ctx.action_type}' is blocked during your work block.",
            override_allowed = True,
            suggested_action = "Focus until your work block ends.",
        )
    return None


def rule_meeting_no_audio_output(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    Suppress desktop audio output when user is in a meeting.
    Earbuds are still permitted (private audio).
    """
    audio_output_types = {"speak_aloud", "play_audio", "toast_notification"}
    if ctx.action_type not in audio_output_types:
        return None
    if not ctx.productivity.in_meeting:
        return None
    # Earbuds are fine during meetings
    if ctx.devices.has_earbuds:
        return PolicyDecision(
            verdict               = Verdict.ALLOW,
            reason                = "Audio routed to earbuds during meeting.",
            rule_name             = "meeting_route_to_earbuds",
            audio_device_override = "earbud",
        )
    return PolicyDecision.deny(
        rule_name        = "meeting_no_audio_output",
        reason           = "Desktop audio suppressed — you appear to be in a meeting.",
        override_allowed = True,
        suggested_action = "Connect earbuds for private audio during meetings.",
    )


# ---------------------------------------------------------------------------
# 4. DEVICE RULES
# ---------------------------------------------------------------------------

def rule_prefer_earbuds_for_audio(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    When earbuds are connected, route all voice/audio output to them.
    This is an ALLOW decision that carries a device routing hint.
    """
    audio_types = {"speak_aloud", "voice_response", "play_audio"}
    if ctx.action_type not in audio_types:
        return None
    if not ctx.devices.has_earbuds:
        return None
    # Return allow with audio_device_override hint
    return PolicyDecision(
        verdict               = Verdict.ALLOW,
        reason                = "Earbuds connected — routing audio output to earbuds.",
        rule_name             = "prefer_earbuds_for_audio",
        audio_device_override = "earbud",
    )


def rule_target_device_must_be_present(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    Actions targeting a specific device require that device to be alive
    in PresenceManager.
    """
    target = ctx.parameters.get("target_device_id")
    if not target:
        return None   # no targeting — OK
    if ctx.devices.target_device_type is not None:
        return None   # device found and alive
    return PolicyDecision.deny(
        rule_name        = "target_device_not_present",
        reason           = f"Target device '{target[:16]}' is not connected or has timed out.",
        override_allowed = False,
        suggested_action = "Check that the target device is online.",
    )


def rule_desktop_actions_require_desktop(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    Actions that launch applications or modify the filesystem require
    a desktop device to be present.
    """
    desktop_only_types = {
        "launch_app", "close_app", "focus_window", "minimize_window",
        "move_file", "delete_file", "create_file", "create_folder",
        "copy_file", "run_command", "install_software",
    }
    if ctx.action_type not in desktop_only_types:
        return None
    if ctx.devices.has_desktop:
        return None
    return PolicyDecision.deny(
        rule_name        = "desktop_actions_require_desktop",
        reason           = f"'{ctx.action_type}' requires a desktop device to be connected.",
        override_allowed = False,
        suggested_action = "Ensure your desktop is running and connected to MARK III.",
    )


# ---------------------------------------------------------------------------
# 5. CONTEXT RULES
# ---------------------------------------------------------------------------

def rule_distraction_warning_in_focus(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    During deep focus (high focus score, work block), opening a
    non-work application adds a soft caution — still ALLOWS but
    the response will include the advisory.
    This only fires if action is SAFE (otherwise safety rules already handle it).
    """
    if ctx.safety_level != "safe":
        return None
    if not ctx.productivity.is_work_block:
        return None
    if ctx.productivity.focus_score < 70:
        return None
    if ctx.productivity.state not in ("focused",):
        return None

    distraction_types = {"launch_app", "open_url", "web_search"}
    if ctx.action_type not in distraction_types:
        return None

    target = (
        ctx.parameters.get("app_name", "") or ctx.parameters.get("url", "")
    ).lower()

    # Known productive apps pass through silently
    productive_apps = {
        "code", "vscode", "visual studio", "pycharm", "intellij", "terminal",
        "iterm", "notion", "obsidian", "figma", "xcode", "cursor",
    }
    if any(p in target for p in productive_apps):
        return None

    # Allow but add conditions note (audit trail)
    return PolicyDecision(
        verdict    = Verdict.ALLOW,
        reason     = f"Allowed during focus block. Tip: this may interrupt your flow.",
        rule_name  = "distraction_warning_in_focus",
        conditions = [f"Focus score: {ctx.productivity.focus_score:.0f}%"],
    )


# ---------------------------------------------------------------------------
# 6. USER PREFERENCE RULES (extensible)
# ---------------------------------------------------------------------------

def rule_user_custom_app_blocks(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """
    Placeholder for user-defined app block rules.
    In future: loaded from UserProfile.metadata["blocked_apps"] list.
    Currently a no-op that shows the extension point.
    """
    blocked = ctx.parameters.get("_user_blocked_apps", [])
    target  = ctx.parameters.get("app_name", "").lower()
    if blocked and any(b.lower() in target for b in blocked):
        return PolicyDecision.deny(
            rule_name        = "user_custom_app_block",
            reason           = f"'{target}' is in your personal block list.",
            override_allowed = True,
        )
    return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegisteredRule:
    name:     str
    fn:       RuleFn
    priority: int         # lower = evaluated first
    category: str
    enabled:  bool = True


# Ordered registry — evaluated top to bottom
# Priority 100–199: safety (hardcoded, non-overridable)
# Priority 200–299: time (high impact)
# Priority 300–399: work block
# Priority 400–499: device routing
# Priority 500–599: context advisories
# Priority 600+:    user preferences

RULES_REGISTRY: list[RegisteredRule] = [
    # Safety (immovable)
    RegisteredRule("critical_always_approval",       rule_critical_always_approval,      100, "safety"),
    RegisteredRule("dangerous_requires_approval",    rule_dangerous_requires_approval,   110, "safety"),
    RegisteredRule("caution_user_preference",        rule_caution_user_preference,       120, "safety"),

    # Time
    RegisteredRule("dangerous_auto_deny_at_night",   rule_dangerous_auto_deny_at_night,  200, "time"),
    RegisteredRule("quiet_hours_no_audio",           rule_quiet_hours_no_audio,          210, "time"),
    RegisteredRule("defer_outside_work_hours",       rule_defer_non_urgent_outside_work_hours, 220, "time"),

    # Work block
    RegisteredRule("no_entertainment_in_work_block", rule_no_entertainment_in_work_block, 300, "work_block"),
    RegisteredRule("meeting_no_audio_output",        rule_meeting_no_audio_output,        310, "work_block"),

    # Device routing
    RegisteredRule("prefer_earbuds_for_audio",       rule_prefer_earbuds_for_audio,       400, "device"),
    RegisteredRule("target_device_must_be_present",  rule_target_device_must_be_present,  410, "device"),
    RegisteredRule("desktop_actions_require_desktop",rule_desktop_actions_require_desktop, 420, "device"),

    # Context advisories (all return ALLOW, add conditions)
    RegisteredRule("distraction_warning_in_focus",   rule_distraction_warning_in_focus,   500, "context"),

    # User preferences
    RegisteredRule("user_custom_app_blocks",         rule_user_custom_app_blocks,         600, "user_preference"),
]


def get_enabled_rules() -> list[RegisteredRule]:
    return sorted([r for r in RULES_REGISTRY if r.enabled], key=lambda r: r.priority)


def disable_rule(name: str) -> bool:
    """Disable a rule by name (runtime toggle, non-persistent)."""
    for i, r in enumerate(RULES_REGISTRY):
        if r.name == name:
            # Frozen dataclass — replace with new instance
            RULES_REGISTRY[i] = RegisteredRule(
                r.name, r.fn, r.priority, r.category, enabled=False,
            )
            return True
    return False


def enable_rule(name: str) -> bool:
    for i, r in enumerate(RULES_REGISTRY):
        if r.name == name:
            RULES_REGISTRY[i] = RegisteredRule(
                r.name, r.fn, r.priority, r.category, enabled=True,
            )
            return True
    return False
