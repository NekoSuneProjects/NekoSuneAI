"""Microphone device enumeration and resolution for wake-word capture.

This node never runs local speech recognition -- `audio.listen` and wake-word
capture record locally and relay the audio to the backend's
`/api/nodes/media/stt`. So the only thing needed from PortAudio here is
*which input device to open*.

That matters because the inherited version of this module was the full Docker
backend's STT stack (SpeechRecognition, torch, faster-whisper, vosk), and its
`_require_audio()` guard demanded `SpeechRecognition` before it would resolve
a device. `requirements-pi-proxy.txt` deliberately does not install
SpeechRecognition -- this node has no use for it -- so wake word could never
start: resolving the microphone raised "Voice support is not installed.
Install the optional extras with: pip install -r requirements-voice.txt",
naming a requirements file this branch does not even have. The wake-word
thread died on that every time and the status page reported it as the reason.

Resolving a device needs sounddevice and nothing else, so that is all this
module asks for now.
"""
from __future__ import annotations

import re
from typing import Any

# sounddevice (PortAudio) is a real dependency of wake-word capture, but keep
# the import guarded so the agent still starts, pairs, and relays commands on
# a box with no PortAudio at all -- wake word is off by default anyway.
try:
    import sounddevice as sd
except (ImportError, OSError):  # OSError: PortAudio shared library missing
    sd = None  # type: ignore[assignment]

MIC_EXTRAS_HINT = (
    "Microphone support is unavailable: the 'sounddevice' package or its "
    "PortAudio library is missing. Install this node's requirements "
    "(pip install -r requirements-pi-proxy.txt) and, on Raspberry Pi OS, "
    "the PortAudio system library (apt install libportaudio2)."
)


def _require_audio() -> None:
    """Raise a clear error when PortAudio/sounddevice is genuinely missing."""
    if sd is None:
        raise RuntimeError(MIC_EXTRAS_HINT)


def get_default_input_device_index() -> int | None:
    if sd is None:
        return None
    default_device = sd.default.device
    candidate = default_device[0] if isinstance(default_device, (list, tuple)) else default_device
    if candidate is None:
        return None
    try:
        candidate_index = int(candidate)
    except (TypeError, ValueError):
        return None
    return candidate_index if candidate_index >= 0 else None


def normalize_audio_device_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name).strip()
    return re.sub(
        r"\s+\((mme|wasapi|wdm-ks|directsound|asio)\)$", "", cleaned, flags=re.IGNORECASE,
    )


def resolve_input_device_info(device_index: int | None) -> dict[str, Any]:
    """Resolve a configured mic index (or None for the default) to a device.

    Returns the concrete index, so callers can keep opening the same physical
    microphone even if PortAudio later reshuffles its defaults -- which it
    does when a Bluetooth speaker becomes the host default.
    """
    _require_audio()
    try:
        if device_index is None:
            device = sd.query_devices(kind="input")
            resolved_index = get_default_input_device_index()
        else:
            device = sd.query_devices(device_index, "input")
            resolved_index = device_index
    except Exception as exc:
        chosen = "the default microphone" if device_index is None else f"microphone #{device_index}"
        raise RuntimeError(
            f"I couldn't access {chosen}. Run `arecord -l` to list capture devices, "
            "then set mic_device_index or mic_alsa_device in this node's config."
        ) from exc

    device_name = str(device.get("name", "Input device"))
    default_sample_rate = device.get("default_samplerate")
    if not isinstance(default_sample_rate, (int, float)) or default_sample_rate <= 0:
        raise RuntimeError(f"The microphone '{device_name}' did not report a valid sample rate.")

    return {
        "index": resolved_index,
        "name": normalize_audio_device_name(device_name),
        "default_sample_rate": int(default_sample_rate),
        "max_input_channels": max(1, int(device.get("max_input_channels", 1))),
    }


def list_input_devices() -> list[dict[str, Any]]:
    """Every PortAudio capture device, for diagnostics and the status page."""
    if sd is None:
        return []
    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise RuntimeError(f"I couldn't list microphone devices. {exc}") from exc

    default_index = get_default_input_device_index()
    return [
        {
            "index": index,
            "name": normalize_audio_device_name(str(device.get("name", "Input device"))),
            "max_input_channels": int(device.get("max_input_channels", 0)),
            "is_default": index == default_index,
        }
        for index, device in enumerate(devices)
        if isinstance(device.get("max_input_channels"), (int, float))
        and device.get("max_input_channels", 0) > 0
    ]
