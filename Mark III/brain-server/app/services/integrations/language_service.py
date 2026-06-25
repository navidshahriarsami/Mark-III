"""
MARK III — Language Service

Detects the language of a Whisper transcription and provides
language-aware context for Qwen responses and TTS selection.

Whisper already detects language during transcription — this service
extracts that signal and routes it through the pipeline so MARK
always responds in the user's spoken language.

Supported languages (Phase 18):
  en — English
  bn — Bengali (বাংলা)
  ar — Arabic (العربية)
  fr — French
  es — Spanish
  ja — Japanese
  zh — Chinese
  hi — Hindi
  de — German
  pt — Portuguese
  tr — Turkish
  ko — Korean
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LanguageResult:
    code:        str    # ISO 639-1 code (e.g. "en", "bn")
    name:        str    # English name
    confidence:  float  # 0.0–1.0 from Whisper
    native_name: str    # Name in that language


_LANG_MAP: dict[str, LanguageResult] = {
    "en": LanguageResult("en", "English",    1.0, "English"),
    "bn": LanguageResult("bn", "Bengali",    1.0, "বাংলা"),
    "ar": LanguageResult("ar", "Arabic",     1.0, "العربية"),
    "fr": LanguageResult("fr", "French",     1.0, "Français"),
    "es": LanguageResult("es", "Spanish",    1.0, "Español"),
    "ja": LanguageResult("ja", "Japanese",   1.0, "日本語"),
    "zh": LanguageResult("zh", "Chinese",    1.0, "中文"),
    "hi": LanguageResult("hi", "Hindi",      1.0, "हिन्दी"),
    "de": LanguageResult("de", "German",     1.0, "Deutsch"),
    "pt": LanguageResult("pt", "Portuguese", 1.0, "Português"),
    "tr": LanguageResult("tr", "Turkish",    1.0, "Türkçe"),
    "ko": LanguageResult("ko", "Korean",     1.0, "한국어"),
}

# Current session language (updated after each Whisper transcription)
_current_language: LanguageResult = _LANG_MAP["en"]


def from_whisper(language_code: str, probability: float = 1.0) -> LanguageResult:
    """
    Create a LanguageResult from Whisper's detected language code.
    Call this right after Whisper transcription with info.language and
    info.language_probability.
    """
    global _current_language
    code = (language_code or "en").lower()[:2]
    result = _LANG_MAP.get(code, LanguageResult(code, code.upper(), probability, code))
    result.confidence = probability
    _current_language = result
    return result


def get_current() -> LanguageResult:
    return _current_language


def build_language_instruction(lang: LanguageResult) -> str:
    """
    Returns a system prompt instruction telling Qwen to respond
    in the detected language. Empty string for English (default).
    """
    if lang.code == "en":
        return ""
    return (
        f"IMPORTANT: The user is speaking {lang.name} ({lang.native_name}). "
        f"You MUST respond in {lang.name}. Do not switch to English."
    )


def is_rtl(lang: LanguageResult) -> bool:
    """True for right-to-left languages (Arabic, Hebrew, etc.)."""
    return lang.code in ("ar", "he", "fa", "ur")
