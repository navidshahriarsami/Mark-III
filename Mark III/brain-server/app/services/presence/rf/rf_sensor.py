"""
MARK III Phase 15E.5 — RF Sensor Interface

Defines the RFSensor ABC and RFSignal dataclass.
All current and future WiFi/RF hardware adapters implement RFSensor.

Current implementation: DummySensor (synthetic data, no hardware required)

Future implementations (Phase 20+):
    EeroSensor       — Eero mesh network motion API
    ESP32Sensor      — ESP32 with CSI (Channel State Information) firmware
    CSIAdapterSensor — USB WiFi adapter running CSI capture

Design contract:
    - get_signal() is synchronous and fast (<50ms)
    - Never raises — returns a low-confidence "no signal" on failure
    - available property reflects real hardware state

MARK does not detect humans.
MARK estimates presence.
WiFi is one signal among many.
"""
from __future__ import annotations

import math
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# Core signal dataclass
# ─────────────────────────────────────────────────────────────────

@dataclass
class RFSignal:
    timestamp:         datetime
    source:            str           # sensor name, e.g. "dummy", "eero", "esp32"
    confidence:        float         # 0.0–1.0 — how reliable this reading is
    movement_detected: bool          # True if motion was inferred from RF
    signal_strength:   float         # RSSI-like, normalised 0.0–1.0 (1.0 = strongest)
    zone:              Optional[str] # "desk" | "living_room" | None if unknown

    @classmethod
    def null(cls, source: str = "none") -> "RFSignal":
        """Represents the absence of an RF sensor reading."""
        return cls(
            timestamp         = datetime.now(),
            source            = source,
            confidence        = 0.0,
            movement_detected = False,
            signal_strength   = 0.0,
            zone              = None,
        )


# ─────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────

class RFSensor(ABC):
    """
    Abstract interface for all RF/WiFi presence sensors.

    Implementations must be:
    - Synchronous (no async — called from presence polling thread)
    - Non-blocking (<50ms per call)
    - Safe (never raise — return RFSignal.null() on failure)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable sensor identifier."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """True if the underlying hardware/service is reachable."""

    @abstractmethod
    def get_signal(self) -> RFSignal:
        """
        Read the current RF environment and return a presence signal.
        Must return RFSignal.null() on any failure — never raise.
        """


# ─────────────────────────────────────────────────────────────────
# DummySensor — synthetic data, no hardware required
# ─────────────────────────────────────────────────────────────────

class DummySensor(RFSensor):
    """
    Synthetic RF sensor for development and testing.

    Simulates a realistic WiFi motion profile:
    - Work hours (8–22): moderate/high movement probability
    - Night (22–8):  low movement probability
    - Natural variation: 10s periods of stillness between bursts
    - Confidence: fixed 0.65 (synthetic data is inherently uncertain)

    Replace with EeroSensor or ESP32Sensor when hardware is available.
    """

    _CONFIDENCE = 0.65
    _ZONE       = "desk"

    def __init__(self) -> None:
        self._last_movement = time.monotonic()
        self._movement_burst_end = 0.0

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def available(self) -> bool:
        return True   # always available — it's synthetic

    def get_signal(self) -> RFSignal:
        now       = time.monotonic()
        hour      = datetime.now().hour
        wall_ts   = datetime.now()

        # Probability of movement in this 10s window
        if 8 <= hour < 22:
            base_prob = 0.7   # active hours
        elif hour < 6 or hour >= 23:
            base_prob = 0.1   # deep night
        else:
            base_prob = 0.4   # transition

        # Random movement bursts (simulate human activity patterns)
        if now > self._movement_burst_end:
            if random.random() < base_prob:
                burst_len = random.uniform(5, 40)    # 5–40s of motion
                self._movement_burst_end = now + burst_len
                self._last_movement = now

        movement = now <= self._movement_burst_end

        # Signal strength: stronger during burst, attenuated otherwise
        strength = (
            random.uniform(0.7, 1.0) if movement
            else random.uniform(0.2, 0.5)
        )

        return RFSignal(
            timestamp         = wall_ts,
            source            = self.name,
            confidence        = self._CONFIDENCE,
            movement_detected = movement,
            signal_strength   = round(strength, 3),
            zone              = self._ZONE,
        )


# ─────────────────────────────────────────────────────────────────
# Future sensor stubs (Phase 20)
# ─────────────────────────────────────────────────────────────────

class EeroSensor(RFSensor):
    """
    Phase 20 — Eero mesh network motion sensing.

    Eero Pro 6/6E exposes a local API that reports motion events
    detected via CSI (Channel State Information) analysis across
    the mesh nodes.

    Setup:
        1. Enable local API on Eero router
        2. Set EERO_API_KEY in .env
        3. Instantiate: EeroSensor(host="192.168.4.1", api_key="...")

    Reference: https://github.com/jfarmer/eero-client
    """

    def __init__(self, host: str = "", api_key: str = "") -> None:
        self._host    = host
        self._api_key = api_key

    @property
    def name(self) -> str:
        return f"eero:{self._host or 'unconfigured'}"

    @property
    def available(self) -> bool:
        return False   # Phase 20

    def get_signal(self) -> RFSignal:
        return RFSignal.null(self.name)


class ESP32Sensor(RFSensor):
    """
    Phase 20 — ESP32 with CSI firmware.

    An ESP32 running the esp32-csi-tool firmware transmits CSI
    data over serial/UDP, which is analysed for motion patterns.

    Setup:
        1. Flash esp32-csi-tool to ESP32
        2. Connect to same WiFi network as MARK
        3. Instantiate: ESP32Sensor(host="192.168.4.XX", port=5500)

    Reference: https://github.com/StevenMHernandez/ESP32-CSI-Tool
    """

    def __init__(self, host: str = "", port: int = 5500) -> None:
        self._host = host
        self._port = port

    @property
    def name(self) -> str:
        return f"esp32:{self._host or 'unconfigured'}"

    @property
    def available(self) -> bool:
        return False   # Phase 20

    def get_signal(self) -> RFSignal:
        return RFSignal.null(self.name)


class CSIAdapterSensor(RFSensor):
    """
    Phase 20 — USB WiFi adapter running CSI capture mode.

    Certain Atheros/Intel WiFi adapters can be configured to output
    raw CSI data. This sensor reads that stream and infers motion.

    Setup:
        1. Install nexmon/picoscenes CSI firmware on adapter
        2. Configure adapter in monitor mode
        3. Instantiate: CSIAdapterSensor(interface="wlan0")

    Reference: https://github.com/seemoo-lab/nexmon_csi
    """

    def __init__(self, interface: str = "wlan0") -> None:
        self._iface = interface

    @property
    def name(self) -> str:
        return f"csi:{self._iface}"

    @property
    def available(self) -> bool:
        return False   # Phase 20

    def get_signal(self) -> RFSignal:
        return RFSignal.null(self.name)
