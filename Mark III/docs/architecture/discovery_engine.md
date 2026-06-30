# MARK III — Discovery Engine

**Phase:** 17B | **Status:** Live | **Version:** 0.21.0

MARK builds its own knowledge of the machine it runs on — installed applications
and personal files — by scanning in the background, not by guessing or asking
an external tool. This is what makes "open Slack" and "find my report" actually
work, instead of depending on PATH lookups that miss most consumer software.

---

## Why This Exists

`shutil.which()` and `os.startfile()` only resolve apps that are on `PATH` or
registered in the Windows "App Paths" registry key. Most consumer apps —
Slack, Discord, Spotify — install under `%LOCALAPPDATA%` and register neither.
They register a Start Menu shortcut, because that's how humans find them too.

Live voice testing surfaced this directly: "open Slack" failed with
`WinError 2` even though Slack was installed. The Discovery Engine fixes the
root cause, not the symptom.

The same principle applies to file search: walking the filesystem live on
every voice query doesn't scale and gets slower as folders grow. MARK indexes
once, in the background, and queries the index instantly.

---

## Architecture

```
app/services/discovery/
  discovery_store.py      ← SQLite: apps table + files table (fact_store.py pattern)
  app_discovery.py         ← Scans Start Menu shortcuts + Get-StartApps (PowerShell, zero deps)
  file_discovery.py        ← Indexes Desktop/Documents/Downloads/Pictures/Videos/Music/OneDrive
  discovery_scheduler.py   ← Background thread: initial scan +10s, rescan every 30min
```

### App Discovery

Two PowerShell sources, combined and deduplicated:

1. **Start Menu shortcuts** (`.lnk` files, user + all-users) — resolved via the
   `WScript.Shell` COM object (built into Windows). This is the primary source;
   every installer creates one.
2. **`Get-StartApps`** — covers UWP/Store apps and surfaces some desktop apps
   shortcuts miss. UWP entries launch via `shell:AppsFolder\<AppID>`.

```python
# Confirmed fix for the actual reported bug:
"Slack" → C:\Users\...\AppData\Local\slack\slack.exe   (source: shortcut)
```

`desktop_executor.py._launch_app()` tries the discovery index FIRST (exact
launch path MARK found on disk), falling back to the existing fuzzy-alias +
PATH resolution (`app_aliases.py`) only if discovery has no match — e.g.
before the first scan completes, or for an app genuinely not installed.

### File Discovery

Indexes a configurable root list — **not** the entire filesystem. Scanning
every drive would mean walking Windows system files, every `node_modules` in
every repo, and multi-terabyte AppData caches: slow, mostly noise, and not
what "find my file" voice queries need.

```python
# file_discovery.py — the whole scope policy, edit to expand/narrow
_ROOT_SUBDIRS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive"]
_EXCLUDE_DIR_NAMES = {"node_modules", ".git", "__pycache__", ".venv", "AppData", ...}
```

Measured: 22,821 files indexed in 4 seconds on the reference machine. Search
queries return in single-digit milliseconds against the SQLite index.

`file_executor.py._search_files()` queries the index when no explicit
`root_path` is given; falls back to a live `rglob()` walk for ad-hoc searches
outside the indexed scope or before the first scan completes.

---

## Scan Lifecycle

```
mark_service.py boots
  → DiscoveryScheduler.start()
       → sleep 10s (let voice/mesh/action systems finish booting)
       → scan apps (1-2s) + scan files (4-10s depending on folder sizes)
       → sleep 30 minutes
       → repeat
```

Manual refresh: `POST /discovery/refresh {"apps": true, "files": true}`
Stats: `GET /discovery/stats`

---

## Permissions

Discovery scanning itself is read-only background infrastructure — it doesn't
go through the Policy Engine (it's not a user-facing Action, same as
`vault_indexer.py`'s background scanning). The actions it *enables*
(`launch_app`, `search_files`) keep their existing safety tiers unchanged —
discovery only makes resolution succeed, it never changes what's allowed.

---

## Platform

Windows only. macOS/Linux scanning is not implemented — `scan_installed_apps()`
returns `[]` gracefully on other platforms rather than failing. MARK currently
runs as desktop brain on Windows exclusively (see [[device_mesh]]).

---

[[action_system]] · [[device_mesh]] · [[cognitive_pipeline]] · [[ADR-0013-Discovery-Engine]] · [[future]]
