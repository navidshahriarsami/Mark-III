"""
MARK III Desktop Daemon — Main Entry Point (Windows)

Owns all async subsystems and wires them together:
  - RabbitHoleDetector  (screen watchdog)
  - BrainClient         (brain server bridge — heartbeat, snapshots, commands)

The MarkIIIDaemon instance is shared with the tray icon (running on the main
thread) via thread-safe submit() calls. All tray callbacks enter this async
context through that bridge.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from daemon.rabbit_hole_detector import RabbitHoleDetector
from daemon.brain_client import BrainClient
from daemon.screen_monitor import capture_snapshot

logger = logging.getLogger("markiii.main")


class MarkIIIDaemon:
    """
    Central coordinator. Owns every subsystem and exposes a minimal surface
    to the tray icon for cross-thread calls.
    """

    def __init__(self, brain_url: str = "http://localhost:8000") -> None:
        self._detector   = RabbitHoleDetector()
        self._brain_url  = brain_url
        self._brain:  Optional[BrainClient] = None
        self._stop_event: Optional[asyncio.Event] = None

        # Tray status callbacks — set by the tray after instantiation
        self.on_connect:    Optional[callable] = None
        self.on_disconnect: Optional[callable] = None

    # ------------------------------------------------------------------
    # Tray-callable interface  (submitted via DaemonThread.submit())
    # ------------------------------------------------------------------

    async def reload_config(self) -> None:
        """Reload blocked keywords + work blocks from YAML. Called by tray sync."""
        logger.info("Config reload triggered from tray.")
        self._detector._reload_config()
        logger.info(
            "Config reloaded — %d blocked keywords, trigger=%d min.",
            len(self._detector._blocked_keywords),
            int(self._detector._trigger_seconds // 60),
        )

    async def request_stop(self) -> None:
        """Signal the run() coroutine to shut down gracefully."""
        if self._stop_event:
            logger.info("Graceful shutdown requested.")
            self._stop_event.set()

    # ------------------------------------------------------------------
    # Main async run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._stop_event = asyncio.Event()
        logger.info("MARK III daemon starting.")

        async with BrainClient(
            base_url      = self._brain_url,
            on_connect    = self._handle_connect,
            on_disconnect = self._handle_disconnect,
        ) as brain:
            self._brain = brain
            # Give the detector a reference so breaches are reported to the server
            self._detector._brain_client = brain

            tasks = [
                asyncio.create_task(
                    self._detector.run(),
                    name="rabbit-hole-detector",
                ),
                asyncio.create_task(
                    brain.heartbeat_loop(),
                    name="brain-heartbeat",
                ),
                asyncio.create_task(
                    brain.snapshot_loop(capture_snapshot),
                    name="brain-snapshot",
                ),
                asyncio.create_task(
                    brain.command_poll(self._handle_incoming_command),
                    name="brain-command-poll",
                ),
            ]

            logger.info(
                "All subsystems started (%d tasks). Waiting for stop signal.",
                len(tasks),
            )

            # Hold here until tray calls request_stop()
            await self._stop_event.wait()

            logger.info("Stop event received — cancelling %d tasks.", len(tasks))
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Daemon exited cleanly.")

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _handle_connect(self) -> None:
        """Called by BrainClient on successful server contact."""
        if self.on_connect:
            self.on_connect()

    def _handle_disconnect(self) -> None:
        """Called by BrainClient when the server becomes unreachable."""
        if self.on_disconnect:
            self.on_disconnect()

    async def _handle_incoming_command(self, cmd: dict) -> None:
        """
        Receives a command dict from the brain server's command poll.
        Feeds it through the HITL executor (Phase 4). For now, logs it
        and posts an acknowledged status back.
        """
        cmd_id  = cmd.get("id", "?")
        raw_cmd = cmd.get("raw", "")
        logger.info("Incoming command queued: id=%s  raw=%r", cmd_id, raw_cmd[:80])
        # TODO Phase 4: route through executor.py HITL gate
        # result = await executor.run(raw_cmd)
        # await self._brain.post_command_result(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-32s  %(levelname)s  %(message)s",
        stream=sys.stdout,
    )

    daemon = MarkIIIDaemon()

    if "--no-tray" in sys.argv:
        logger.info("Starting in --no-tray debug mode.")
        asyncio.run(daemon.run())
    else:
        from platform.windows.tray_icon import launch
        launch(daemon)


if __name__ == "__main__":
    main()
