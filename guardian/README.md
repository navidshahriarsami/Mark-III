# Guardian v1 — motion monitor

Insta360 Link → motion detection → records clip + pushes to your phone.
Live view over Tailscale from anywhere. Motion-only for now; face recognition later.

## Setup

```bash
cd guardian
pip install -r requirements.txt
```

**1. Find your camera index** (Insta360 Link may not be 0):
```bash
python guardian.py --list
```
Set the right one: `set CAM_INDEX=1` (or edit the constant).

**2. Phone push (fallback only) — install ntfy in Safari/app:**
- Install the **ntfy** app (iOS, free), or add ntfy.sh to your Safari home screen
- Subscribe to the exact topic printed on startup (default `mark-guardian-navid-9271`)
- Change `NTFY_TOPIC` to something private — public topics are guessable

**3. Run:**
```bash
python guardian.py
```

**4. Live view on phone** — over Tailscale (works on cellular, anywhere):
```
http://100.94.162.25:8080
```
(that's your desktop's Tailscale IP). On home WiFi you can also use the LAN IP.

## Arming — voice or HTTP

Guardian starts **disarmed** (live view works, but no recording or alerts).
It only monitors when armed — which means **zero ntfy usage unless you've
actively armed it**.

- **Voice (via MARK):** say **"guardian"** to arm, **"disarm guardian"** to stop,
  **"guardian status"** to check.
- **HTTP:** `POST /arm`, `POST /disarm`, `GET /status`

## Notification path — MARK first, ntfy only when away

When motion fires while armed, Guardian notifies **MARK's brain first**
(free, local desktop toast + spoken alert). It only falls back to **ntfy**
(phone push) when MARK reports you're **away from the desktop**, or MARK is
unreachable. So the free-tier ntfy quota is only touched when you're actually
out of the house — not while you're sitting at your desk.

## Tuning

| Constant | Effect |
|---|---|
| `MOTION_AREA` | Lower = more sensitive (default 1500) |
| `MOTION_COOLDOWN_S` | Min seconds between phone alerts (default 30) |
| `RECORD_SECONDS` | Clip length per event (default 20) |
| `MARK_MESH` | MARK brain URL (default `http://127.0.0.1:8765`) |

Clips land in `guardian/clips/`. Snapshot is attached to each phone alert.

## v2 (planned)

- Face recognition — enroll your face, only alert on *unknown* faces
  (drop-in at the `TODO(face)` line in `guardian.py`)
- Phone-presence gating — if your phone's on the network, treat motion as safe
- Fold into MARK as a reflex module + mesh notification
