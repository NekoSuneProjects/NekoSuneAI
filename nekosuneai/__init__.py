from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _repair_session_audio_default() -> None:
    """Repair PortAudio's `-1` default when Docker exposes host session audio.

    PulseAudio/PipeWire can be perfectly reachable through its Unix socket while
    PortAudio still reports no default output. NekoSuneAI's TTS path asks
    sounddevice for the default speaker, so choose the best visible session
    output once at process startup instead of failing with "Error querying
    device -1".
    """
    if os.name == "nt":
        return
    if not (os.environ.get("PULSE_SERVER") or os.environ.get("PIPEWIRE_REMOTE")):
        return

    try:
        import sounddevice as sd
    except (ImportError, OSError):
        return

    try:
        current = sd.default.device
        if isinstance(current, (tuple, list)) and len(current) >= 2:
            current_input, current_output = current[0], current[1]
        else:
            current_input, current_output = -1, -1
        if current_output is not None and int(current_output) >= 0:
            return

        devices = sd.query_devices()
    except Exception:
        return

    candidates: list[tuple[int, int]] = []
    for index, device in enumerate(devices):
        try:
            if int(device.get("max_output_channels", 0)) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        name = str(device.get("name", "")).strip().lower()
        if "pulse" in name:
            priority = 0
        elif "pipewire" in name:
            priority = 1
        elif name in {"default", "sysdefault"} or "default" in name:
            priority = 2
        else:
            priority = 3
        candidates.append((priority, index))

    if not candidates:
        return

    _, output_index = min(candidates)
    try:
        input_index = int(current_input)
    except (TypeError, ValueError):
        input_index = -1
    sd.default.device = (input_index, output_index)


_repair_session_audio_default()

__all__: list[str] = []
