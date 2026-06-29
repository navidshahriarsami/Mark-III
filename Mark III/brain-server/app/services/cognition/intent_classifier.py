"""
MARK III — Intent Classifier

Classifies every utterance before routing so the pipeline can choose
the cheapest, fastest source that can answer it correctly.

Intent types:
  social       → Social Reflex  (<1ms)
  factual_live → Integration Manager  (<10ms) — time, weather, battery, etc.
  recall       → Vector/Obsidian memory  (<200ms)
  conversation → Qwen 7B  (1-3s)
  reasoning    → Qwen 7B with deep context  (2-5s)
  complex      → Council  (5-30s)

Classification is purely rule-based (regex + keyword) — zero LLM cost.
Fast enough to add <2ms to every query.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    SOCIAL       = "social"        # hello, thanks, bye
    FACTUAL_LIVE = "factual_live"  # time, weather, battery, device status
    RECALL       = "recall"        # what did we decide, remind me, what phase
    CONVERSATION = "conversation"  # casual chat, short answers
    REASONING    = "reasoning"     # why, how does, explain, plan
    COMPLEX      = "complex"       # multi-step, architecture, coding


@dataclass
class IntentResult:
    intent:     Intent
    confidence: float   # 0.0–1.0
    signals:    list[str]


# ── Pattern banks ─────────────────────────────────────────────────────────────

_SOCIAL = re.compile(
    r"^(hi|hello|hey|good (morning|afternoon|evening|night)|thanks?|thank you|"
    r"bye|goodbye|yes|no|ok|okay|got it|alright|sure|cool|great|perfect|"
    r"mark|are you there|you there)[\s!?.]*$",
    re.I,
)

_FACTUAL_LIVE = re.compile(
    r"\b(time|date|day|weather|temperature|uv|rain|battery|charge|"
    r"cpu|ram|gpu|memory usage|disk|storage|wifi|internet|network|ip|"
    r"device status|who is online|is .+ connected|location|where am i)\b",
    re.I,
)

_RECALL = re.compile(
    r"\b(what did (we|you|i) (decide|say|discuss|agree|build|choose)|"
    r"why did (we|you|i) (choose|pick|select|use|switch|decide|go with)|"
    r"remind me|what was (the|our|my)|what phase|what is mark'?s?|"
    r"our decision|architecture|roadmap|phase \d+|what have we|"
    r"what did we build|what is installed|what models|remember when|"
    r"threshold|setting|config|parameter|value for|how (is|was|are) .+ set|"
    r"what (is|was|are) (the|our) .+(threshold|setting|config|value|level))\b",
    re.I,
)

_COMPLEX = re.compile(
    r"\b(design|architect|implement|build a (system|pipeline|service)|"
    r"write (code|a function|a class|a script)|debug|refactor|"
    r"step[- ]by[- ]step|plan (the|my|a) (entire|full|complete)|"
    r"compare .+ vs|pros and cons|trade.?offs?|analyse|"
    r"career|investment|legal|medical)\b",
    re.I,
)

_REASONING = re.compile(
    r"\b(why|how does|how do|explain|what causes|difference between|"
    r"should i|what would|what if|help me (understand|plan|figure|think)|"
    r"recommend|advise|suggest|best (way|approach|option)|"
    r"break (this|it) down|walk me through|"
    r"plan (my|a|the)|schedule|prioriti[sz]e|help me with|what should i)\b",
    re.I,
)


# ── Classifier ────────────────────────────────────────────────────────────────

def classify(text: str) -> IntentResult:
    """
    Classify the intent of a voice utterance.
    Returns the most specific matching intent with confidence.
    """
    t = text.strip()

    # Social — highest priority for short utterances
    if _SOCIAL.search(t) and len(t.split()) <= 6:
        return IntentResult(Intent.SOCIAL, 0.95, ["social_pattern"])

    # Factual live — time/weather/device data
    signals: list[str] = []
    if m := _FACTUAL_LIVE.search(t):
        signals.append(f"factual:{m.group()}")
        return IntentResult(Intent.FACTUAL_LIVE, 0.90, signals)

    # Recall — asking about stored knowledge
    if m := _RECALL.search(t):
        signals.append(f"recall:{m.group()}")
        return IntentResult(Intent.RECALL, 0.88, signals)

    # Complex — multi-step, architecture, coding
    if m := _COMPLEX.search(t):
        signals.append(f"complex:{m.group()}")
        return IntentResult(Intent.COMPLEX, 0.85, signals)

    # Reasoning — explanation, planning, advice
    if m := _REASONING.search(t):
        signals.append(f"reasoning:{m.group()}")
        return IntentResult(Intent.REASONING, 0.80, signals)

    # Default: conversational
    return IntentResult(Intent.CONVERSATION, 0.70, ["default"])
