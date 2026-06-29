# MARK III — Mesh API Reference

**Base URL:** `http://<desktop-ip>:8765`
**Authentication:** None (local network / Tailscale VPN)
**Format:** JSON

---

## GET /mesh/ping

Health check.

**Response:**
```json
{ "status": "ok", "core": "desktop-mark-core", "time": "2026-06-30T..." }
```

---

## GET /mesh/devices

All registered devices.

**Response:**
```json
{
  "devices": [
    {
      "device_id": "desktop-mark-core",
      "name": "Desktop (DESKTOP-OMJ0BL5)",
      "type": "desktop",
      "platform": "windows",
      "ip": "192.168.4.85",
      "battery": null,
      "active": true,
      "state": "active",
      "capabilities": ["reasoning", "qwen", "council", "reflex", "microphone", "speaker"]
    }
  ]
}
```

---

## GET /mesh/status

Mesh health + active device.

**Response:**
```json
{
  "online": 2,
  "offline": 0,
  "active_device": "desktop-mark-core",
  "uptime_s": 3600.0,
  "devices": [...]
}
```

---

## GET /mesh/presence

Active device + online list.

**Response:**
```json
{
  "active_device": { ... },
  "online_devices": [ ... ],
  "online_count": 2
}
```

---

## POST /mesh/register

Register a new device.

**Request:**
```json
{
  "device_id": "macbook-navids-macbo",
  "name": "MacBook Pro M1",
  "type": "macbook",
  "platform": "darwin",
  "ip": "192.168.4.86",
  "battery": 82.0,
  "active": true,
  "capabilities": ["microphone", "speaker", "display", "battery", "voice"]
}
```

**Response:**
```json
{ "status": "registered", "device": { ... } }
```

---

## POST /mesh/heartbeat

15-second keepalive from device.

**Request:**
```json
{ "device_id": "macbook-navids-macbo", "battery": 79.0, "active": true }
```

**Response:**
```json
{ "status": "ok", "device": { ... } }
```

---

## POST /mesh/voice

Audio relay from device microphone. Desktop processes and responds.

**Headers:**
- `Content-Type: audio/wav`
- `X-Device-ID: <device_id>`
- `Content-Length: <bytes>`

**Request body:** Raw WAV bytes (16kHz, mono, int16)

**Response:**
```json
{
  "text": "It's 3:05 AM.",
  "utterance": "What time is it?",
  "device_inactive": false
}
```

If `device_inactive: true`, the responding device should stay silent (desktop is active voice interface).

---

## POST /mesh/activate

Force a device to become the active voice interface (used by ⌘⌥M hotkey).

**Request:**
```json
{ "device_id": "macbook-navids-macbo" }
```

**Response:**
```json
{ "status": "activated", "active": "macbook-navids-macbo" }
```

---

## Device Listener API (port 8766)

Each device runs its own HTTP server on port 8766 to receive pushes from the brain.

### POST /mark/response

Brain pushes a text response to this device for TTS playback.

```json
{ "text": "It's 3:05 AM.", "source": "desktop-mark-core", "speak": true }
```

### POST /mark/conversation

Brain pushes conversation history handoff.

```json
{
  "text": "Continuing from desktop.",
  "history": [ ... ],
  "source_device": "Desktop"
}
```

### POST /mark/relay

Control the mic relay (start/stop).

```json
{ "action": "start" }   // resume mic relay
{ "action": "standby" } // pause mic relay
```
