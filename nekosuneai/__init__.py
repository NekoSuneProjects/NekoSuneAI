from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Ranking tables for PortAudio auto-routing. Each entry pairs a set of
# lower-cased name fragments with the rank awarded to the first fragment that
# matches; tables are scanned top to bottom, so earlier rows win ties.
_CAPTURE_RANKS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("kinect", "xbox nui"), 0),
    (("usb",), 1),
    (("pulse",), 3),
    (("pipewire",), 4),
    (("default",), 5),
    (("bluez", "bluetooth"), 20),
    (("monitor",), 30),
)
_CAPTURE_FALLBACK_RANK = 8

_PLAYBACK_RANKS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("pulse",), 0),
    (("pipewire",), 1),
    (("default",), 2),
)
_PLAYBACK_FALLBACK_RANK = 3

_NO_DEVICE = -1


def _coerce_index(value: object) -> int:
    """Return a non-negative PortAudio index, or _NO_DEVICE when unusable."""
    try:
        index = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _NO_DEVICE
    return index if index >= 0 else _NO_DEVICE


def _channel_count(device: object, key: str) -> int:
    try:
        return int(device.get(key, 0))  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return 0


def _rank_of(name: str, table: tuple[tuple[tuple[str, ...], int], ...], fallback: int) -> int:
    for fragments, rank in table:
        if any(fragment in name for fragment in fragments):
            return rank
    return fallback


def _highest_ranked(
    devices: object,
    channel_key: str,
    table: tuple[tuple[tuple[str, ...], int], ...],
    fallback: int,
) -> int:
    """Pick the best-ranked device exposing at least one channel of channel_key."""
    best_rank: int | None = None
    best_index = _NO_DEVICE
    for index, device in enumerate(devices):  # type: ignore[call-overload]
        if _channel_count(device, channel_key) <= 0:
            continue
        name = str(device.get("name", "")).strip().lower()
        rank = _rank_of(name, table, fallback)
        if best_rank is None or rank < best_rank:
            best_rank, best_index = rank, index
    return best_index


def _host_session_routing() -> bool:
    """True when a host PulseAudio/PipeWire session is driving audio for us."""
    if os.name == "nt":
        return False
    return bool(os.environ.get("PULSE_SERVER") or os.environ.get("PIPEWIRE_REMOTE"))


def _current_defaults(sd: object) -> tuple[int, int]:
    configured = sd.default.device  # type: ignore[attr-defined]
    if isinstance(configured, (tuple, list)) and len(configured) >= 2:
        return _coerce_index(configured[0]), _coerce_index(configured[1])
    return _NO_DEVICE, _NO_DEVICE


def _repair_session_audio_default() -> None:
    """Repair Docker PortAudio defaults without coupling mic and speaker.

    Output should follow the host PulseAudio/PipeWire default sink so Bluetooth
    speakers such as Alexa work naturally. Input auto-selection is deliberately
    separate: prefer Kinect/Xbox NUI and other USB capture hardware over generic
    Pulse/PipeWire, Bluetooth, or monitor inputs. This prevents changing the
    speaker route from silently stealing the wake-word microphone.
    """
    if not _host_session_routing():
        return

    try:
        import sounddevice as sd
    except (ImportError, OSError):
        return

    try:
        capture_index, playback_index = _current_defaults(sd)
        devices = sd.query_devices()
    except Exception:
        return

    device_count = len(devices)

    # Capture is re-ranked unconditionally: a valid PortAudio default can still
    # point at the wrong source once a Bluetooth card shows up mid-session.
    ranked_capture = _highest_ranked(
        devices, "max_input_channels", _CAPTURE_RANKS, _CAPTURE_FALLBACK_RANK
    )
    if ranked_capture != _NO_DEVICE:
        capture_index = ranked_capture
    elif capture_index >= device_count:
        capture_index = _NO_DEVICE

    # Playback stays host-session driven. An already-valid sink (say, one picked
    # through pactl) is left untouched; only broken defaults get re-derived.
    playback_usable = (
        0 <= playback_index < device_count
        and _channel_count(devices[playback_index], "max_output_channels") > 0
    )
    if not playback_usable:
        playback_index = _highest_ranked(
            devices, "max_output_channels", _PLAYBACK_RANKS, _PLAYBACK_FALLBACK_RANK
        )

    if capture_index == _NO_DEVICE and playback_index == _NO_DEVICE:
        return

    sd.default.device = (capture_index, playback_index)


_repair_session_audio_default()

__all__: list[str] = []
