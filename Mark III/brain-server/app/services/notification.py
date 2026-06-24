"""
MARK III Brain Server — Notification Service

Abstraction layer that sits between breach detection and external push APIs.
Concrete backends are selected at startup from config; the route layer calls
NotificationService.send_breach_alert() and doesn't care which backend fires.

Backends implemented:
  PushoverBackend   — Pushover API (iOS + Android, $5 one-time client app).
                      Best choice for a solo developer: instant setup, no SDK.
  LogOnlyBackend    — Writes to the server log. Default when no keys are set.
                      Zero configuration needed — always works.
  FCMBackend        — Firebase Cloud Messaging stub. Wired up in Phase 6
                      when the React Native app is built and FCM tokens exist.

Configuration (.env):
  NOTIFICATION_BACKEND=pushover      # or "log" or "fcm"
  PUSHOVER_APP_TOKEN=a...
  PUSHOVER_USER_KEY=u...
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("markiii.server.notification")


# ---------------------------------------------------------------------------
# Shared payload — backend-agnostic
# ---------------------------------------------------------------------------

@dataclass
class BreachAlert:
    device_id:    str
    hostname:     str
    keyword:      str
    duration_min: float
    process_name: str
    active_domain: Optional[str] = None

    @property
    def title(self) -> str:
        return "MARK III — Rabbit Hole Alert"

    @property
    def message(self) -> str:
        domain = self.active_domain or self.keyword
        mins   = int(self.duration_min)
        lines = [
            f"{mins} minutes on {domain}.",
            "Your goals aren't going to achieve themselves. Close the tab.",
            f"Device: {self.hostname}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class NotificationBackend(ABC):

    @abstractmethod
    async def send(self, alert: BreachAlert) -> tuple[bool, str]:
        """
        Send the alert. Returns (success: bool, receipt: str).
        receipt is a provider-specific ID or error message.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str: ...


# ---------------------------------------------------------------------------
# Log-only backend (default / fallback)
# ---------------------------------------------------------------------------

class LogOnlyBackend(NotificationBackend):
    name = "log"

    async def send(self, alert: BreachAlert) -> tuple[bool, str]:
        logger.warning(
            "BREACH ALERT [log-only]  device=%s  keyword=%r  duration=%.1f min  domain=%s",
            alert.device_id[:16], alert.keyword, alert.duration_min,
            alert.active_domain or "-",
        )
        return True, "logged"


# ---------------------------------------------------------------------------
# Pushover backend
# ---------------------------------------------------------------------------

_PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

_PRIORITY = {
    "normal": 0,
    "high":   1,    # bypasses quiet hours
    "emergency": 2, # requires acknowledgment (also needs retry + expire params)
}


class PushoverBackend(NotificationBackend):
    name = "pushover"

    def __init__(self, app_token: str, user_key: str) -> None:
        if not app_token or not user_key:
            raise ValueError("Pushover requires both PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY.")
        self._token    = app_token
        self._user_key = user_key

    async def send(self, alert: BreachAlert) -> tuple[bool, str]:
        payload = {
            "token":    self._token,
            "user":     self._user_key,
            "title":    alert.title,
            "message":  alert.message,
            "priority": _PRIORITY["normal"],
            "sound":    "intermission",
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(_PUSHOVER_URL, data=payload)
                r.raise_for_status()
                receipt = r.json().get("request", "ok")
                logger.info("Pushover alert sent. receipt=%s", receipt)
                return True, receipt
        except httpx.HTTPStatusError as exc:
            msg = f"Pushover HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error(msg)
            return False, msg
        except Exception as exc:
            msg = f"Pushover error: {exc}"
            logger.error(msg)
            return False, msg


# ---------------------------------------------------------------------------
# FCM stub — wired up in Phase 6 when mobile app has FCM tokens
# ---------------------------------------------------------------------------

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class FCMBackend(NotificationBackend):
    """
    Sends push notifications via the Expo Push API (which wraps FCM for Android
    and APNs for iOS). Fetches stored Expo push tokens from the DB at send time
    so newly registered devices are picked up automatically.
    """
    name = "fcm"

    def __init__(self, server_key: str) -> None:
        self._key = server_key

    async def send(self, alert: BreachAlert) -> tuple[bool, str]:
        from sqlalchemy import select
        from app.database import AsyncSessionLocal
        from app.models.db import Device

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Device.expo_push_token).where(
                    Device.expo_push_token.isnot(None)
                )
            )
            tokens = [row[0] for row in result.all()]

        if not tokens:
            logger.warning("FCM: no registered mobile push tokens — alert dropped.")
            return False, "no_tokens"

        messages = [
            {"to": token, "title": alert.title, "body": alert.message, "sound": "default"}
            for token in tokens
        ]

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(_EXPO_PUSH_URL, json=messages)
                r.raise_for_status()
                receipts = r.json().get("data", [])
                ok_count = sum(1 for rec in receipts if rec.get("status") == "ok")
                logger.info("Expo push sent to %d/%d tokens.", ok_count, len(tokens))
                return True, f"sent:{ok_count}/{len(tokens)}"
        except Exception as exc:
            logger.error("Expo push failed: %s", exc)
            return False, str(exc)


# ---------------------------------------------------------------------------
# Composite service — tries configured backend, falls back to log
# ---------------------------------------------------------------------------

class NotificationService:
    """
    Single instance, created at server startup via _build_backend().
    Route handlers call send_breach_alert() without knowing which backend fires.
    """

    def __init__(self, backend: NotificationBackend) -> None:
        self._backend  = backend
        self._fallback = LogOnlyBackend()
        logger.info("Notification service ready. backend=%s", backend.name)

    async def send_breach_alert(self, alert: BreachAlert) -> tuple[bool, str]:
        success, receipt = await self._backend.send(alert)
        if not success and self._backend.name != "log":
            logger.warning("Primary backend failed — falling back to log.")
            success, receipt = await self._fallback.send(alert)
        return success, receipt

    @property
    def backend_name(self) -> str:
        return self._backend.name


def build_notification_service() -> NotificationService:
    """
    Called once during app lifespan. Reads config and returns the
    appropriate NotificationService instance.
    """
    backend_name = settings.notification_backend.lower()

    if backend_name == "pushover":
        try:
            backend = PushoverBackend(
                app_token = settings.pushover_app_token,
                user_key  = settings.pushover_user_key,
            )
        except ValueError as exc:
            logger.warning("Pushover misconfigured (%s) — falling back to log.", exc)
            backend = LogOnlyBackend()

    elif backend_name == "fcm":
        backend = FCMBackend(server_key=settings.fcm_server_key)

    else:
        backend = LogOnlyBackend()

    return NotificationService(backend)
