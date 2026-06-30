"""
MARK III — App Discovery

Builds a real index of installed applications by scanning the actual machine —
not guessing via shutil.which()/PATH (which finds almost nothing for consumer
apps) and not relying on a hardcoded list.

Root cause this fixes: most consumer apps (Slack, Discord, Spotify, etc.)
install under %LOCALAPPDATA% and register only a Start Menu shortcut — they
are never on PATH and rarely register in the Windows "App Paths" registry key
that os.startfile() checks. Start Menu shortcuts are the one thing every
installer creates, because that's how humans find apps too.

Sources combined (Windows):
  1. Start Menu shortcuts (.lnk) — user + all-users, resolved via the
     WScript.Shell COM object (built into Windows, zero pip dependency)
  2. Get-StartApps — covers UWP/Store apps AND surfaces some desktop apps
     shortcuts miss; UWP entries launch via shell:AppsFolder\<AppID>

macOS/Linux: not yet implemented (MARK currently runs as desktop brain on
Windows only — see device_mesh.md). Returns an empty list gracefully.
"""
from __future__ import annotations

import json
import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("markiii.discovery.apps")

_PLATFORM = platform.system()

_SCAN_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$shell = New-Object -ComObject WScript.Shell
$results = @()

$paths = @("$env:APPDATA\Microsoft\Windows\Start Menu\Programs", "$env:ProgramData\Microsoft\Windows\Start Menu\Programs")
foreach ($p in $paths) {
    if (Test-Path $p) {
        Get-ChildItem -Path $p -Filter *.lnk -Recurse | ForEach-Object {
            try {
                $sc = $shell.CreateShortcut($_.FullName)
                if ($sc.TargetPath -and (Test-Path $sc.TargetPath)) {
                    $results += [PSCustomObject]@{ Name = $_.BaseName; Target = $sc.TargetPath; Source = "shortcut" }
                }
            } catch {}
        }
    }
}

Get-StartApps | ForEach-Object {
    $appId = $_.AppID
    if ($appId -match '^[A-Za-z]:\\' -and (Test-Path $appId)) {
        $results += [PSCustomObject]@{ Name = $_.Name; Target = $appId; Source = "startapp_exe" }
    } else {
        $results += [PSCustomObject]@{ Name = $_.Name; Target = "shell:AppsFolder\$appId"; Source = "uwp" }
    }
}

$results | ConvertTo-Json -Compress
"""


def scan_installed_apps(timeout: float = 30.0) -> list[dict]:
    """
    Run the Windows app scan and return a deduplicated list of
    {name, target, source} dicts. Returns [] on non-Windows or on failure
    (never raises — discovery is best-effort infrastructure, not a
    user-facing action).
    """
    if _PLATFORM != "Windows":
        log.info("App discovery not implemented for %s — skipping", _PLATFORM)
        return []

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCAN_SCRIPT],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            log.warning("App scan PowerShell exited %d: %s", proc.returncode, proc.stderr[:300])
            return []

        raw = proc.stdout.strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):   # PowerShell collapses single-item arrays
            data = [data]

        apps = [
            {"name": d["Name"], "target": d["Target"], "source": d["Source"]}
            for d in data if d.get("Name") and d.get("Target")
        ]
        log.info("App scan complete: %d apps in %.1fs", len(apps), time.monotonic() - t0)
        return apps

    except subprocess.TimeoutExpired:
        log.warning("App scan timed out after %.0fs", timeout)
        return []
    except Exception as e:
        log.warning("App scan failed: %s", e)
        return []


def run_and_store() -> int:
    """Scan and persist to the discovery store. Returns count of apps stored."""
    from app.services.discovery.discovery_store import get_discovery_store

    store   = get_discovery_store()
    scan_id = store.log_scan_start("apps")
    try:
        apps  = scan_installed_apps()
        count = store.replace_apps(apps)
        store.log_scan_end(scan_id, count)
        return count
    except Exception as e:
        store.log_scan_end(scan_id, 0, error=str(e))
        log.error("App discovery scan failed: %s", e)
        return 0
