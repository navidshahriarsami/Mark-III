"""
Guardian — Personality / "alive head" motion controller.

Makes the Insta360 Link behave like a curious little creature. Two states:

  WANDER — organic idle motion built from a REPERTOIRE of distinct gestures,
           not one repeating profile. Mostly calm drifting, with occasional
           darts, head-cocks, curious up/down looks, slow searching scans,
           attentive stares, and a playful "recalibrate" shimmy. Each gesture
           has its own speed + rhythm, and the same one never fires twice in a
           row, so the behavior stays surprising and pet-like.

  FOLLOW — a face is present: lock on and keep it centered. Closed loop on the
           IMAGE (face offset), so it does NOT rely on the gimbal's unreliable
           position readback.

Bounds/signs are best-guesses until calibrated by watching the live view.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

# ── Gimbal range + direction (measured by hand-moving the real camera) ──────
PAN_MIN,  PAN_MAX  = -70.0, 75.0     # turn "no" — nearly ±75 of real travel
TILT_MIN, TILT_MAX = -28.0, 32.0     # capped upward so it doesn't gaze at the ceiling
ROLL_MIN, ROLL_MAX = -100.0, 100.0   # ear-to-shoulder head tilt — full ±100 (real max)
ROLL_PUSH          = 125.0           # command past the limit so eased motion actually
                                     # reaches the physical ±100 and holds there solidly
ZOOM_MIN, ZOOM_MAX = 100.0, 400.0    # 1x .. 4x — the Z (depth) axis
FOLLOW_ZOOM        = 200.0           # lean in to ~2x when locked on a face

# Where "looking at you" is. Tune LOOK_AT_YOU live with /eyelevel?tilt=N until
# it meets your eyes instead of the ceiling. EYE_PAN is "facing forward".
LOOK_AT_YOU = -6.0    # rest slightly DOWN toward you, not up at the ceiling
EYE_PAN     = 0.0


def set_eye_level(tilt: float) -> None:
    """Live-tune the 'looking at you' tilt (from /eyelevel)."""
    global LOOK_AT_YOU
    LOOK_AT_YOU = float(tilt)
PAN_SIGN  = 1.0     # flip to -1 if it turns AWAY from a face
TILT_SIGN = 1.0     # flip to -1 if it tilts the wrong way
ROLL_SIGN = 1.0     # flip to -1 if the head-cock leans the wrong way
ZOOM_EASE = 0.10    # gentle lean-in / pull-out (slow so it's smooth, not jarring)

# ── Follow feel ─────────────────────────────────────────────────────────────
FOLLOW_GAIN = 15.0    # gentler chase (was 26 — too twitchy up close)
FOLLOW_EASE = 0.16    # smoother approach
LOSE_FACE_S = 2.5
DEADZONE    = 0.16    # ignore small face offsets so it doesn't fidget on micro-moves
CLOSE_FRAC  = 0.30    # face wider than this fraction of frame = "you're close"

# ── Idle "breathing" — subtle life even while holding still ─────────────────
BREATH_AMP  = 0.7
BREATH_RATE = 1.1


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


@dataclass
class Face:
    x: int; y: int; w: int; h: int
    @property
    def cx(self): return self.x + self.w / 2
    @property
    def cy(self): return self.y + self.h / 2
    @property
    def area(self): return self.w * self.h


@dataclass
class Waypoint:
    tp: float          # target pan
    tt: float          # target tilt
    ease: float        # 0..1 — approach speed (low=slow drift, high=snappy dart)
    dwell: float       # seconds to rest once arrived
    timeout: float = 4.0   # give up approaching after this long (never get stuck)
    tr: float = 0.0    # target roll (sideways head-cock); default level


class Personality:
    def __init__(self) -> None:
        self.pan = 0.0
        self.tilt = 0.0
        self.roll = 0.0
        self.zoom = ZOOM_MIN
        self.mode = "wander"
        self._q: list[Waypoint] = []
        self._cur: Waypoint | None = None
        self._cur_start = 0.0
        self._held_from: float | None = None
        self._last_gesture = ""
        self._last_face = 0.0

    # ── Gesture repertoire ──────────────────────────────────────────────────
    def _gesture(self, name: str) -> list[Waypoint]:
        p, t = self.pan, self.tilt
        side = -1 if p > 0 else 1                    # bias moves toward center-crossing
        far  = lambda: random.choice([PAN_MIN, PAN_MAX]) * random.uniform(0.7, 1.0)

        # ── Named "on demand" gestures you can trigger to play ──
        #   YES = nod (tilt)   NO = shake (pan)   HUH = head-cock (roll)
        if name == "yes":         # nod up-down-up — an emphatic "yes"
            n = 16
            return [Waypoint(p, _clamp(t + n, TILT_MIN, TILT_MAX),      0.20, 0.12, 1.5),
                    Waypoint(p, _clamp(t - n * 0.6, TILT_MIN, TILT_MAX), 0.20, 0.12, 1.5),
                    Waypoint(p, _clamp(t + n * 0.5, TILT_MIN, TILT_MAX), 0.20, 0.12, 1.5),
                    Waypoint(p, t, 0.14, 0.5, 1.5)]

        if name == "no":          # shake left-right-left — an emphatic "no"
            s = 22
            return [Waypoint(_clamp(p - s, PAN_MIN, PAN_MAX), t, 0.22, 0.10, 1.5),
                    Waypoint(_clamp(p + s, PAN_MIN, PAN_MAX), t, 0.22, 0.10, 1.5),
                    Waypoint(_clamp(p - s * 0.6, PAN_MIN, PAN_MAX), t, 0.22, 0.10, 1.5),
                    Waypoint(p, t, 0.14, 0.5, 1.5)]

        if name == "huh":         # curious head-cock and hold — "huh?" (full lean)
            lean = random.choice([-1, 1]) * ROLL_PUSH
            return [Waypoint(p, t, 0.10, 1.8, 3.5, tr=lean),
                    Waypoint(p, t, 0.10, 0.4, 2.0, tr=0.0)]

        if name == "center":      # return to neutral — pan first, then tilt (never together)
            return [Waypoint(0.0, t, 0.10, 0.3, 2.5, tr=0.0),
                    Waypoint(0.0, 0.0, 0.10, 0.4, 3.0, tr=0.0)]

        if name == "wake":        # GOOD MORNING — stretch, find you, greet, settle
            up = _clamp(t + 26, TILT_MIN, TILT_MAX)
            return [
                Waypoint(p, up, 0.055, 0.8, 5.0),                              # 1. slow stretch UP (tilt)
                Waypoint(p, LOOK_AT_YOU, 0.07, 0.4, 3.5),                      # 2. ease down to your level
                Waypoint(_clamp(EYE_PAN + 32, PAN_MIN, PAN_MAX), LOOK_AT_YOU,
                         0.10, 0.4, 3.5),                                      # 3. look around one way (pan)
                Waypoint(_clamp(EYE_PAN - 32, PAN_MIN, PAN_MAX), LOOK_AT_YOU,
                         0.10, 0.4, 3.5),                                      # 4. and the other (pan)
                Waypoint(EYE_PAN, LOOK_AT_YOU, 0.10, 0.35, 3.0),              # 5. find you — center (pan)
                Waypoint(EYE_PAN, LOOK_AT_YOU, 0.085, 1.1, 5.0, tr= ROLL_PUSH),  # 6. big HELLO head-tilt
                Waypoint(EYE_PAN, LOOK_AT_YOU, 0.085, 1.1, 5.0, tr=-ROLL_PUSH),  # 7. and back (roll)
                Waypoint(EYE_PAN, LOOK_AT_YOU, 0.085, 0.6, 3.0, tr=0.0),         # 8. settle, looking at you
            ]

        # Character: mostly looks at YOU, pleads with roll, and reacts to
        # imagined sounds with fast snaps + freezes. Pan/tilt moves are BIG and
        # FAST; roll is the gentle signature. Stillness between moves keeps the
        # fast ones from reading as frantic.

        if name == "eye":         # look toward you — pan first, THEN tilt (never together)
            pp = _clamp(EYE_PAN + random.uniform(-16, 16), PAN_MIN, PAN_MAX)
            return [Waypoint(pp, t, 0.13, random.uniform(0.4, 0.9), 3.0),           # turn forward
                    Waypoint(pp, _clamp(LOOK_AT_YOU + random.uniform(-7, 7),
                                        TILT_MIN, TILT_MAX),
                             0.13, random.uniform(1.2, 2.6), 4.0)]                  # settle gaze

        if name == "plead":       # DEEP, SLOW roll — leans ALL the way over and holds
            a = ROLL_PUSH          # overshoot so it slams to the full physical limit
            return [Waypoint(p, t, 0.10, 1.1, 4.5, tr= a),          # roll fully one way, HOLD
                    Waypoint(p, t, 0.10, 1.1, 4.5, tr=-a),          # fully other way, HOLD
                    Waypoint(p, t, 0.10, 1.2, 4.5, tr=0.0)]         # settle level

        if name == "sway":        # slow deep sway — full lean, unhurried
            a = ROLL_PUSH
            return [Waypoint(p, t, 0.085, 0.9, 4.0, tr= a),
                    Waypoint(p, t, 0.085, 0.9, 4.0, tr=-a),
                    Waypoint(p, t, 0.08,  1.1, 4.0, tr=0.0)]

        if name == "investigate": # horizontal search → vertical scan → deep "huh?"
            # Search both sides first. The final pan waypoint has a long dwell so
            # the physical gimbal finishes turning before any tilt command begins.
            reach = random.uniform(0.68, 0.88)
            first_sign = random.choice([-1, 1])
            p1 = (PAN_MAX if first_sign > 0 else PAN_MIN) * reach
            p2 = (PAN_MIN if first_sign > 0 else PAN_MAX) * reach
            up = _clamp(t + random.uniform(14, 22), TILT_MIN, TILT_MAX)
            dn = _clamp(t - random.uniform(24, 36), TILT_MIN, TILT_MAX)
            lean = random.choice([-1, 1]) * ROLL_PUSH
            return [
                Waypoint(p1, t, 0.16, 0.45, 4.0),                  # 1. search one side (pan only)
                Waypoint(p2, t, 0.13, 0.85, 5.0),                  # 2. search other side; stop pan
                Waypoint(p2, up, 0.12, 0.25, 3.0),                 # 3. scan up (tilt only)
                Waypoint(p2, dn, 0.11, 0.30, 3.5),                 # 4. scan down — "yes" shape
                Waypoint(p2, t,  0.10, 0.80, 3.0),                 # 5. level; stop tilt completely
                Waypoint(p2, t,  0.075, 2.4, 5.0, tr=lean),        # 6. deep, slow HUH roll + hold
                Waypoint(p2, t,  0.065, 0.8, 4.0, tr=0.0),         # 7. unhurried return to level
            ]

        if name == "alert":       # heard something! fast snap, freeze, then dismiss
            tp = _clamp(random.choice([PAN_MIN, PAN_MAX]) * random.uniform(0.6, 0.95),
                        PAN_MIN, PAN_MAX)
            return [Waypoint(tp, t, 0.30, random.uniform(2.2, 4.2), 2.5),   # snap pan + FREEZE
                    Waypoint(_clamp(EYE_PAN + random.uniform(-8, 8), PAN_MIN, PAN_MAX),
                             t, 0.07, random.uniform(0.8, 1.6), 4.0)]        # return pan, hold tilt

        if name == "turn":        # BIG FAST pan, LEANING into it with roll (pan+roll ok)
            tp   = _clamp(far(), PAN_MIN, PAN_MAX)
            lean = random.uniform(24, 45) * (1 if tp > p else -1)
            return [Waypoint(tp, t, 0.22, random.uniform(0.7, 1.4), 3.0,
                             tr=_clamp(lean, ROLL_MIN, ROLL_MAX)),
                    Waypoint(tp, t, 0.12, random.uniform(0.6, 1.2), 2.5, tr=0.0)]

        if name == "look":        # BIG FAST nod — tilt only
            return [Waypoint(p,
                             _clamp(t + random.choice([-1, 1]) * random.uniform(26, 46),
                                    TILT_MIN, TILT_MAX),
                             0.22, random.uniform(0.7, 1.4), 3.0)]

        if name == "cock":        # ear-to-shoulder head-cock — roll only, full lean
            lean = random.choice([-1, 1]) * ROLL_PUSH
            return [Waypoint(p, t, 0.10, random.uniform(1.6, 2.8), 4.0, tr=lean)]

        if name == "flop":        # rare dramatic full ear-to-ground tilt — roll only
            lean = random.choice([-1, 1]) * ROLL_PUSH
            return [Waypoint(p, t, 0.10, random.uniform(1.8, 3.2), 4.0, tr=lean),
                    Waypoint(p, t, 0.08, random.uniform(0.6, 1.2), 3.0, tr=0.0)]

        if name == "scan":        # slow searching pan — pan only
            return [Waypoint((PAN_MAX if p < 0 else PAN_MIN) * 0.85, t,
                             0.03, random.uniform(0.6, 1.2), 8.0)]

        # "stare" / default — attentive freeze (the "spend time" pauses)
        return [Waypoint(p, t, 0.05, random.uniform(2.6, 5.0), 1.0)]

    _WEIGHTS = {
        # roll-dominant — plead + sway + cock + flop + investigate + turn(lean)
        "plead":       20,   # deep pleading roll — your favorite
        "sway":        16,   # continuous gentle roll sway
        "eye":         14,   # look at you (pan then tilt, never together)
        "cock":        14,   # head-cock (roll)
        "investigate": 14,   # notice → scan → huh (ends on big roll)
        "stare":        8,   # freeze / spend time
        "turn":         6,   # pan turn, leaning with roll
        "alert":        5,   # heard something → freeze → ignored
        "flop":         5,   # dramatic full head-flop
        "look":         1,   # rare standalone nod
    }

    def force(self, name: str) -> None:
        """Play a named gesture right now (yes/no/huh/center/…), then resume idle."""
        self._q = self._gesture(name)
        self._cur = None
        self.mode = "wander"

    def _pick_gesture(self) -> list[Waypoint]:
        names = [n for n in self._WEIGHTS if n != self._last_gesture]  # no immediate repeat
        weights = [self._WEIGHTS[n] for n in names]
        name = random.choices(names, weights=weights, k=1)[0]
        self._last_gesture = name
        return self._gesture(name)

    # ── Tick ────────────────────────────────────────────────────────────────
    def update(self, faces: list[Face], frame_w: int, frame_h: int, now: float | None = None):
        if now is None:
            now = time.monotonic()

        if faces:
            self._last_face = now
            self.mode = "follow"
            self._cur = None; self._q.clear()      # drop any idle gesture
            face = max(faces, key=lambda f: f.area)
            ex = (face.cx - frame_w / 2) / (frame_w / 2)
            ey = (face.cy - frame_h / 2) / (frame_h / 2)
            close = (face.w / frame_w) > CLOSE_FRAC     # you're right up in its face

            # When you're close, chase even less and settle — don't fidget on
            # every micro-movement, and don't zoom in (that amplifies restlessness).
            gain = FOLLOW_GAIN * (0.5 if close else 1.0)
            ease = FOLLOW_EASE * (0.7 if close else 1.0)
            dz   = DEADZONE   * (1.6 if close else 1.0)

            tp, tt = self.pan, self.tilt
            if abs(ex) > dz:
                tp = _clamp(self.pan + PAN_SIGN * gain * ex, PAN_MIN, PAN_MAX)
            if abs(ey) > dz:
                tt = _clamp(self.tilt - TILT_SIGN * gain * ey, TILT_MIN, TILT_MAX)
            self.pan  += (tp - self.pan) * ease
            self.tilt += (tt - self.tilt) * ease
            self.roll += (0.0 - self.roll) * FOLLOW_EASE       # level up — attentive
            target_zoom = ZOOM_MIN if close else FOLLOW_ZOOM   # no zoom when already close
            self.zoom += (target_zoom - self.zoom) * ZOOM_EASE
            return self.pan, self.tilt, self.roll, self.zoom, True

        if self.mode == "follow" and now - self._last_face < LOSE_FACE_S:
            self.roll += (0.0 - self.roll) * FOLLOW_EASE
            self.zoom += (ZOOM_MIN - self.zoom) * ZOOM_EASE
            return self.pan, self.tilt, self.roll, self.zoom, False  # hold where face was

        # ── WANDER: run the gesture queue ──
        self.mode = "wander"
        if self._cur is None:
            if not self._q:
                self._q = self._pick_gesture()
            self._cur = self._q.pop(0)
            self._cur_start = now
            self._held_from = None

        wp = self._cur
        self.pan  += (wp.tp - self.pan) * wp.ease
        self.tilt += (wp.tt - self.tilt) * wp.ease
        self.roll += (wp.tr - self.roll) * wp.ease

        arrived = (abs(wp.tp - self.pan) + abs(wp.tt - self.tilt) < 1.5)
        if arrived or (now - self._cur_start > wp.timeout):
            if self._held_from is None:
                self._held_from = now
            elif now - self._held_from >= wp.dwell:
                self._cur = None                    # advance to next waypoint/gesture

        # ease zoom back to 1x while wandering
        self.zoom += (ZOOM_MIN - self.zoom) * ZOOM_EASE
        # (No breathing wobble — it read as a fast nodding/tail-shake jitter.
        # The gesture variety + stares provide the life instead.)
        return (self.pan, self.tilt, self.roll, self.zoom, False)
