# Guardian — Handoff (continue development here)

A motion/face security monitor built on an **Insta360 Link** webcam that also
behaves like a **living creature** — its gimbal (pan/tilt/roll + zoom) is driven
by a "personality" engine so it looks around, cocks its head, pleads, and locks
onto faces. Runs as a standalone Python process; live view + control over HTTP.

The current focus is **tuning the creature's personality/movement** — that's the
fun part the owner is iterating on. Read this whole file before changing motion.

---

## Run / restart

```bash
cd guardian
pip install -r requirements.txt          # opencv-python, numpy, fastapi, uvicorn, requests
python guardian.py                        # starts camera + web server on :8080
```

Restart after any code change (Python doesn't hot-reload). On Windows, kill the
running process first:
```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -like '*guardian.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Freeze all movement (static webcam) with env `LIFE=0`.

---

## Files

| File | Role |
|---|---|
| `guardian.py` | Main. Camera loop, motion/face detection, gimbal command application, FastAPI web server (live view, play panel, control endpoints, ntfy). |
| `personality.py` | **The creature.** Gesture repertoire + state machine that outputs pan/tilt/roll/zoom each tick. This is what you tune. |
| `yunet.onnx` | Face detector model (OpenCV 5 `FaceDetectorYN`). Downloaded from OpenCV Zoo. |
| `README.md` | User-facing setup (ntfy, Tailscale, arming). |
| `start_guardian.bat` | Silent launcher (also copied to Startup folder for auto-start). |

---

## HARDWARE FACTS (hard-won — do not re-litigate)

Camera: **Insta360 Link**, `cv2.VideoCapture(0, cv2.CAP_DSHOW)`, 1280x720.
Gimbal driven via `cap.set(cv2.CAP_PROP_*, value)`:

| Axis | Property | "Creature" meaning | Real range | Notes |
|---|---|---|---|---|
| Pan | `CAP_PROP_PAN` | turn / "no" (left-right) | ~ -72 .. +78 | has position feedback; tracks manual movement |
| Tilt | `CAP_PROP_TILT` | nod / "yes" (up-down) | -30 .. +82 physical | **capped to +32 in code** so it doesn't stare at ceiling |
| Roll | `CAP_PROP_ROLL` | ear-to-shoulder head-cock | **±100 HARD CAP** | software-only (resists hand); NO manual feedback |
| Zoom | `CAP_PROP_ZOOM` | lean in on a face | 100 (1x) .. 400 (4x) | digital; not physically movable |

**Critical limits (already investigated exhaustively — don't retry):**
- **Roll is hard-capped at ±100** by the camera firmware. `set(110+)` is rejected.
  We use an *overshoot* trick: command `ROLL_PUSH=125` so the eased value actually
  reaches and pins at the physical 100 (easing only asymptotes, so commanding 100
  lands at ~95).
- The gimbal *can* physically roll ~180° — but **only** during its firmware boot
  calibration, which fires on **physical USB replug only**. Not commandable:
  UVC caps at 100; libusb is blocked by the Windows webcam driver ("Entity not
  found"); the Insta360 app itself has no roll control; software PnP disable/enable
  ("soft replug") fails with generic error. Full 180° = manual cable replug only.
  Don't spend time here again.

---

## Movement control model (READ BEFORE TUNING personality.py)

- **Gesture system:** `Personality.update(faces, w, h, now)` returns
  `(pan, tilt, roll, zoom, following)` each tick. Idle behavior is a **queue of
  Waypoints**; when the queue empties it picks a new gesture by weighted random
  (`_WEIGHTS`), never repeating the same one twice.
- **Waypoint** = `(tp, tt, ease, dwell, timeout, tr)` — target pan/tilt, ease
  (0..1 approach speed), dwell (seconds to hold once arrived), timeout, target roll.
- **Two rules the owner cares about a lot:**
  1. **Pan and tilt must NEVER move in the same waypoint** (turning-while-nodding
     looks "mad"). Roll *may* accompany either. Verified 0% pan+tilt overlap.
  2. **Roll is the favorite** — keep it prominent, deep (near ±100), and SLOW
     (few big held swings, not fast shimmy). "More axis, less frequency."
- **FOLLOW mode:** when a face is present, it locks on and centers the face
  (closed loop on the *image*, not gimbal position — position readback is
  unreliable), levels roll, and zooms to ~2x. Face lost >2.5s → resume wander.

### Command-rate tuning (in guardian.py camera loop)
Gimbal `cap.set` calls are throttled: **every 3rd frame** with a **dead-band**
(pan/tilt 0.4, roll 0.5, zoom 4.0) via `_last_sent`. This was carefully dialed:
- too frequent (every frame) → gimbal **shakes** mid-move
- too sparse (every 5th) → **laggy**
- every 3rd + dead-band → the sweet spot. Change cautiously.

### Current gestures (personality.py `_gesture`)
Idle: `eye` (look at you), `plead` (deep slow roll beg), `sway` (gentle roll),
`cock` (head-cock), `investigate` (turn→scan up/down→big HUH roll — signature),
`alert` (snap→freeze→ignore), `turn` (pan w/ roll lean), `look` (rare nod),
`flop` (full roll), `stare` (freeze).
On-demand (via `force(name)`): `yes`, `no`, `huh`, `center` + all the above.

### "Look at you" level
`LOOK_AT_YOU` (personality.py, currently -6) is the resting tilt so it meets the
owner's eyes, not the ceiling. Tunable **live** via `POST /eyelevel?tilt=N` — the
owner should dial this to their camera height; bake the winning value into the const.

---

## HTTP API (all on :8080)

| Endpoint | Purpose |
|---|---|
| `GET /` | live MJPEG view |
| `GET /play` | **play panel** — buttons to trigger gestures on the phone |
| `GET /help` | command reference (returns addresses too) |
| `POST /do?move=<name>` | trigger a named gesture (yes/no/huh/plead/sway/investigate/eye/center...) |
| `POST /eyelevel?tilt=N` | live-tune the "look at you" tilt |
| `POST /arm` `/disarm` | arm/disarm motion recording+alerts |
| `GET /status` `/health` | state |
| `POST /look?pan=&tilt=` | raw manual gimbal (calibration; only meaningful with LIFE=0) |

Also: **ntfy** control (subscribe/publish `arm`/`disarm`/`help` to a topic — works
on any internet, no Tailscale) and motion alerts. Live *video* view is over
Tailscale (`http://100.94.162.25:8080`) or LAN. See README.

---

## Security-monitor side (works, secondary to the creature right now)
- **Disarmed by default.** Armed = a spotted FACE (while armed) records a clip to
  `clips/` and sends an alert. `MARK-first` notification then ntfy fallback when away.
- Face recognition to tell the OWNER from an intruder is a **planned v2** — the
  hook is where `following` triggers recording. OpenCV 5 ships `FaceRecognizerSF`
  (SFace) for exactly this.

---

## State / next steps
- **Nothing is committed to git yet** — this whole project is uncommitted. Consider
  an initial commit.
- Owner is actively tuning the **personality feel** (roll depth/hold, timing, the
  investigate/plead/sway behaviors, "look at you" level).
- There is an OPTIONAL integration with a separate project ("MARK III" at
  `../Mark III/brain-server`) — a voice command "guardian" and a `/guardian/alert`
  endpoint. Ignore unless asked; the creature is self-contained in this folder.

## Good first move for the new session
Read `personality.py` fully, run `python guardian.py`, open `/play` on a phone,
and trigger `plead` / `investigate` / `huh` to see the current character before
changing anything.
