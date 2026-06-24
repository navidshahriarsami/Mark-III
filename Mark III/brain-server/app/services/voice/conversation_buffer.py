from __future__ import annotations

"""
MARK III Phase 15B — ConversationBuffer + SentenceValidator

ConversationBuffer — Phase 15B redesign:
    Problem solved: keyboard clicks (~30ms spikes at -30 dBFS) used to reset
    the silence counter on every keystroke, forcing the 15-second max.

    Fix: onset confirmation requires ONSET_CHUNKS consecutive loud frames
    (300 ms by default) before declaring speech.  A single click (1 frame)
    never meets that threshold, so the silence counter is never corrupted.
    A pre-buffer captures the frames before onset so no speech is lost.

    State machine:
        WAITING  → no confirmed speech; audio buffered in ring pre-buffer
        SPEAKING → onset confirmed; recording + silence tracking
        COMPLETE → 3 s silence elapsed OR max duration hit

SentenceValidator:
    Classifies a Whisper transcript as:
        noise      — discard silently
        incomplete — continue listening (trailing clause, dangling opener)
        complete   — send to council
"""

import io
import logging
import re
import wave
from enum import Enum
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("markiii.conv_buffer")


# ─────────────────────────────────────────────────────────────────
# ConvState
# ─────────────────────────────────────────────────────────────────

class ConvState(str, Enum):
    WAITING  = "waiting"
    SPEAKING = "speaking"
    COMPLETE = "complete"


# ─────────────────────────────────────────────────────────────────
# ConversationBuffer
# ─────────────────────────────────────────────────────────────────

class ConversationBuffer:
    """
    Phase 15B dynamic VAD buffer.

    Feed mic chunks one at a time; call get_wav() when feed() returns True.

    Key behaviour:
    - Onset confirmation: ONSET_CHUNKS consecutive loud frames required
      before recording starts. Rejects clicks, bumps, fan spikes (<300 ms).
    - Pre-buffer: last ~450 ms held in a ring buffer so speech onset is never
      clipped when recording finally arms.
    - Silence timeout (3 s): once speech is confirmed, 3 consecutive seconds
      of quiet triggers COMPLETE.  Single clicks do NOT reset this counter
      (they won't confirm as speech again).
    - on_speech_start callback: fires the moment onset is confirmed so the
      caller can transition from WAIT_FOR_SPEECH → LISTENING.
    - Hard ceiling at max_duration_s regardless of speech pattern.
    """

    def __init__(
        self,
        sample_rate:        int   = 16000,
        speech_db:          float = -35.0,
        onset_chunks:       int   = 10,
        silence_timeout_s:  float = 3.0,
        max_duration_s:     float = 20.0,
        on_speech_start:    Optional[Callable] = None,
    ) -> None:
        self._sr           = sample_rate
        self._speech_db    = speech_db
        self._onset_need   = onset_chunks
        self._sil_timeout  = int(silence_timeout_s * sample_rate)
        self._max_dur      = int(max_duration_s    * sample_rate)
        self._prebuf_size  = int(onset_chunks * 1.5)  # ~450 ms at 30 ms/chunk
        self._on_start     = on_speech_start

        self._state:       ConvState   = ConvState.WAITING
        self._chunks:      list[bytes] = []
        self._prebuffer:   list[bytes] = []   # ring buffer before onset

        self._onset_count: int = 0   # consecutive loud chunks
        self._total_samp:  int = 0
        self._speech_samp: int = 0
        self._sil_samp:    int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> ConvState:
        return self._state

    @property
    def speech_duration_s(self) -> float:
        return self._speech_samp / self._sr

    @property
    def total_duration_s(self) -> float:
        return self._total_samp / self._sr

    @property
    def silence_duration_s(self) -> float:
        return self._sil_samp / self._sr

    # ------------------------------------------------------------------
    # Feed
    # ------------------------------------------------------------------

    def feed(self, pcm16: np.ndarray) -> bool:
        """
        Feed one 16-bit PCM chunk.
        Returns True when utterance is complete and get_wav() is ready.
        """
        n   = len(pcm16)
        rms = float(np.sqrt(np.mean(pcm16.astype(np.float64) ** 2)))
        db  = 20.0 * np.log10(rms / 32768.0 + 1e-9)
        is_loud = db > self._speech_db

        # Onset counter: rises on loud frames, decays 3× faster when quiet.
        # This requires ~300ms of sustained audio to reach onset_need,
        # but resets to zero after ~10ms of quiet (one chunk quiet = -3).
        if is_loud:
            self._onset_count = min(self._onset_count + 1, self._onset_need * 2)
        else:
            self._onset_count = max(self._onset_count - 3, 0)

        is_speech = self._onset_count >= self._onset_need

        # ── WAITING ────────────────────────────────────────────────
        if self._state == ConvState.WAITING:
            # Always update ring pre-buffer while waiting
            self._prebuffer.append(pcm16.tobytes())
            if len(self._prebuffer) > self._prebuf_size:
                self._prebuffer.pop(0)

            if is_speech:
                # Onset confirmed — flush pre-buffer into recording
                for pre_bytes in self._prebuffer:
                    self._chunks.append(pre_bytes)
                    self._total_samp += len(pre_bytes) // 2
                self._prebuffer.clear()

                self._chunks.append(pcm16.tobytes())
                self._total_samp  += n
                self._speech_samp += n
                self._state = ConvState.SPEAKING

                log.debug("Speech onset (db=%.1f)", db)
                if self._on_start:
                    try:
                        self._on_start()
                    except Exception:
                        pass

        # ── SPEAKING ───────────────────────────────────────────────
        elif self._state == ConvState.SPEAKING:
            self._chunks.append(pcm16.tobytes())
            self._total_samp += n

            if is_speech:
                self._speech_samp += n
                self._sil_samp     = 0
            else:
                self._sil_samp += n
                if self._sil_samp >= self._sil_timeout:
                    self._state = ConvState.COMPLETE
                    log.debug(
                        "Utterance complete: speech=%.1fs  silence=%.1fs  total=%.1fs",
                        self.speech_duration_s,
                        self.silence_duration_s,
                        self.total_duration_s,
                    )
                    return True

        # Hard max-duration ceiling
        if self._total_samp >= self._max_dur:
            self._state = ConvState.COMPLETE
            log.debug("Max duration reached (%.0fs)", self.total_duration_s)
            return True

        return False

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def get_wav(self) -> bytes:
        """Return all buffered audio as WAV bytes."""
        raw = b"".join(self._chunks)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sr)
            wf.writeframes(raw)
        return buf.getvalue()

    def reset(self) -> None:
        self._chunks.clear()
        self._prebuffer.clear()
        self._state        = ConvState.WAITING
        self._onset_count  = 0
        self._total_samp   = 0
        self._speech_samp  = 0
        self._sil_samp     = 0


