"""
Guardian — motion-triggered camera monitor (v1)

Insta360 Link (or any UVC webcam) → motion detection → record clip + phone push.
Live MJPEG view over Tailscale, viewable from your phone anywhere.

v1 scope: MOTION ONLY. Records + alerts on any motion.
Face recognition ("anybody but me") is a planned v2 — the trigger point is
marked TODO(face) below so it drops in without restructuring.

Run:  python guardian.py
View: http://<desktop-tailscale-ip>:8080  from your phone
"""
from __future__ import annotations

import os
import time
import threading
import datetime as dt
from pathlib import Path

import cv2
import numpy as np
import requests
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse, HTMLResponse
import uvicorn

# ─────────────────────────── Config ────────────────────────────
CAMERA_INDEX      = int(os.getenv("CAM_INDEX", "0"))     # find yours: python guardian.py --list
PORT              = int(os.getenv("PORT", "8080"))
CLIPS_DIR         = Path(__file__).parent / "clips"

MOTION_AREA       = 1500     # (legacy) min changed-pixel-area for frame-diff motion
MOTION_COOLDOWN_S = 30       # min seconds between notifications (anti-spam)
RECORD_SECONDS    = 20       # clip length once a face is spotted
WARMUP_FRAMES     = 30       # frames to let the camera boot-calibrate before we drive it
FIRMWARE_WAKE_S   = 7.0      # seconds to let the camera's OWN wake movement (Smart
                             # Adjustment face-search) play before the personality drives it

# "Alive head" — 3-axis gimbal motion (pan/tilt/roll) + zoom-on-follow.
# Re-enabled now that a cooler handles the servo heat. The gesture mix leans on
# "stare"/"drift" so it rests between moves (natural + servo-friendly). Set
# LIFE=0 to freeze it to a static webcam anytime.
LIFE_ENABLED      = int(os.getenv("LIFE", "1"))

# MARK brain — Guardian notifies MARK FIRST (free, local desktop toast).
# ntfy is only used as a fallback when you're away from the desktop.
MARK_MESH_URL     = os.getenv("MARK_MESH", "http://127.0.0.1:8765")

# ntfy.sh — two topics:
#  ALERT topic: Guardian PUSHES motion alerts here (you subscribe on your phone).
#  CTRL  topic: Guardian LISTENS here; your phone PUBLISHES "arm"/"disarm" to
#               control Guardian from any internet (WiFi or cellular) — no
#               Tailscale needed.
# Change both to private/unguessable values (public namespace = anyone who knows
# the CTRL topic can arm/disarm). Control messages are tiny + rare (well under
# the free 250/day). Live VIDEO still uses Tailscale — ntfy can't stream video.
NTFY_TOPIC        = os.getenv("NTFY_TOPIC", "mark-guardian-navid-9271")
NTFY_URL          = f"https://ntfy.sh/{NTFY_TOPIC}"
NTFY_CTRL_TOPIC   = os.getenv("NTFY_CTRL", "mark-guardian-ctrl-navid-4417")
NTFY_CTRL_URL     = f"https://ntfy.sh/{NTFY_CTRL_TOPIC}/json"

# ─────────────────────────── State ─────────────────────────────
_latest_jpeg: bytes | None = None
_lock = threading.Lock()
_last_notify = 0.0
_recording = False
_armed = False               # disarmed by default — no alerts until "guardian" arms it
_play = {"move": None}       # inbox: /do sets a named gesture; camera_loop plays it
_life = {"on": bool(LIFE_ENABLED)}   # runtime: is the creature alive (moving)?
CLIPS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Guardian")


