from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _valid_device_index(value: object) -> bool:
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


def _repair_session_audio_default() -> None:
    """Repair invalid PortAudio defaults for Docker host-session audio.

    PulseAudio/PipeWire can be reachable through its Unix socket while
    PortAudio still reports ``-1`` for one or both default devices.  Speaker
    auto-routing and Bluetooth recovery should not be allowed to break the
    microphone side, so input and output defaults are repaired independently.

    Input preference intentionally favors Kinect/USB capture hardware before a
    generic Pulse/PipeWire/default device.  Output preference remains the
    session Pulse/PipeWire bridge so the host default sink (including Alexa)
    continues to control where TTS is played.
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
        devices = sd.query_devices()
    except Exception:
        return

    input_index = int(current_input) if _valid_device_index(current_input) else -1
    output_index = int(current_output) if _valid_device_index(current_output) else -1

    # Validate that a supposedly-valid input/output index actually has channels.
    if 0 <= input_index < len(devices):
        try:
            if int(devices[input_index].get("max_input_channels", 0)) <= 0:
                input_index = -1
        except (TypeError, ValueError):
            input_index = -1
    elif input_index >= 0:
        input_index = -1

    if 0 <= output_index < len(devices):
        try:
            if int(devices[output_index].get("max_output_channels", 0)) <= 0:
                output_index = -1
        except (TypeError, ValueError):
            output_index = -1
    elif output_index >= 0:
        output_index = -1

    if input_index < 0:
        input_candidates: list[tuple[int, int]] = []
        for index, device in enumerate(devices):
            try:
                if int(device.get("max_input_channels", 0)) <= 0:
                    continue
            except (TypeError, ValueError):
                continue

            name = str(device.get("name", "")).strip().lower()
            # Avoid loopback/monitor and Bluetooth headset sources when a real
            # USB microphone is available.  A connected Alexa is output-only in
            # the common setup and must never displace the Kinect wake mic.
            if "monitor" in name:
                priority = 20
            elif "bluez" in name or "bluetooth" in name:
                priority = 15
            elif "kinect" in name or "xbox nui" in name:
                priority = 0
            elif "usb" in name:
                priority = 1
            elif "pulse" in name:
                priority = 2
            elif "pipewire" in name:
                priority = 3
            elif name in {"default", "sysdefault"} or "default" in name:
                priority = 4
            else:
                priority = 8
            input_candidates.append((priority, index))

        if input_candidates:
            _, input_index = min(input_candidates)

    if output_index < 0:
        output_candidates: list[tuple[int, int]] = []
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
            output_candidates.append((priority, index))

        if output_candidates:
            _, output_index = min(output_candidates)

    if input_index < 0 and output_index < 0:
        return

    sd.default.device = (input_index, output_index)


_repair_session_audio_default()

__all__: list[str] = []
