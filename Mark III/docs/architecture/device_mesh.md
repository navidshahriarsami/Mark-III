# MARK III — Device Mesh Architecture

## Purpose

The Device Mesh allows MARK to exist across multiple devices simultaneously. The desktop is always the brain. Every other device is an interface.

## Design Principle

> The desktop is the permanent intelligence. Every other device is a portal into MARK.

**One brain. Multiple bodies.**

## Architecture

```
MARK Core (Desktop)
    Port 8765 — REST API
    ├── /mesh/register    POST — device registration
    ├── /mesh/heartbeat   POST — 15s keepalive + battery + GPS
    ├── /mesh/devices     GET  — all registered devices
    ├── /mesh/status      GET  — mesh health + active device
    ├── /mesh/presence    GET  — active device + online list
    ├── /mesh/voice       POST — audio relay from remote device
    ├── /mesh/activate    POST — keyboard hotkey → set active device
    └── /mesh/ping        GET  — connectivity check

MacBook Pro M1 (Client)
    Port 8766 — Inbound listener
    ├── /mark/response    POST — receive text, Samantha speaks
    ├── /mark/conversation POST — receive conversation handoff
    └── /mark/relay       POST — start/stop mic relay
```

## Device Registry

- Stored in `mesh_devices.json`
- Each device has: device_id, name, type, platform, ip, battery, state, capabilities
- States: `active | online | idle | offline`
- Heartbeat timeout: 45 seconds (3 missed 15s heartbeats)

## Active Device State

**Critical architectural decision:** Active device state is owned exclusively by the desktop brain. Devices never manage their own state.

- Desktop tracks which device is the active voice interface
- `_active_voice_device` variable in `always_listening_loop.py`
- All queries from inactive devices receive `{"device_inactive": true}` → silent response
- All queries from active device receive full processing + response

## Voice Mode Switching

```
"Shift to Mac"    → desktop Piper silent, Mac Samantha speaks
"Shift to desktop" → Mac relay pauses, desktop K66 + Piper resumes
⌘⌥M hotkey       → POST /mesh/activate → forces Mac active
```

## Devices (Current & Planned)

| Device | Status | Capabilities |
|---|---|---|
| Desktop (MARK Core) | ✅ Live | All intelligence |
| MacBook Pro M1 | ✅ Live | Mic relay, Samantha TTS |
| iPhone 16 | 📋 Phase 16B | GPS, voice relay, emergency SOS |
| Apple Watch | 📋 Phase 16C | Presence, quick replies |
| Smart Glasses | 📋 Phase 19 | AR overlay, vision AI |
| ESP32 | 📋 Phase 17B | IoT sensors, environment |
| TI IWR6843ISK | 📋 Phase 17A | 60GHz radar presence |

## Tailscale (Current) vs MARK Connect (Future)

Current: Tailscale VPN provides cross-network connectivity.
Future (Phase 17A): Self-hosted WireGuard relay (`MARK Connect`) replaces Tailscale for commercial deployments. Zero third-party dependency.

## Related Documents

- [System Overview](system_overview.md)
- [Presence Fusion](../api/presence_fusion.md)
