# ADR-0013 — Discovery Engine

**Status:** Accepted
**Date:** 2026-06-30
**Author:** Navid Shahriar Sami

## Context

Live voice testing of Phase 17 (Universal Action System) surfaced that
"open Slack" failed even though Slack was installed. Root cause: app launch
resolution relied entirely on `shutil.which()` (PATH lookup) and
`os.startfile()` (Windows "App Paths" registry key) — neither of which most
consumer apps register. Slack, Discord, and Spotify install under
`%LOCALAPPDATA%` and rely solely on a Start Menu shortcut.

The same architectural gap applied to file search: `file_executor.py` walked
the filesystem live (`pathlib.rglob()`) on every single query, with no
caching — slow, and would only get slower as the indexed scope grew.

The user's explicit direction: MARK should resolve this with its own
capability, scanning its own machine in the background — not via narrow
per-bug patches, and not via any external tool performing the search on
MARK's behalf.

## Decision

Build a Discovery Engine (`app/services/discovery/`) that builds and persists
a real index of installed apps and personal files, refreshed automatically.

1. **App discovery** — PowerShell-based scan combining Start Menu shortcut
   resolution (`.lnk` via `WScript.Shell` COM, built into Windows, zero pip
   dependency) with `Get-StartApps` (covers UWP/Store apps). This finds what
   `shutil.which()` structurally cannot.
2. **File discovery** — indexes a deliberately scoped root list (Desktop,
   Documents, Downloads, Pictures, Videos, Music, OneDrive) rather than the
   entire filesystem. Indexing every drive would scan Windows system files,
   every `node_modules`, and multi-terabyte caches — slow and not useful for
   "find my file" queries. The scope is a single editable list in
   `file_discovery.py`, not a hardcoded constraint.
3. **Persistence** — SQLite (`discovery_store.py`), mirroring the
   `fact_store.py`/`action_store.py` pattern already established.
4. **Lifecycle** — background thread, initial scan 10s after boot, rescans
   every 30 minutes, manually triggerable via `POST /discovery/refresh`.
5. **Resolution priority** — `desktop_executor.py` and `file_executor.py` try
   the discovery index first (the real, exact path MARK found), falling back
   to the existing fuzzy-alias/PATH resolution and live filesystem walk
   respectively — never a regression for apps/files outside indexed scope.

## Consequences

- "Open Slack" now launches the actual installed binary
- File search returns from an index (single-digit ms) instead of a live walk
- The same architecture extends to any future "does X exist on this machine"
  question — MARK answers from its own index, not by asking again
- Scope (which directories, which scan sources) is explicit and editable, not
  implicit or hidden — `_ROOT_SUBDIRS` in `file_discovery.py` is the whole policy
- Platform-specific: Windows only today. macOS/Linux scanning returns `[]`
  gracefully rather than failing — a future MARK Mobile/Mac client would need
  its own discovery implementation, not this one

---

[[discovery_engine]] · [[action_system]] · [[ADR-0012-Universal-Action-System]] · [[ADR-0010-Universal-Actions]]
