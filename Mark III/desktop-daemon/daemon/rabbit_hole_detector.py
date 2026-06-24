"""
MARK III — Rabbit Hole Detector

Runs an async watch loop every 10 seconds. Maintains a rolling hit-counter
per distraction keyword. If any keyword stays continuously active for more
than TRIGGER_MINUTES during a designated work block, it fires a sarcastic
Windows toast notification and resets the counter.

Work blocks are defined in config/daemon_config.yaml.
Blocked keywords are defined in config/blocked_apps.yaml.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from plyer import notification

from daemon.screen_monitor import WindowSnapshot, capture_snapshot

logger = logging.getLogger("markiii.rabbit_hole")

# ---------------------------------------------------------------------------
# Configuration paths
# ---------------------------------------------------------------------------

_CONFIG_DIR   = Path(__file__).resolve().parent.parent / "config"
_DAEMON_CFG   = _CONFIG_DIR / "daemon_config.yaml"
_BLOCKED_CFG  = _CONFIG_DIR / "blocked_apps.yaml"


# ---------------------------------------------------------------------------
# Defaults — used if YAML files are absent
# ---------------------------------------------------------------------------

DEFAULT_POLL_SECONDS   = 10
DEFAULT_TRIGGER_MINUTES = 15

DEFAULT_BLOCKED_KEYWORDS: list[str] = [
    "youtube.com",
    "reddit",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "twitch.tv",
    "gaming",
    "discord",
    "9gag",
    "buzzfeed",
    "mechanical keyboard",   # self-aware easter egg
]

# Work blocks: list of (start_hour, end_hour) in 24h local time
# e.g. [(9, 12), (13, 17)] = 9–12 and 1–5 PM
DEFAULT_WORK_BLOCKS: list[tuple[int, int]] = [
    (9, 12),
    (13, 17),
]


# ---------------------------------------------------------------------------
# Sarcastic reprimand bank — rotated randomly on each trigger
# ---------------------------------------------------------------------------

_REPRIMANDS = [
    (
        "Mate, really?",
        "You've been on {keyword} for {minutes} minutes. "
        "Your goals aren't going to achieve themselves. Close the tab."
    ),
    (
        "Productivity? Never heard of her.",
        "{minutes} minutes on {keyword}. "
        "I've started billing this time as 'strategic procrastination.' "
        "It's not. Close it."
    ),
    (
        "Outstanding. Truly.",
        "A solid {minutes} minutes on {keyword}. "
        "I'd clap, but your project deadline can't. Get back to work."
    ),
    (
        "MARK III Distraction Report",
        "Active rabbit hole: {keyword}. Duration: {minutes} min. "
        "Recommended action: close the tab and pretend this never happened."
    ),
    (
        "You right there, champ?",
        "{minutes} minutes on {keyword}. "
        "That's impressive dedication — shame it's pointed the wrong direction."
    ),
    (
        "Intervention Time",
        "I've watched you browse {keyword} for {minutes} minutes. "
        "One of us is doing their job. It isn't you right now."
    ),
]


def _pick_reprimand(keyword: str, minutes: int) -> tuple[str, str]:
    title, msg = random.choice(_REPRIMANDS)
    return title, msg.format(keyword=keyword, minutes=minutes)


# ---------------------------------------------------------------------------
# YAML loaders
# ---------------------------------------------------------------------------

def _load_blocked_keywords() -> list[str]:
    if not _BLOCKED_CFG.exists():
        logger.warning("blocked_apps.yaml not found — using defaults.")
        return DEFAULT_BLOCKED_KEYWORDS
    with _BLOCKED_CFG.open() as f:
        data = yaml.safe_load(f) or {}
    return [kw.lower() for kw in data.get("keywords", DEFAULT_BLOCKED_KEYWORDS)]


def _load_work_blocks() -> list[tuple[int, int]]:
    if not _DAEMON_CFG.exists():
        return DEFAULT_WORK_BLOCKS
    with _DAEMON_CFG.open() as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("work_blocks", [])
    return [(int(b["start"]), int(b["end"])) for b in raw] or DEFAULT_WORK_BLOCKS


def _load_poll_seconds() -> int:
    if not _DAEMON_CFG.exists():
        return DEFAULT_POLL_SECONDS
    with _DAEMON_CFG.open() as f:
        data = yaml.safe_load(f) or {}
    return int(data.get("poll_seconds", DEFAULT_POLL_SECONDS))


def _load_trigger_minutes() -> int:
    if not _DAEMON_CFG.exists():
        return DEFAULT_TRIGGER_MINUTES
    with _DAEMON_CFG.open() as f:
        data = yaml.safe_load(f) or {}
    return int(data.get("trigger_minutes", DEFAULT_TRIGGER_MINUTES))


# ---------------------------------------------------------------------------
# Work block check
# ---------------------------------------------------------------------------

def _in_work_block(work_blocks: list[tuple[int, int]]) -> bool:
    now_hour = datetime.now().hour
    return any(start <= now_hour < end for start, end in work_blocks)


# ---------------------------------------------------------------------------
# Hit-counter state
# ---------------------------------------------------------------------------

@dataclass
class _KeywordState:
    keyword:      str
    first_seen:   float = field(default_factory=time.monotonic)
    last_seen:    float = field(default_factory=time.monotonic)
    alerted:      bool  = False   # True after a notification fires; reset on clean poll

    @property
    def continuous_minutes(self) -> float:
        return (self.last_seen - self.first_seen) / 60


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

def _fire_notification(keyword: str, minutes: int) -> None:
    title, message = _pick_reprimand(keyword, minutes)
    try:
        notification.notify(
            title=title,
            message=message,
            app_name="MARK III",
            timeout=12,          # seconds before auto-dismiss
        )
        logger.info("Distraction alert fired: keyword=%r minutes=%d", keyword, minutes)
    except Exception as exc:
        # plyer may fail if notification service is unavailable; log and move on
        logger.error("Failed to send notification: %s", exc)


# ---------------------------------------------------------------------------
# Detector class
# ---------------------------------------------------------------------------

class RabbitHoleDetector:
    """
    Async watch loop. Call run() as a long-lived coroutine inside the daemon.

    The state machine per keyword:
      - Keyword active in snapshot  → update last_seen; start timer if new
      - Keyword absent              → clear state (resets timer)
      - Timer exceeds threshold AND not yet alerted → fire notification, mark alerted
      - Keyword clears after alert  → full reset so next session is fresh

    brain_client is optional — set by MarkIIIDaemon after BrainClient is ready.
    When present, every breach is also reported to the server for DB persistence
    and push notification fan-out.
    """

    def __init__(self) -> None:
        self._active: dict[str, _KeywordState] = {}
        self._blocked_keywords: list[str] = []
        self._work_blocks: list[tuple[int, int]] = []
        self._poll_seconds: int = DEFAULT_POLL_SECONDS
        self._trigger_seconds: float = DEFAULT_TRIGGER_MINUTES * 60
        self._brain_client = None          # injected by MarkIIIDaemon
        self._last_snapshot: Optional[WindowSnapshot] = None

    def _reload_config(self) -> None:
        self._blocked_keywords = _load_blocked_keywords()
        self._work_blocks       = _load_work_blocks()
        self._poll_seconds      = _load_poll_seconds()
        self._trigger_seconds   = _load_trigger_minutes() * 60

    def _extract_hit_keywords(self, snapshot: WindowSnapshot) -> set[str]:
        text = snapshot.combined_text
        return {kw for kw in self._blocked_keywords if kw in text}

    def _tick(self, snapshot: Optional[WindowSnapshot]) -> None:
        """Update internal state for one poll cycle."""
        if snapshot is None:
            return
        self._last_snapshot = snapshot

        if not _in_work_block(self._work_blocks):
            # Outside work hours — silently drain all state
            self._active.clear()
            return

        hit_keywords = self._extract_hit_keywords(snapshot)

        # Advance or create counters for every currently-detected keyword
        now = time.monotonic()
        for kw in hit_keywords:
            if kw not in self._active:
                logger.debug("Rabbit hole started: %r", kw)
                self._active[kw] = _KeywordState(keyword=kw)
            else:
                self._active[kw].last_seen = now

        # Check thresholds and fire alerts
        for kw, state in list(self._active.items()):
            if kw not in hit_keywords:
                # Keyword disappeared — full reset
                logger.debug("Rabbit hole cleared: %r (was %.1f min)", kw, state.continuous_minutes)
                del self._active[kw]
                continue

            if (not state.alerted) and (state.continuous_minutes * 60 >= self._trigger_seconds):
                minutes = int(state.continuous_minutes)
                _fire_notification(kw, minutes)
                state.alerted = True   # suppress repeat alerts for the same session
                # Schedule async brain-server report without blocking the tick
                asyncio.create_task(
                    self._report_breach(kw, state.continuous_minutes),
                    name=f"breach-report-{kw[:20]}",
                )

    async def _report_breach(self, keyword: str, duration_min: float) -> None:
        """
        Fire-and-forget coroutine that posts a breach report to the brain server.
        Swallows all exceptions so a network failure never disrupts the detector.
        """
        if self._brain_client is None:
            return
        snap = self._last_snapshot
        try:
            await self._brain_client._post(
                "/api/v1/alerts/breach",
                {
                    "device_id":    self._brain_client._device_id,
                    "keyword":      keyword,
                    "duration_min": round(duration_min, 2),
                    "process_name": snap.process_name if snap else "unknown",
                    "active_domain": snap.ocr_address_bar[:128] if snap and snap.ocr_address_bar else None,
                },
            )
            logger.info("Breach report posted to brain server: keyword=%r", keyword)
        except Exception as exc:
            logger.warning("Failed to post breach to brain server: %s", exc)

    async def run(self) -> None:
        """Long-running async coroutine. Drop into the daemon event loop."""
        logger.info("Rabbit hole detector starting.")
        self._reload_config()

        config_reload_counter = 0

        while True:
            try:
                snapshot = await capture_snapshot()
                self._tick(snapshot)

                # Reload config every ~5 minutes (30 × 10 s) so changes to
                # blocked_apps.yaml take effect without restarting the daemon.
                config_reload_counter += 1
                if config_reload_counter >= 30:
                    self._reload_config()
                    config_reload_counter = 0

            except Exception:
                logger.exception("Unexpected error in rabbit hole detector tick.")

            await asyncio.sleep(self._poll_seconds)

    def current_state(self) -> list[dict]:
        """Expose internal hit state for the brain-server status endpoint."""
        return [
            {
                "keyword":    s.keyword,
                "minutes":    round(s.continuous_minutes, 1),
                "alerted":    s.alerted,
            }
            for s in self._active.values()
        ]