# ─────────────────────── Camera worker ─────────────────────────
def _open_camera_blocking():
    """
    Open the REAL camera, retrying patiently until it delivers a full-resolution
    frame. Handles boot timing and unplug/replug (the device can be slow to
    re-enumerate on index 0). Critically, it rejects the 640x480 fallback stream
    that some indices expose — that fallback delivers video but CANNOT drive the
    gimbal, which is what left the creature stuck looking down after a replug.
    """
    attempt = 0
    while True:
        # Preferred: the real 1280-wide device (has gimbal control). The Link
        # sometimes defaults to a 640x480 stream (esp. after a replug), so we
        # explicitly REQUEST 1280x720 before judging the frame.
        for idx in (CAMERA_INDEX, 0, 1, 2):
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            ok, f = (cap.read() if cap.isOpened() else (False, None))
            if ok and f is not None and f.shape[1] >= 1000:
                # Warn if gimbal control is offline (replug can knock it out).
                gimbal_ok = cap.get(cv2.CAP_PROP_ROLL) != -1
                note = "" if gimbal_ok else "  [GIMBAL OFFLINE — replug the USB to restore]"
                print(f"[guardian] camera open index {idx} {f.shape[1]}x{f.shape[0]} (after {attempt} retries){note}")
                return cap
            cap.release()
        attempt += 1
        # Last resort after many tries: accept any working stream so we at least
        # keep video, even if the gimbal can't be driven.
        if attempt >= 6:
            for idx in (CAMERA_INDEX, 0, 1, 2):
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                ok, f = (cap.read() if cap.isOpened() else (False, None))
                if ok and f is not None:
                    print(f"[guardian] camera open (fallback, no gimbal?) index {idx}")
                    return cap
                cap.release()
        print(f"[guardian] real camera not ready (attempt {attempt}) — retrying in 3s...")
        time.sleep(3)


