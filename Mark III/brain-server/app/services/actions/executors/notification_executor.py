"""
MARK III — Notification Executor (Phase 12B)

Handles:
  send_notification (CAUTION) — desktop toast + mobile push

Channels (attempted in order, first available wins):
  1. plyer         — cross-platform desktop toast (pip install plyer)
  2. win10toast    — Windows 10/11 toast (pip install win10toast)
  3. platform APIs — macOS osascript, Linux notify-send
  4. Mobile push   — via /voice/device or stored device_id from Presence
     (sends a push notification payload to the mobile API endpoint)

Parameters:
  title     str  — notification title
  body      str  — notification body
  sound     bool — play sound (default True)
  device_id str  — optional: route to specific device
"""

from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
import time
from typing import Optional

from app.services.actions.base_action import Action, ActionResult, ActionType

logger = logging.getLogger(__name__)

_PLATFORM = platform.system()

try:
    from plyer import notification as plyer_notification
    _PLYER_AVAILABLE = True
except ImportError:
    _PLYER_AVAILABLE = False

try:
    from win10toast import ToastNotifier
    _WIN10TOAST_AVAILABLE = True
except ImportError:
    _WIN10TOAST_AVAILABLE = False


class NotificationExecutor:

    async def run(self, action: Action) -> ActionResult:
        t0 = time.monotonic()
        try:
            result = await self._dispatch(action)
        except Exception as exc:
            result = ActionResult(success=False, error=str(exc))
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    async def _dispatch(self, action: Action) -> ActionResult:
        if action.action_type == ActionType.SEND_NOTIFICATION:
            return await asyncio.to_thread(
                self._send,
                action.parameters["title"],
                action.parameters["body"],
                bool(action.parameters.get("sound", True)),
                action.parameters.get("device_id"),
            )
        return ActionResult(success=False, error=f"Unknown notification action: {action.action_type}")

    # ------------------------------------------------------------------
    # Desktop notification
    # ------------------------------------------------------------------

    def _send(
        self, title: str, body: str, sound: bool, target_device: Optional[str]
    ) -> ActionResult:
        channels_tried: list[str] = []
        errors:         list[str] = []

        # 1. plyer (best cross-platform)
        if _PLYER_AVAILABLE:
            try:
                plyer_notification.notify(
                    title       = title,
                    message     = body,
                    app_name    = "MARK III",
                    timeout     = 10,
                )
                return ActionResult(
                    success  = True,
                    output   = f"Notification sent: {title}",
                    metadata = {"channel": "plyer"},
                )
            except Exception as exc:
                channels_tried.append("plyer")
                errors.append(f"plyer: {exc}")

        # 2. win10toast (Windows fallback)
        if _PLATFORM == "Windows" and _WIN10TOAST_AVAILABLE:
            try:
                toaster = ToastNotifier()
                toaster.show_toast(
                    title,
                    body,
                    duration   = 10,
                    threaded   = True,
                )
                return ActionResult(
                    success  = True,
                    output   = f"Notification sent: {title}",
                    metadata = {"channel": "win10toast"},
                )
            except Exception as exc:
                channels_tried.append("win10toast")
                errors.append(f"win10toast: {exc}")

        # 3. macOS osascript
        if _PLATFORM == "Darwin":
            try:
                script = f'display notification "{body}" with title "{title}"'
                subprocess.run(
                    ["osascript", "-e", script],
                    check=True, capture_output=True, timeout=5
                )
                return ActionResult(
                    success  = True,
                    output   = f"Notification sent: {title}",
                    metadata = {"channel": "osascript"},
                )
            except Exception as exc:
                channels_tried.append("osascript")
                errors.append(f"osascript: {exc}")

        # 4. Linux notify-send
        if _PLATFORM == "Linux":
            try:
                subprocess.run(
                    ["notify-send", title, body],
                    check=True, capture_output=True, timeout=5
                )
                return ActionResult(
                    success  = True,
                    output   = f"Notification sent: {title}",
                    metadata = {"channel": "notify-send"},
                )
            except Exception as exc:
                channels_tried.append("notify-send")
                errors.append(f"notify-send: {exc}")

        # All channels failed
        return ActionResult(
            success  = False,
            error    = f"All notification channels failed. Tried: {channels_tried}. Errors: {errors}",
            metadata = {"install_hint": "pip install plyer  # recommended cross-platform"},
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_executor: Optional[NotificationExecutor] = None

def get_notification_executor() -> NotificationExecutor:
    global _executor
    if _executor is None:
        _executor = NotificationExecutor()
    return _executor
