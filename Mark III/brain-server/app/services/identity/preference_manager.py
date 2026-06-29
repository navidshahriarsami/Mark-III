"""
MARK III — Preference Manager

Tracks and evolves communication and usage preferences.
Preferences change gradually — never abruptly.

Detects signals like:
  - User often asks for shorter responses → reduce response_length
  - User asks technical questions → raise explanation_depth
  - User speaks in a language → add to languages list
"""
from __future__ import annotations

import logging

log = logging.getLogger("markiii.identity.prefs")


def update_language_preference(detected_language: str) -> None:
    """Called when Whisper detects a non-English language."""
    if not detected_language or detected_language == "en":
        return
    try:
        from app.services.identity.identity_manager import get_identity_manager
        mgr     = get_identity_manager()
        profile = mgr.profile
        if detected_language not in profile.languages:
            langs = [detected_language] + [l for l in profile.languages if l != detected_language]
            mgr.update(languages=langs[:5])
            log.info("Language preference updated: primary=%s", detected_language)
    except Exception as e:
        log.debug("Language pref error: %s", e)


def note_query_intent(intent: str) -> None:
    """
    Called after every query. Gradually infers communication preferences
    from the types of questions the owner asks.
    """
    try:
        from app.services.identity.activity_tracker import get_activity_tracker
        get_activity_tracker().record_query("", intent)
    except Exception:
        pass


def update_preferred_app(app_name: str) -> None:
    """Called when an app is mentioned in context."""
    if not app_name:
        return
    try:
        from app.services.identity.identity_manager import get_identity_manager
        mgr  = get_identity_manager()
        apps = mgr.profile.preferred_apps
        if app_name not in apps:
            mgr.update(preferred_apps=[app_name] + apps[:9])
    except Exception:
        pass
