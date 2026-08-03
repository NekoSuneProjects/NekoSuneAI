"""NekoSuneAI - RVC voice conversion for normal chat replies.

Distinct from the singing RVC backend (nekosuneai/singing.py's RvcSingingEngine) —
this converts every spoken chat reply (whatever XTTS/gTTS just rendered) through a
trained RVC voice model, so NekoSuneAI can sound like a specific voice with a
Pitch control, independent of which XTTS speaker/gTTS language produced the source
audio. Optional and lazy-imported, same pattern as singing.py.
"""
from __future__ import annotations

import os
from pathlib import Path

from .config import Config

RVC_INSTALL_HINT = (
    "RVC is not installed. Install an RVC inference package (e.g. rvc-python) "
    "or set RVC_CHAT_ENABLED=false."
)


def apply_rvc(input_path: Path, config: Config) -> Path:
    """Convert *input_path* through the configured chat RVC model, in place.

    No-ops (returns *input_path* unchanged) when chat RVC is off or unconfigured.
    Raises RuntimeError on failure so callers can decide whether to fall back to
    the un-converted voice rather than break the reply.
    """
    if not config.rvc_chat_enabled:
        return input_path
    if not config.rvc_chat_model_path:
        raise RuntimeError(
            "Set RVC_CHAT_MODEL_PATH in .env to your trained RVC model (.pth)."
        )

    try:
        from rvc_python.infer import RVCInference  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dep
        raise RuntimeError(RVC_INSTALL_HINT) from exc

    # Convert to a sibling temp file first — infer_file reading and writing the
    # same path in place is not something the library guarantees is safe.
    converted_path = input_path.with_name(f"_rvc_{input_path.name}")
    try:
        rvc = RVCInference(model_path=config.rvc_chat_model_path)
        rvc.set_params(
            f0up_key=config.rvc_chat_pitch,
            index_rate=config.rvc_chat_index_rate,
            protect=config.rvc_chat_protect,
        )
        rvc.infer_file(str(input_path), str(converted_path))
    except Exception as exc:
        raise RuntimeError(f"RVC voice conversion failed: {exc}") from exc

    os.replace(converted_path, input_path)
    return input_path
