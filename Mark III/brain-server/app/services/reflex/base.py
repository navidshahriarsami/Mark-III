from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ReflexResponse:
    handled:    bool
    text:       str
    confidence: float   # 0.0–1.0
    source:     str     # module name: "system", "weather", "network", …
    latency_ms: float

    @classmethod
    def miss(cls) -> "ReflexResponse":
        return cls(handled=False, text="", confidence=0.0, source="none", latency_ms=0.0)
