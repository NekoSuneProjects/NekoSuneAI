from __future__ import annotations

import re


_STOP_RE = re.compile(
    r"^\s*(?:(?:hey\s+)?neko(?:suneai)?[\s,]+)?(?:stop|be quiet|silence|shut up)(?:\s+(?:now|everything|talking|speaking|music|audio))?[.!]?\s*$",
    re.IGNORECASE,
)


def is_global_stop_command(text: str) -> bool:
    """Return true only for short, unambiguous interruption commands."""
    return bool(_STOP_RE.fullmatch(text or ""))