def camera_loop() -> None:
    global _latest_jpeg, _last_notify, _recording

    cap = _open_camera_blocking()
    _manual_cap["cap"] = cap   # expose handle for /look manual control

    # Face detector (YuNet DNN, OpenCV 5) + the "alive head" controller.
    from personality import Personality, Face, PAN_SIGN, TILT_SIGN, ROLL_SIGN
    _model = str(Path(__file__).parent / "yunet.onnx")
    detector = cv2.FaceDetectorYN.create(_model, "", (320, 320), score_threshold=0.7)
    pet = Personality()

    frame_no = 0
    faces: list = []
    _last_sent = {"pan": None, "tilt": None, "roll": None, "zoom": None}

    # GOOD MORNING = the camera's OWN wake movement (Smart Adjustment: it pitches
    # up/down to find you, then centers your face). We keep the video stream alive
    # but send NO gimbal commands during this window, so the firmware's wake plays
    # untouched. Then the personality takes over.
    #   Requires in the Insta360 Link Controller app:
    #     • Smart Adjustment  = ON   (so it does the wake movement)
    #     • AI/subject tracking = OFF (so it stops fighting the personality after)
    print("[guardian] letting the camera's own wake movement play...")
    _wake_end = time.monotonic() + FIRMWARE_WAKE_S
    while time.monotonic() < _wake_end:
        cap.read()          # keep stream alive; do NOT drive the gimbal
        time.sleep(0.03)
    print("[guardian] wake done — personality taking over")

    read_fails = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            read_fails += 1
            # A handful of dropped frames is normal; sustained failure means the
            # camera was unplugged/reset — reopen it (handles unplug→replug).
            if read_fails >= 25:
                print("[guardian] camera lost — reconnecting...")
                try:
                    cap.release()
                except Exception:
                    pass
                cap = _open_camera_blocking()
                _manual_cap["cap"] = cap
                _last_sent.update({"pan": None, "tilt": None, "roll": None, "zoom": None})
                read_fails = 0
            else:
                time.sleep(0.1)
            continue
        read_fails = 0
        frame_no += 1
        h, w = frame.shape[:2]

        # Detect faces every 3rd frame with YuNet (fast DNN).
        if _life["on"] and frame_no % 3 == 0:
            detector.setInputSize((w, h))
            _n, dets = detector.detect(frame)
            faces = []
            if dets is not None:
                for d in dets:
                    x, y, fw, fh = int(d[0]), int(d[1]), int(d[2]), int(d[3])
                    faces.append(Face(x, y, fw, fh))

        # Play request from /do — trigger a named gesture on demand.
        mv = _play["move"]
        if mv:
            _play["move"] = None
            try:
                pet.force(mv)
            except Exception:
                pass

        following = False
        if _life["on"]:
            # Drive the alive head. FOLLOW when a face is present, else WANDER.
            pan, tilt, roll, zoom, following = pet.update(faces, w, h)
            # Apply pan/tilt/roll/zoom at a LOW rate with a dead-band. Streaming
            # many tiny position updates makes the Link's own motion controller
            # stutter mid-move; sending ~6/s and only when an axis actually moved
            # lets the gimbal glide smoothly between our targets.
            if frame_no % 3 == 0:
                for prop, val, key, band in (
                    (cv2.CAP_PROP_PAN,  pan  * PAN_SIGN,  "pan",  0.4),
                    (cv2.CAP_PROP_TILT, tilt * TILT_SIGN, "tilt", 0.4),
                    (cv2.CAP_PROP_ROLL, roll * ROLL_SIGN, "roll", 0.5),
                    (cv2.CAP_PROP_ZOOM, zoom,             "zoom", 4.0),
                ):
                    last = _last_sent[key]
                    if last is None or abs(val - last) >= band:
                        try:
                            cap.set(prop, float(val))
                            _last_sent[key] = val
                        except Exception:
                            pass

        # Draw face boxes
        for f in faces:
            col = (0, 0, 255) if following else (0, 220, 0)
            cv2.rectangle(frame, (f.x, f.y), (f.x + f.w, f.y + f.h), col, 2)

        # Overlays
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, stamp, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 255, 0), 2)
        state = "◉ FOLLOWING" if following else ("● watching" if _armed else "○ idle")
        cv2.putText(frame, state, (10, 55), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (0, 0, 255) if following else (0, 200, 0), 2)

        # Publish latest frame for the live stream
        ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok2:
            with _lock:
                _latest_jpeg = buf.tobytes()

        # Trigger = a FACE spotted while ARMED. (A moving head breaks frame-diff
        # motion detection, and your intent is face-based anyway. Face-recognition
        # to tell YOU from a stranger drops in here later — TODO(face-id).)
        if _armed and following and not _recording:
            now = time.time()
            if now - _last_notify >= MOTION_COOLDOWN_S:
                _last_notify = now
                threading.Thread(target=notify, args=(frame.copy(),), daemon=True).start()
                threading.Thread(target=record_clip, args=(cap,), daemon=True).start()


