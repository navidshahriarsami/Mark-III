# ADR-0010 — Universal Actions Architecture (Planned)

**Status:** Planned — Phase 17
**Date:** 2026-06-28

## Context

MARK can speak and reason but cannot yet DO anything. "Open Chrome", "take a screenshot", "set a reminder" all require desktop automation.

## Planned Decision

Build a Universal Actions layer that executes commands on any connected device.

```
Voice command → Intent (complex/action) → Action Router → Executor → Response
```

Action executors:
- `desktop_executor.py` — open apps, screenshots, file operations
- `browser_executor.py` — URL, tab management
- `notification_executor.py` — system notifications, reminders
- `file_executor.py` — file search, open, read

## Design Rules

- Actions require confirmation for high-stakes operations (delete, send, purchase)
- `SudoApprovalModal` in future MARK Mobile iOS app handles approval from phone
- All executed actions are logged in vector memory as automation patterns
- Repeated patterns become learned workflows (via Learning Engine)

## Status

Not yet implemented. Scaffolding exists in `app/services/actions/`. Implementation is Phase 17.
