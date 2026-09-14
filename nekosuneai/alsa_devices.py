"""Resolve which ALSA capture device `arecord` should actually open.

Wake-word detection and command capture were using two different microphones.
`wakeword.py` resolves a concrete PortAudio index (and deliberately so -- see
its comment about Bluetooth reshuffling PortAudio's defaults), but `_record_wav`
shelled out to a bare `arecord` with no `-D`, which always opens the ALSA
*default* device. On a Pi whose default has been taken over by a Bluetooth
speaker -- or which simply has onboard audio ahead of a USB mic -- the wake word
was heard on the USB microphone and the command that followed was recorded from
something else entirely. The result is a node that chimes and then transcribes
silence.

PortAudio indices are not ALSA device names, so this module bridges the two:

* sounddevice reports Linux devices as e.g. ``USB Audio Device: - (hw:1,0)``,
  so the ALSA address is usually recoverable straight from the device name;
* failing that, `arecord -l` is matched by card name;
* an explicit ``mic_alsa_device`` in the node config always wins, for setups
  where neither guess is right.

Everything resolves to ``plughw:`` rather than ``hw:``. The Xbox 360 Kinect
microphone array is a 4-channel 16-bit device that will not open as the mono
16 kHz stream the backend's STT endpoint requires; ``plughw`` puts ALSA's
conversion plugin in front so the downmix and resample happen in ALSA instead
of failing the capture outright.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

# "USB Audio Device: - (hw:1,0)" / "Kinect USB Audio: USB Audio (hw:2,0)"
_HW_IN_NAME_RE = re.compile(r"\((?:plug)?hw:(\d+)\s*,\s*(\d+)\)")
# `arecord -l` card/device lines:
# "card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]"
_ARECORD_LINE_RE = re.compile(
    r"^card\s+(\d+):\s*(\S+)\s*\[([^\]]*)\],\s*device\s+(\d+):\s*([^\[]*)\[([^\]]*)\]",
    re.M,
)

# Substrings that identify the Xbox 360 Kinect's microphone array across the
# several names BlueZ/ALSA/the kernel give it depending on firmware and driver.
_KINECT_HINTS = ("kinect", "xbox nui", "xbox360", "xbox 360")


def alsa_capture_devices() -> list[dict[str, Any]]:
    """Every ALSA capture device `arecord -l` can see, as plughw addresses."""
    if not shutil.which("arecord"):
        return []
    try:
        result = subprocess.run(
            ["arecord", "-l"], capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    devices: list[dict[str, Any]] = []
    for card, card_id, card_name, device, _device_id, device_name in _ARECORD_LINE_RE.findall(
        result.stdout
    ):
        label = card_name.strip() or card_id.strip()
        detail = device_name.strip()
        devices.append({
            "alsa_device": f"plughw:{card},{device}",
            "card": int(card),
            "device": int(device),
            "name": f"{label} — {detail}" if detail and detail != label else label,
            "is_kinect": any(hint in f"{label} {detail}".lower() for hint in _KINECT_HINTS),
        })
    return devices


def alsa_device_from_portaudio_name(name: str) -> str:
    """Pull an ALSA address out of a PortAudio device name, if it carries one."""
    match = _HW_IN_NAME_RE.search(name or "")
    if not match:
        return ""
    return f"plughw:{int(match.group(1))},{int(match.group(2))}"


def _match_by_name(name: str, devices: list[dict[str, Any]]) -> str:
    """Best-effort match of a PortAudio device name against `arecord -l`."""
    cleaned = re.sub(r"\s*\((?:plug)?hw:[^)]*\)\s*", " ", name or "").strip().lower()
    if not cleaned:
        return ""
    # Longest shared token run wins, so "USB Audio Device" matches its card
    # rather than the first card that happens to contain the word "USB".
    tokens = [token for token in re.split(r"[^a-z0-9]+", cleaned) if len(token) > 2]
    if not tokens:
        return ""
    best, best_score = "", 0
    for item in devices:
        target = item["name"].lower()
        score = sum(1 for token in tokens if token in target)
        if score > best_score:
            best, best_score = item["alsa_device"], score
    return best


def resolve_capture_device(
    alsa_device: str = "",
    portaudio_name: str = "",
    prefer_kinect: bool = False,
) -> str:
    """Decide what to pass to `arecord -D`.

    Returns an empty string when nothing better than the ALSA default can be
    determined -- the caller then omits ``-D`` and behaves as before, rather
    than guessing at a device that may not exist.
    """
    explicit = str(alsa_device or "").strip()
    if explicit:
        return explicit

    from_name = alsa_device_from_portaudio_name(portaudio_name)
    if from_name:
        return from_name

    devices = alsa_capture_devices()
    if not devices:
        return ""

    matched = _match_by_name(portaudio_name, devices)
    if matched:
        return matched

    if prefer_kinect:
        kinect = next((item for item in devices if item["is_kinect"]), None)
        if kinect:
            return kinect["alsa_device"]

    # A single USB capture card is unambiguous; more than one and guessing
    # would reintroduce exactly the wrong-microphone bug this module fixes.
    if len(devices) == 1:
        return devices[0]["alsa_device"]
    return ""
