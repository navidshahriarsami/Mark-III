"""MARK III — Identity Diagnostics"""
from __future__ import annotations
import logging
log = logging.getLogger("markiii.identity.diag")

def log_identity_status() -> None:
    try:
        from app.services.identity.identity_manager import get_identity_manager
        mgr = get_identity_manager()
        p   = mgr.profile
        log.info(
            "Identity: owner=%r  onboarded=%s  voice=%s  devices=%d",
            p.preferred_name or p.display_name or "unknown",
            p.onboarded,
            p.voice_profile.enrolled,
            len(p.mesh_devices),
        )
    except Exception as e:
        log.debug("Identity diag error: %s", e)
