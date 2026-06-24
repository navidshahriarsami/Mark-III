"""
MARK III — Presence Manager (Phase 11)

Tracks active voice-capable devices and resolves preferred I/O routing.

Design goals:
  - Any combination of input/output devices per session (earbuds in, glasses mic out)
  - Device handoff without dropping the conversation session
  - Future-compatible: register new device types by subclassing VoiceDevice
  - Heartbeat-based expiry so stale devices are automatically removed

Device types:
  desktop  — local machine running brain-server, full sounddevice access
  mobile   — phone running MARK III mobile app, API-based PTT
  earbud   — Bluetooth earbuds (future: BLE / platform SDK)
  glasses  — Meta Ray-Ban, Xreal, etc. (future: SDK integration)
  unknown  — any device that hasn't self-identified

Capability flags:
  microphone     — device can record audio
  speaker        — device can play audio
  wake_word      — device runs wake word detection locally
  push_to_talk   — device signals PTT via API (mobile, glasses button)
  streaming      — device supports real-time audio stream (WebSocket)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("markiii.voice.presence")

# Seconds without a heartbeat before a device is considered absent
_DEVICE_TTL = 120.0

# Capability constants
CAP_MIC       = "microphone"
CAP_SPEAKER   = "speaker"
CAP_WAKE_WORD = "wake_word"
CAP_PTT       = "push_to_talk"
CAP_STREAMING = "streaming"


@dataclass
class VoiceDevice:
    """
    A registered voice I/O device.

    mic_index / speaker_index are sounddevice indices (desktop only).
    metadata holds device-specific data: BT address, glasses serial, etc.
    """
    device_id:     str
    device_type:   str                         # desktop|mobile|earbud|glasses|unknown
    name:          str
    capabilities:  set[str]                    = field(default_factory=set)
    mic_index:     Optional[int]               = None   # -1 = system default
    speaker_index: Optional[int]               = None
    last_seen:     float                       = field(default_factory=time.time)
    metadata:      dict                        = field(default_factory=dict)

    @property
    def can_record(self) -> bool:
        return CAP_MIC in self.capabilities

    @property
    def can_speak(self) -> bool:
        return CAP_SPEAKER in self.capabilities

    @property
    def has_wake_word(self) -> bool:
        return CAP_WAKE_WORD in self.capabilities

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < _DEVICE_TTL

    def touch(self) -> None:
        self.last_seen = time.time()

    def to_dict(self) -> dict:
        return {
            "device_id":     self.device_id,
            "device_type":   self.device_type,
            "name":          self.name,
            "capabilities":  sorted(self.capabilities),
            "mic_index":     self.mic_index,
            "speaker_index": self.speaker_index,
            "last_seen":     self.last_seen,
            "is_alive":      self.is_alive,
            "metadata":      self.metadata,
        }


class PresenceManager:
    """
    Singleton registry of active voice devices.

    Responsibilities:
    - Register / update / expire devices
    - Resolve preferred input/output for a given session device_id
    - Support cross-device routing (mic from glasses, speaker to earbuds)
    - Provide handoff: re-route a live session to new devices
    """

    def __init__(self) -> None:
        self._devices: dict[str, VoiceDevice] = {}
        # Explicit routing overrides: device_id → (input_device_id, output_device_id)
        self._routing: dict[str, tuple[str, str]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, device: VoiceDevice) -> None:
        self._devices[device.device_id] = device
        logger.info(
            "Device registered  id=%s  type=%s  caps=%s",
            device.device_id[:16], device.device_type,
            ",".join(sorted(device.capabilities)),
        )

    def register_desktop(
        self,
        device_id:     str,
        name:          str = "Desktop",
        mic_index:     Optional[int] = None,
        speaker_index: Optional[int] = None,
    ) -> VoiceDevice:
        dev = VoiceDevice(
            device_id     = device_id,
            device_type   = "desktop",
            name          = name,
            capabilities  = {CAP_MIC, CAP_SPEAKER, CAP_WAKE_WORD, CAP_STREAMING},
            mic_index     = mic_index,
            speaker_index = speaker_index,
        )
        self.register(dev)
        return dev

    def register_mobile(
        self,
        device_id: str,
        name:      str = "Mobile",
        metadata:  dict | None = None,
    ) -> VoiceDevice:
        dev = VoiceDevice(
            device_id    = device_id,
            device_type  = "mobile",
            name         = name,
            capabilities = {CAP_MIC, CAP_SPEAKER, CAP_PTT},
            metadata     = metadata or {},
        )
        self.register(dev)
        return dev

    def register_earbud(
        self,
        device_id:    str,
        name:         str = "Earbuds",
        bt_address:   str = "",
    ) -> VoiceDevice:
        """Register a Bluetooth earbud device (future SDK integration)."""
        dev = VoiceDevice(
            device_id    = device_id,
            device_type  = "earbud",
            name         = name,
            capabilities = {CAP_MIC, CAP_SPEAKER, CAP_PTT},
            metadata     = {"bt_address": bt_address},
        )
        self.register(dev)
        return dev

    def register_glasses(
        self,
        device_id:  str,
        name:       str = "Smart Glasses",
        serial:     str = "",
        platform:   str = "meta_ray_ban",
    ) -> VoiceDevice:
        """Register a smart glasses device (Meta Ray-Ban, Xreal, etc.)."""
        dev = VoiceDevice(
            device_id    = device_id,
            device_type  = "glasses",
            name         = name,
            capabilities = {CAP_MIC, CAP_PTT},            # glasses rarely have speakers
            metadata     = {"serial": serial, "platform": platform},
        )
        self.register(dev)
        return dev

    def heartbeat(self, device_id: str) -> None:
        """Update last_seen for a device. Call from device heartbeat API."""
        if device_id in self._devices:
            self._devices[device_id].touch()

    def remove(self, device_id: str) -> None:
        self._devices.pop(device_id, None)
        self._routing.pop(device_id, None)

    def expire_stale(self) -> list[str]:
        """Remove devices that haven't sent a heartbeat within TTL. Returns removed IDs."""
        stale = [did for did, d in self._devices.items() if not d.is_alive]
        for did in stale:
            self.remove(did)
            logger.info("Device expired  id=%s", did[:16])
        return stale

    # ------------------------------------------------------------------
    # I/O resolution
    # ------------------------------------------------------------------

    def preferred_input(self, device_id: str) -> Optional[VoiceDevice]:
        """
        Return the preferred microphone device for this session.

        Resolution order:
        1. Explicit routing override set via set_routing()
        2. The device itself if it has a microphone
        3. Any alive device with a microphone (desktop preferred)
        4. None (no microphone available)
        """
        # 1. Explicit override
        if device_id in self._routing:
            inp_id = self._routing[device_id][0]
            d = self._devices.get(inp_id)
            if d and d.can_record and d.is_alive:
                return d

        # 2. Device itself
        own = self._devices.get(device_id)
        if own and own.can_record and own.is_alive:
            return own

        # 3. Best available (desktop first)
        return self._best_input()

    def preferred_output(self, device_id: str) -> Optional[VoiceDevice]:
        """
        Return the preferred speaker device for this session.

        Resolution order:
        1. Explicit routing override
        2. The device itself if it has a speaker
        3. Any alive device with a speaker (desktop preferred)
        4. None (no speaker available)
        """
        if device_id in self._routing:
            out_id = self._routing[device_id][1]
            d = self._devices.get(out_id)
            if d and d.can_speak and d.is_alive:
                return d

        own = self._devices.get(device_id)
        if own and own.can_speak and own.is_alive:
            return own

        return self._best_output()

    def _best_input(self) -> Optional[VoiceDevice]:
        """Pick the best available mic: desktop > earbud > glasses > mobile."""
        preference = ["desktop", "earbud", "glasses", "mobile", "unknown"]
        alive_mics = [d for d in self._devices.values() if d.can_record and d.is_alive]
        for pref in preference:
            for d in alive_mics:
                if d.device_type == pref:
                    return d
        return None

    def _best_output(self) -> Optional[VoiceDevice]:
        """Pick the best available speaker: earbud > desktop > mobile."""
        preference = ["earbud", "desktop", "mobile", "unknown"]
        alive_speakers = [d for d in self._devices.values() if d.can_speak and d.is_alive]
        for pref in preference:
            for d in alive_speakers:
                if d.device_type == pref:
                    return d
        return None

    # ------------------------------------------------------------------
    # Routing overrides (device handoff)
    # ------------------------------------------------------------------

    def set_routing(
        self,
        device_id:       str,
        input_device_id: str,
        output_device_id: str,
    ) -> dict:
        """
        Override I/O routing for a device.

        Example: glasses mic + earbud speaker
          set_routing(session_device_id, glasses_id, earbud_id)

        The override persists until clear_routing() or device expiry.
        """
        self._routing[device_id] = (input_device_id, output_device_id)
        inp  = self._devices.get(input_device_id)
        out  = self._devices.get(output_device_id)
        logger.info(
            "Routing set  device=%s  input=%s(%s)  output=%s(%s)",
            device_id[:16],
            input_device_id[:16],  inp.device_type if inp else "unknown",
            output_device_id[:16], out.device_type if out else "unknown",
        )
        return {
            "device_id":        device_id,
            "input_device_id":  input_device_id,
            "output_device_id": output_device_id,
        }

    def clear_routing(self, device_id: str) -> None:
        self._routing.pop(device_id, None)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_device(self, device_id: str) -> Optional[VoiceDevice]:
        return self._devices.get(device_id)

    def list_alive(self) -> list[VoiceDevice]:
        return [d for d in self._devices.values() if d.is_alive]

    def status(self) -> dict:
        alive = self.list_alive()
        return {
            "total_registered": len(self._devices),
            "alive":            len(alive),
            "devices":          [d.to_dict() for d in alive],
            "routing_overrides": {
                k: {"input": v[0], "output": v[1]}
                for k, v in self._routing.items()
            },
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_presence: PresenceManager | None = None


def get_presence_manager() -> PresenceManager:
    global _presence
    if _presence is None:
        _presence = PresenceManager()
    return _presence