# ─────────────────────── Record + notify ───────────────────────
def record_clip(cap: cv2.VideoCapture) -> None:
    global _recording
    _recording = True
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        fps = 20
        name = CLIPS_DIR / f"motion_{dt.datetime.now():%Y%m%d_%H%M%S}.mp4"
        writer = cv2.VideoWriter(str(name), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        print(f"[guardian] recording -> {name.name}")
        end = time.time() + RECORD_SECONDS
        while time.time() < end:
            with _lock:
                jpeg = _latest_jpeg
            if jpeg:
                frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    writer.write(cv2.resize(frame, (w, h)))
            time.sleep(1 / fps)
        writer.release()
        print(f"[guardian] saved {name.name}")
    finally:
        _recording = False


def notify(frame: np.ndarray) -> None:
    """
    MARK-first notification. Tries MARK's brain (free, local desktop toast);
    only falls back to ntfy.sh (phone push) if MARK is unreachable OR reports
    you're away from the desktop. This keeps ntfy usage near zero.
    """
    msg = "Guardian: motion detected while armed."

    # 1. MARK brain first — free, local, no external service.
    # MARK replies {"owner_away": bool}. If it's reachable and you're home,
    # the desktop toast is enough and we skip ntfy entirely.
    use_ntfy = True
    try:
        r = requests.post(f"{MARK_MESH_URL}/guardian/alert",
                          json={"message": msg}, timeout=3)
        data = r.json() if r.ok else {}
        use_ntfy = bool(data.get("owner_away", False))
        print(f"[guardian] alerted via MARK (owner_away={use_ntfy})")
    except Exception:
        use_ntfy = True   # can't reach MARK → assume away → phone push

    # 2. ntfy fallback — ONLY when away/unreachable.
    if use_ntfy:
        try:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            requests.post(
                NTFY_URL,
                data=buf.tobytes() if ok else b"",
                headers={
                    "Title": "Guardian: motion detected",
                    "Priority": "high",
                    "Tags": "rotating_light",
                    "Filename": "snapshot.jpg",
                },
                timeout=10,
            )
            print("[guardian] phone push sent (ntfy fallback)")
        except Exception as e:
            print(f"[guardian] ntfy fallback failed: {e}")


# ─────────────────── ntfy control listener ─────────────────────
def ntfy_control_loop() -> None:
    """
    Subscribe to the ntfy CONTROL topic and react to commands published from
    your phone. Lets you arm/disarm over plain cellular with no Tailscale.

    Publish from phone (iOS Shortcut / Safari):
        POST https://ntfy.sh/<CTRL_TOPIC>  body: "arm" | "disarm" | "status"
    """
    import json
    global _armed
    while True:
        try:
            # Short read timeout so a half-dead stream reconnects fast (ntfy sends
            # keepalives ~every 45s; no data for 75s ⇒ stale ⇒ reconnect). Also
            # force a fresh reconnect every few minutes so it can never sit on a
            # silently-dead connection and miss commands.
            conn_start = time.monotonic()
            with requests.get(NTFY_CTRL_URL, stream=True, timeout=(10, 75)) as r:
                print(f"[guardian] listening for control on ntfy topic: {NTFY_CTRL_TOPIC}")
                for line in r.iter_lines():
                    if time.monotonic() - conn_start > 240:
                        break     # periodic proactive reconnect
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    if evt.get("event") != "message":
                        continue
                    cmd = (evt.get("message") or "").strip().lower()
                    if cmd in ("wake", "start", "pet", "hello", "come", "alive", "wake up"):
                        _life["on"] = True
                        _play["move"] = "wake"          # good-morning greeting
                        print("[guardian] creature WAKE (via ntfy)")
                        _ntfy_ack("Your pet is awake 🐾")
                    elif cmd in ("sleep", "rest", "freeze", "still", "nap"):
                        _life["on"] = False
                        print("[guardian] creature SLEEP (via ntfy)")
                        _ntfy_ack("Your pet is resting 😴")
                    elif cmd in ("arm", "activate", "guardian"):
                        _armed = True
                        print("[guardian] ARMED (via ntfy)")
                        _ntfy_ack("Guardian armed.")
                    elif cmd in ("disarm", "stand down"):
                        _armed = False
                        print("[guardian] DISARMED (via ntfy)")
                        _ntfy_ack("Guardian disarmed.")
                    elif cmd == "status":
                        _ntfy_ack(f"Pet: {'awake' if _life['on'] else 'resting'} · "
                                  f"Guard: {'armed' if _armed else 'disarmed'}")
                    elif cmd in ("help", "commands", "?"):
                        _ntfy_ack(_help_text())
        except Exception as e:
            print(f"[guardian] ntfy control reconnecting: {e}")
            time.sleep(5)   # reconnect on drop


def _ntfy_ack(text: str) -> None:
    """Confirm a control action back to your phone via the ALERT topic."""
    try:
        requests.post(NTFY_URL, data=text.encode("utf-8"),
                      headers={"Title": "Guardian", "Priority": "low", "Tags": "shield"},
                      timeout=8)
    except Exception:
        pass


def get_addresses() -> tuple[str, str]:
    """
    Return (lan_ip, tailscale_ip) of this PC.
      lan_ip       — home-WiFi / LAN address (192.168.x, 10.x, 172.16-31.x)
      tailscale_ip — 100.64-127.x address, reachable from anywhere via Tailscale
    Either may be "" if unavailable.
    """
    import socket
    lan = ""
    tail = ""
    try:  # default-route local address (the physical NIC, not Tailscale)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    try:  # scan all bound IPv4s for the Tailscale CGNAT range
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            o = ip.split(".")
            if o[0] == "100" and o[1].isdigit() and 64 <= int(o[1]) <= 127:
                tail = ip
                break
    except Exception:
        pass
    # if the default-route address turned out to be the Tailscale one, don't
    # double-report it as LAN
    if lan == tail:
        lan = ""
    return lan, tail


def _help_text() -> str:
    lan, tail = get_addresses()
    lines = [
        "🐾  YOUR PET — reply with one word:",
        "",
        '  Wake the creature     →  write "wake"',
        '  Let it rest           →  write "sleep"',
        '  Guard your space      →  write "arm"',
        '  Stand down            →  write "disarm"',
        '  Check the state       →  write "status"',
        '  See this again        →  write "help"',
        "",
        "📹  Watch live:",
    ]
    if tail:
        lines.append(f"  Anywhere    →  http://{tail}:{PORT}")
    if lan:
        lines.append(f"  Home WiFi   →  http://{lan}:{PORT}")
    if not (tail or lan):
        lines.append(f"  http://<this-pc-ip>:{PORT}")
    return "\n".join(lines)


# ─────────────────────────── Web ───────────────────────────────
def mjpeg_generator():
    while True:
        with _lock:
            jpeg = _latest_jpeg
        if jpeg:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
        time.sleep(0.05)


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><html><head><meta name=viewport
    content="width=device-width,initial-scale=1"><title>Guardian</title>
    <style>body{margin:0;background:#000;font-family:system-ui;color:#eee}
    .bar{padding:10px 14px;background:#111;font-weight:600;display:flex;
    justify-content:space-between;align-items:center}
    .bar a{color:#6cf;text-decoration:none;font-weight:500}
    img{width:100%;height:auto;display:block}</style></head>
    <body><div class=bar><span>🛡️ Guardian — live</span>
    <a href="/help">help</a></div>
    <img src="/stream"></body></html>"""


_HELP = {
    "guardian": "motion-triggered camera monitor",
    "http_control": {
        "POST /arm":     "start monitoring (record + alert on motion)",
        "POST /disarm":  "stop monitoring",
        "GET  /status":  "armed / recording state",
        "GET  /health":  "camera + recording + armed",
        "GET  /help":    "this",
    },
    "ntfy_control (any internet — WiFi or cellular, no Tailscale)": {
        "how": f"POST a message to https://ntfy.sh/{NTFY_CTRL_TOPIC}",
        "arm":     "body: arm | on | activate",
        "disarm":  "body: disarm | off | stop",
        "status":  "body: status",
        "help":    "body: help",
    },
    "phone_alerts": {
        "subscribe_topic": NTFY_TOPIC,
        "note": "Guardian pushes motion snapshots here when armed + you're away.",
    },
    "mark_voice (when home, MARK running)": {
        "guardian":         "arm",
        "disarm guardian":  "disarm",
        "guardian status":  "report state",
    },
}


@app.get("/help")
def help_page():
    lan, tail = get_addresses()
    return {
        **_HELP,
        "live_view": {
            "anywhere_tailscale": f"http://{tail}:{PORT}/" if tail else "Tailscale not detected",
            "home_wifi_lan":      f"http://{lan}:{PORT}/" if lan else "LAN not detected",
            "note": "both work on WiFi or cellular; Tailscale is the works-anywhere one.",
        },
    }


@app.get("/stream")
def stream():
    return StreamingResponse(mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/health")
def health():
    with _lock:
        alive = _latest_jpeg is not None
    return {"camera": "live" if alive else "starting",
            "recording": _recording, "armed": _armed}


@app.post("/arm")
def arm():
    global _armed
    _armed = True
    print("[guardian] ARMED")
    return {"armed": True}


@app.post("/disarm")
def disarm():
    global _armed
    _armed = False
    print("[guardian] DISARMED")
    return {"armed": False}


@app.get("/status")
def status():
    return {"armed": _armed, "recording": _recording, "life": _life["on"]}


# ── Play: trigger named gestures on demand ──────────────────────
_MOVES = ["wake", "plead", "sway", "investigate", "huh", "yes", "no", "eye"]


@app.post("/do")
def do(move: str):
    """Make the creature perform a named gesture."""
    m = move.strip().lower()
    if m not in _MOVES:
        return {"error": f"unknown move '{m}'", "moves": _MOVES}
    _play["move"] = m
    return {"doing": m}


@app.post("/eyelevel")
def eyelevel(tilt: float):
    """
    Live-tune where 'looking at you' is. Send different tilt values until it
    meets your eyes instead of the ceiling: POST /eyelevel?tilt=-10
    """
    try:
        from personality import set_eye_level
        set_eye_level(tilt)
        _play["move"] = "eye"   # immediately look there so you can see it
        return {"look_at_you_tilt": tilt}
    except Exception as e:
        return {"error": str(e)}


@app.get("/play", response_class=HTMLResponse)
def play_page():
    buttons = "".join(
        f'<button onclick="fetch(\'/do?move={m}\',{{method:\'POST\'}})">{m.upper()}</button>'
        for m in _MOVES)
    return f"""<!doctype html><html><head><meta name=viewport
    content="width=device-width,initial-scale=1"><title>Play</title>
    <style>body{{margin:0;background:#0b0b0b;font-family:system-ui;color:#eee;
    text-align:center}} .bar{{padding:12px;background:#111;font-weight:600}}
    img{{width:100%;max-height:52vh;object-fit:contain;background:#000}}
    .pad{{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px}}
    button{{padding:18px;font-size:18px;font-weight:700;border:0;border-radius:14px;
    background:#1e6feb;color:#fff}} button:active{{background:#1652b0}}
    .hint{{color:#888;font-size:13px;padding:0 14px 16px}}</style></head>
    <body><div class=bar>🐾 Play with your creature</div>
    <img src="/stream">
    <div class=pad>{buttons}</div>
    <div class=hint>YES = nod · NO = shake · HUH = head-cock · CENTER = face forward</div>
    </body></html>"""


# Manual gimbal control — for calibrating range/direction while watching the
# live view, and for the "manual pan" phone controls.
_manual_cap = {"cap": None}


@app.post("/look")
def look(pan: float = 0.0, tilt: float = 0.0):
    """
    Absolute gimbal move for calibration/manual control.
    Usage: POST /look?pan=15&tilt=-5   (units match personality.py bounds)
    Note: only meaningful when LIFE is off, else the pet immediately overrides.
    """
    import cv2 as _cv2
    c = _manual_cap["cap"]
    if c is None:
        return {"error": "camera not ready"}
    try:
        c.set(_cv2.CAP_PROP_PAN, float(pan))
        c.set(_cv2.CAP_PROP_TILT, float(tilt))
        return {"pan": pan, "tilt": tilt}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────── Main ──────────────────────────────
if __name__ == "__main__":
    import sys
    if "--list" in sys.argv:
        print("Probing camera indices 0-5...")
        for i in range(6):
            c = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            print(f"  index {i}: {'FOUND' if c.isOpened() else '-'}")
            c.release()
        sys.exit(0)

    threading.Thread(target=camera_loop, daemon=True).start()
    threading.Thread(target=ntfy_control_loop, daemon=True).start()
    print(f"[guardian] live view: http://<your-tailscale-ip>:{PORT}")
    print(f"[guardian] alert topic:   {NTFY_TOPIC}")
    print(f"[guardian] control topic: {NTFY_CTRL_TOPIC}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
