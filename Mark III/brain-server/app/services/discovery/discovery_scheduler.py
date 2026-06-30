"""
MARK III — Discovery Scheduler

Background lifecycle for app + file discovery scans. Mirrors the pattern
already established by vault_indexer.py (deferred initial scan, periodic
background re-scan, thread-safe singleton).

Scans run on a dedicated daemon thread — never block the voice loop, mesh,
or action queue. Both scans are independently triggerable.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("markiii.discovery.scheduler")

_INITIAL_DELAY_S = 10.0     # let voice/mesh/action systems finish booting first
_RESCAN_INTERVAL_S = 1800.0  # 30 minutes


class DiscoveryScheduler:
    def __init__(self) -> None:
        self._thread:  threading.Thread | None = None
        self._running  = False
        self._lock     = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="discovery-scheduler", daemon=True)
            self._thread.start()
        log.info("Discovery Scheduler started (initial scan in %.0fs, rescan every %.0fmin)",
                  _INITIAL_DELAY_S, _RESCAN_INTERVAL_S / 60)

    def stop(self) -> None:
        self._running = False

    def refresh_now(self, apps: bool = True, files: bool = True) -> dict:
        """Manually trigger a scan, blocking until complete. Returns counts."""
        result = {}
        if apps:
            from app.services.discovery.app_discovery import run_and_store as scan_apps
            result["apps"] = scan_apps()
        if files:
            from app.services.discovery.file_discovery import run_and_store as scan_files
            result["files"] = scan_files()
        return result

    def _loop(self) -> None:
        time.sleep(_INITIAL_DELAY_S)
        while self._running:
            try:
                self._run_full_scan()
            except Exception as e:
                log.warning("Discovery scan cycle error: %s", e)
            for _ in range(int(_RESCAN_INTERVAL_S)):
                if not self._running:
                    return
                time.sleep(1)

    def _run_full_scan(self) -> None:
        from app.services.discovery.app_discovery import run_and_store as scan_apps
        from app.services.discovery.file_discovery import run_and_store as scan_files

        log.info("Discovery scan starting (apps + files)")
        apps_n  = scan_apps()
        files_n = scan_files()
        log.info("Discovery scan complete: %d apps, %d files", apps_n, files_n)


_scheduler: DiscoveryScheduler | None = None
_sched_lock = threading.Lock()


def get_discovery_scheduler() -> DiscoveryScheduler:
    global _scheduler
    if _scheduler is None:
        with _sched_lock:
            if _scheduler is None:
                _scheduler = DiscoveryScheduler()
    return _scheduler
