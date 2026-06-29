"""
MARK III — Voice Profile

Architecture for owner voice authentication.
No biometric data is stored — only enrollment metadata.

Phase 16B-iOS: voice enrollment happens during mobile onboarding.
Future: speaker diarization distinguishes owner from guests.

Currently: stub architecture only.
Biometric implementation comes in a dedicated security phase.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("markiii.identity.voice")


@dataclass
class VoiceEnrollmentStatus:
    enrolled:      bool  = False
    confidence:    float = 0.0
    enrolled_at:   str   = ""
    model_version: str   = ""
    guest_mode:    bool  = False


def get_enrollment_status() -> VoiceEnrollmentStatus:
    """Return current voice enrollment status from profile."""
    try:
        from app.services.identity.identity_manager import get_profile
        vp = get_profile().voice_profile
        return VoiceEnrollmentStatus(
            enrolled      = vp.enrolled,
            confidence    = vp.confidence_threshold,
            enrolled_at   = vp.enrollment_date,
            model_version = vp.model_version,
            guest_mode    = not vp.enrolled,
        )
    except Exception:
        return VoiceEnrollmentStatus()


def mark_enrolled(model_version: str = "v1") -> None:
    """Called when mobile app completes voice enrollment."""
    try:
        from app.services.identity.identity_manager import get_identity_manager
        mgr = get_identity_manager()
        vp  = mgr.profile.voice_profile
        vp.enrolled         = True
        vp.enrollment_date  = datetime.now().isoformat(timespec="seconds")
        vp.model_version    = model_version
        mgr.save()
        log.info("Voice enrollment completed")
    except Exception as e:
        log.warning("Voice enrollment error: %s", e)


def is_owner_voice() -> bool:
    """
    Future: compare current voice against enrolled print.
    Currently: returns True (no authentication yet).
    """
    status = get_enrollment_status()
    if not status.enrolled:
        return True  # No enrollment = open access (single-user assumption)
    return True  # TODO: implement speaker verification
