# ADR-0003 — Device Mesh: Brain Owns State

**Status:** Accepted
**Date:** 2026-06-25

## Context

When the Mac device client managed its own active/standby state, both devices would sometimes respond simultaneously. Network switches caused the Mac's state to be lost. Race conditions between the relay lock and K66 processing caused double responses.

## Decision

**The desktop brain owns all device state. Devices never manage their own state.**

- `_active_voice_device` lives only in `always_listening_loop.py` on the desktop
- Mac always sends audio to `/mesh/voice` — desktop decides whether to respond
- Desktop returns `{"device_inactive": true}` to silence the Mac
- Desktop Piper TTS is gated on `is_desktop_active()` — never fires when Mac is active
- Voice mode switches via voice commands ("shift to Mac") or ⌘⌥M hotkey

## Alternatives Considered

1. **Mac manages its own state** — Rejected: state lost on crash/restart, race conditions
2. **Relay lock** — Rejected: race condition between K66 processing and relay arrival
3. **Both devices always silent except active** — Accepted: implemented via desktop state gate

## Consequences

- Mac always sends audio regardless of active state (slight bandwidth cost)
- Desktop must respond to all `/mesh/voice` requests (even to return empty)
- State survives Mac restarts (desktop never forgets)
- ⌘⌥M hotkey always works (physical override via `/mesh/activate`)

## Future Impact

Any new device (iPhone, Watch) follows the same pattern: it always sends to the brain, the brain decides. No device-side state management.

---

[[device_mesh]] · [[system_overview]] · [[mesh_api]] · [[ADR-0001-Mark-Operating-System]] · [[future]] · [[cognitive_pipeline]]
