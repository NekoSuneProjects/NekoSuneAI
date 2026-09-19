from __future__ import annotations

import codecs
import sys
from typing import Any

_FALLBACK_ENCODING = "utf-8"


def console_safe_text(value: Any) -> str:
    """Render ``value`` so it can be printed without a UnicodeEncodeError.

    Windows consoles frequently report a legacy code page that cannot carry the
    emoji and CJK text the assistant likes to emit. Anything the active stdout
    encoding accepts is passed through untouched; only genuinely unencodable
    text pays for a lossy round-trip, where unsupported code points collapse to
    the replacement character.
    """
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or _FALLBACK_ENCODING

    try:
        codecs.lookup(encoding)
    except (LookupError, TypeError):
        return text

    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        pass
    except Exception:
        return text
    else:
        return text

    try:
        return text.encode(encoding, "replace").decode(encoding, "replace")
    except Exception:
        return text
