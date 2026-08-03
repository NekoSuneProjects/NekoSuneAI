"""Lightweight language detection for per-language TTS voicing.

Returns a language code XTTS understands (and that ``normalize_gtts_language``
maps for gTTS), so NekoSuneAI can speak a Japanese line in Japanese, a Russian line
in Russian, etc. Script detection (Kana/Hangul/CJK/Cyrillic/Arabic/Devanagari)
needs no dependencies and covers the high-value non-Latin cases; Latin-script
languages use ``langdetect`` when installed, else fall back to the default.
"""
from __future__ import annotations

# XTTS-v2 supported languages (gTTS accepts the same via normalize_gtts_language).
_XTTS_LANGS = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs",
    "ar", "zh-cn", "ja", "ko", "hu", "hi",
}


def _script_counts(text: str) -> dict[str, int]:
    counts = {"kana": 0, "hangul": 0, "cjk": 0, "cyrillic": 0, "arabic": 0, "devanagari": 0, "latin": 0}
    for ch in text:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF:
            counts["kana"] += 1
        elif 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF:
            counts["hangul"] += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            counts["cjk"] += 1
        elif 0x0400 <= o <= 0x04FF:
            counts["cyrillic"] += 1
        elif 0x0600 <= o <= 0x06FF:
            counts["arabic"] += 1
        elif 0x0900 <= o <= 0x097F:
            counts["devanagari"] += 1
        elif (0x41 <= o <= 0x5A) or (0x61 <= o <= 0x7A):
            counts["latin"] += 1
    return counts


def detect_language(text: str, default: str = "en") -> str:
    """Best-effort language code (XTTS-compatible). Returns ``default`` when unsure."""
    text = (text or "").strip()
    if len(text) < 2:
        return default
    c = _script_counts(text)
    # Non-Latin scripts are unambiguous enough to switch on a single character.
    if c["kana"] > 0:
        return "ja"
    if c["hangul"] > 0:
        return "ko"
    if c["cyrillic"] >= 2:
        return "ru"
    if c["arabic"] >= 2:
        return "ar"
    if c["devanagari"] >= 2:
        return "hi"
    if c["cjk"] > 0 and c["latin"] <= c["cjk"]:
        return "zh-cn"  # CJK with no kana → Chinese
    # Latin script: defer to langdetect if available, mapping to the XTTS set.
    if c["latin"] >= 3:
        try:
            from langdetect import detect  # type: ignore

            code = detect(text).lower()
            code = {"zh-cn": "zh-cn", "zh-tw": "zh-cn"}.get(code, code)
            if code in _XTTS_LANGS:
                return code
        except Exception:
            pass
    return default if default in _XTTS_LANGS or default else "en"