# ─────────────────────────────────────────────────────────────────
# Sentence Validator  (Phase 15B)
# ─────────────────────────────────────────────────────────────────

# Single tokens Whisper hallucinates on silence or background noise
_NOISE_TOKENS: frozenset[str] = frozenset({
    "uh", "um", "umm", "hmm", "hm", "huh", "mm", "mhm",
    "ah", "oh", "er", "erm", "ha", "hey", "eh", "ahh",
    "ohh", "uhh", "well", "so", "like", "what", "right",
    "the", "a", "i", "ok", "okay", "yeah", "yep", "nope",
})

# Words that signal the sentence is mid-clause (don't cut off yet)
_DANGLING_ENDINGS: frozenset[str] = frozenset({
    "and", "but", "or", "because", "so", "then",
    "the", "a", "an", "that", "which",
    "to", "of", "for", "with", "on", "in", "at", "by",
    "if", "when", "while", "as", "though", "although",
    "however", "yet",
})

# Incomplete-opener patterns — sentence started but not finished
_INCOMPLETE_RE: list[re.Pattern] = [
    # "I need / want / think / feel / was" (without completion)
    re.compile(r"\bI\s+(need|want|was|think|feel|was going)\s*$",             re.I),
    # "I need you / him / it" — object present but no verb follows
    re.compile(r"\bI need\s+(you|him|her|them|it|us)\s*$",                    re.I),
    # "Can / could / would / will you" alone
    re.compile(r"\b(can|could|would|will|shall)\s+you\s*$",                   re.I),
    # "What is / are / was / were" with nothing after
    re.compile(r"\bwhat\s+(is|are|was|were)\s*$",                             re.I),
    # "How do / does / did / can / should / would"
    re.compile(r"\bhow\s+(do|does|did|can|should|would)\s*$",                 re.I),
    # "When / where / who is / are / was"
    re.compile(r"\b(when|where|who)\s+(is|are|was|were|did|will|can|should)\s*$", re.I),
    # "Help me" / "Show me" / "Tell me" as the ENTIRE utterance (not inside a sentence)
    re.compile(r"^(please\s+)?(help|show|tell)\s+me[\s!?.]*$",                re.I),
    re.compile(r"^(please\s+)?explain[\s!?.]*$",                              re.I),
    # "I was thinking / wondering"
    re.compile(r"\bI was\s+(thinking|wondering)\s*$",                          re.I),
    # "Maybe / perhaps / sort of / kind of" trailing
    re.compile(r"\b(maybe|perhaps|sort of|kind of)\s*$",                       re.I),
]


class SentenceValidator:
    """
    Classify a Whisper transcript so MARK can decide what to do next.

    noise      → discard; prompt the user to repeat
    incomplete → open continuation window
    complete   → forward to council
    """

    # Phase 15B: require at least 2 words (MIN_WORDS = 2)
    _MIN_WORDS = 2

    def is_noise(self, text: str) -> bool:
        """True for empty, very short, or obvious transcription artefacts."""
        t = text.strip()
        if not t or len(t) < 3:
            return True
        words = t.lower().rstrip(".!?,;").split()
        # Fewer than MIN_WORDS → noise (single whispers, clicks, pops)
        if len(words) < self._MIN_WORDS:
            return True
        # All words are known filler tokens
        if all(w in _NOISE_TOKENS for w in words):
            return True
        return False

    def is_incomplete(self, text: str) -> bool:
        """True if the utterance ends on a dangling word or a known incomplete opener."""
        t    = text.strip().rstrip(".!?,;")
        last = t.split()[-1].lower() if t.split() else ""
        if last in _DANGLING_ENDINGS:
            return True
        for pat in _INCOMPLETE_RE:
            if pat.search(t):
                return True
        return False

    def is_complete(self, text: str) -> bool:
        return not self.is_noise(text) and not self.is_incomplete(text)
