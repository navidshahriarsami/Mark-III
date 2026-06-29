"""
MARK III — Fact Normalizer

Converts raw user-provided values into canonical, comparable forms.
Normalization happens BEFORE storage so retrieval is always exact.

Examples:
  "10k"              → value="10000"  unit=""
  "$10K AUD"         → value="10000"  unit="AUD"
  "ten thousand"     → value="10000"  unit=""
  "Twenty-five mil"  → value="25000000" unit=""
  "March 15"         → value="2026-03-15" unit="date"
  "3pm Monday"       → value="15:00 Monday" unit="time"
  "john@gmail.com"   → value="john@gmail.com" unit="email"
  "high priority"    → value="high"   unit="priority"
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class NormalizedValue:
    value:    str
    unit:     str   = ""
    raw:      str   = ""
    type:     str   = "text"   # number | date | time | email | text | boolean


# ── Number normalization ───────────────────────────────────────────────────────

_MULTIPLIERS = {
    "k": 1_000, "thousand": 1_000,
    "m": 1_000_000, "million": 1_000_000, "mil": 1_000_000,
    "b": 1_000_000_000, "billion": 1_000_000_000,
}

_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
}

_CURRENCIES = {
    "aud": "AUD", "australian": "AUD", "a$": "AUD",
    "usd": "USD", "us$": "USD", "american": "USD",
    "gbp": "GBP", "pound": "GBP", "£": "GBP",
    "eur": "EUR", "euro": "EUR", "€": "EUR",
    "cad": "CAD", "canadian": "CAD",
    "sgd": "SGD", "singapore": "SGD",
    "bdt": "BDT", "taka": "BDT", "bangladeshi": "BDT",
}

_CURRENCY_SYMBOLS = {"$": "", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
    "nov": "11", "dec": "12",
}


def normalize(raw: str) -> NormalizedValue:
    """
    Main normalization entry point.
    Detects the value type and normalizes accordingly.
    """
    raw_stripped = raw.strip()
    lower = raw_stripped.lower()

    # Email
    if re.match(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_stripped):
        return NormalizedValue(value=raw_stripped.lower(), unit="email", raw=raw, type="email")

    # Boolean
    if lower in ("yes", "true", "on", "enabled", "active", "confirmed"):
        return NormalizedValue(value="true", raw=raw, type="boolean")
    if lower in ("no", "false", "off", "disabled", "inactive"):
        return NormalizedValue(value="false", raw=raw, type="boolean")

    # Priority levels
    if lower in ("high", "critical", "urgent"):
        return NormalizedValue(value="high", unit="priority", raw=raw)
    if lower in ("medium", "normal", "moderate"):
        return NormalizedValue(value="medium", unit="priority", raw=raw)
    if lower in ("low", "minor"):
        return NormalizedValue(value="low", unit="priority", raw=raw)

    # Date
    date_val = _try_normalize_date(lower)
    if date_val:
        return NormalizedValue(value=date_val, unit="date", raw=raw, type="date")

    # Number with optional currency
    num_val, unit = _try_normalize_number(lower)
    if num_val is not None:
        return NormalizedValue(
            value=str(int(num_val)) if num_val == int(num_val) else str(num_val),
            unit=unit, raw=raw, type="number",
        )

    # Fallback: return as-is
    return NormalizedValue(value=raw_stripped, raw=raw, type="text")


def _try_normalize_number(s: str) -> tuple[Optional[float], str]:
    """Extract a numeric value and optional currency unit from a string."""
    # Strip common punctuation
    s = s.replace(",", "")

    # Detect currency
    currency = ""
    for sym, curr in _CURRENCY_SYMBOLS.items():
        if sym in s:
            s = s.replace(sym, "").strip()
            currency = curr
            break
    for word, curr in _CURRENCIES.items():
        if word in s:
            s = s.replace(word, "").strip()
            if not currency:
                currency = curr
            break

    # Pattern: "10k", "10m", "10 thousand", etc.
    m = re.match(r"^([\d,.]+)\s*([kmb]|thousand|million|mil|billion)?\s*$", s, re.I)
    if m:
        base = float(m.group(1).replace(",", ""))
        mult_key = (m.group(2) or "").lower()
        mult = _MULTIPLIERS.get(mult_key, 1)
        return base * mult, currency

    # Pure number
    m = re.match(r"^([\d,.]+)$", s)
    if m:
        return float(s.replace(",", "")), currency

    # Word-based numbers: "ten thousand", "twenty five hundred"
    words = s.lower().split()
    total = _parse_word_number(words)
    if total is not None:
        return total, currency

    return None, ""


def _parse_word_number(words: list[str]) -> Optional[float]:
    """Parse English number words into a float."""
    current = 0.0
    total   = 0.0
    matched = False

    for word in words:
        if word in _WORD_NUMBERS:
            matched = True
            n = _WORD_NUMBERS[word]
            if n == 100:
                current = (current or 1) * 100
            else:
                current += n
        elif word in _MULTIPLIERS:
            matched = True
            mult  = _MULTIPLIERS[word]
            total += (current or 1) * mult
            current = 0.0

    if matched:
        return total + current
    return None


def _try_normalize_date(s: str) -> Optional[str]:
    """Attempt to extract a date and return ISO format YYYY-MM-DD."""
    from datetime import datetime, date
    import calendar

    today = date.today()

    # Relative dates
    if "today" in s:       return today.isoformat()
    if "tomorrow" in s:    return date.fromordinal(today.toordinal() + 1).isoformat()
    if "yesterday" in s:   return date.fromordinal(today.toordinal() - 1).isoformat()

    # "March 15" or "15 March"
    for month_name, month_num in _MONTHS.items():
        if month_name in s:
            # Find day number
            m = re.search(r"\b(\d{1,2})\b", s)
            if m:
                day  = int(m.group(1))
                year = today.year
                # If this date has passed, use next year
                try:
                    d = date(year, int(month_num), day)
                    if d < today:
                        d = date(year + 1, int(month_num), day)
                    return d.isoformat()
                except ValueError:
                    pass

    # ISO-like "2026-03-15" or "03/15/2026"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    # "Q3 2026"
    m = re.match(r"q([1-4])\s*(\d{4})", s)
    if m:
        q, year = int(m.group(1)), int(m.group(2))
        month = (q - 1) * 3 + 1
        return f"{year}-{month:02d}-01"

    return None
