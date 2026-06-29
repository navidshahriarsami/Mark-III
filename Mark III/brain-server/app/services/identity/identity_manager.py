"""
MARK III — Identity Manager

The single source of truth for who owns this MARK installation.
Loads, persists, and provides the UserProfile.

One installation = one owner. No exceptions.
The profile is stored locally and never shared.

Mobile onboarding will write to this same profile via the mesh API.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from app.services.identity.profile_schema import UserProfile

log = logging.getLogger("markiii.identity")

_PROFILE_PATH = Path(__file__).parents[3] / "user_profile.json"
_manager: Optional["IdentityManager"] = None
_lock = threading.Lock()


class IdentityManager:
    """
    Manages the owner's UserProfile for this MARK installation.

    On first run: creates a default profile (minimal, not onboarded).
    After mobile onboarding: profile is fully populated.
    Between runs: profile persists on disk.
    """

    def __init__(self) -> None:
        self._profile: UserProfile = self._load_or_create()
        self._dirty   = False
        log.info(
            "Identity loaded — owner: %r  onboarded: %s",
            self._profile.preferred_name or self._profile.display_name or "unknown",
            self._profile.onboarded,
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_or_create(self) -> UserProfile:
        if _PROFILE_PATH.exists():
            try:
                data = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
                profile = UserProfile.from_dict(data)
                log.info("Profile loaded: %s", _PROFILE_PATH)
                return profile
            except Exception as e:
                log.warning("Profile load failed (%s) — creating fresh", e)
        profile = UserProfile()
        self._save(profile)
        return profile

    def _save(self, profile: Optional[UserProfile] = None) -> None:
        p = profile or self._profile
        try:
            _PROFILE_PATH.write_text(
                json.dumps(p.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("Profile save failed: %s", e)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def profile(self) -> UserProfile:
        return self._profile

    def update(self, **kwargs) -> None:
        """Update profile fields and persist."""
        for k, v in kwargs.items():
            if hasattr(self._profile, k):
                setattr(self._profile, k, v)
        self._profile.touch()
        self._save()
        log.info("Profile updated: %s", list(kwargs.keys()))

    def save(self) -> None:
        self._save()

    def is_onboarded(self) -> bool:
        p = self._profile
        return bool(p.display_name or p.preferred_name)

    def get_context_summary(self) -> str:
        """
        Returns a compact owner summary for Qwen context injection.
        Always included in the Context Builder.
        """
        return self._profile.summary()

    def from_mobile_onboarding(self, data: dict) -> None:
        """
        Called when the mobile app completes onboarding.
        Merges mobile-provided data into the profile.
        """
        for k, v in data.items():
            if hasattr(self._profile, k):
                setattr(self._profile, k, v)
        self._profile.onboarded        = True
        self._profile.onboarding_source = "mobile"
        self._profile.touch()
        self._save()
        log.info("Profile populated from mobile onboarding: %s", self._profile.preferred_name)

    def reset(self) -> None:
        """Reset to a blank profile (for testing or re-onboarding)."""
        self._profile = UserProfile()
        self._save()
        log.info("Profile reset")


def get_identity_manager() -> IdentityManager:
    global _manager
    if _manager is None:
        with _lock:
            if _manager is None:
                _manager = IdentityManager()
    return _manager


def get_profile() -> UserProfile:
    return get_identity_manager().profile
