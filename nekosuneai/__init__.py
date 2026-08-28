from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _valid_device_index(value: object) -> bool:
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


def _repair_session_audio_default() -> None:
    """Repair Docker PortAudio defaults without coupling mic and speaker.

    Output should follow the host PulseAudio/PipeWire default sink so Bluetooth
    speakers such as Alexa work naturally. Input auto-selection is deliberately
    separate: prefer Kinect/Xbox NUI and other USB capture hardware over generic
    Pulse/PipeWire, Bluetooth, or monitor inputs. This prevents changing the
    speaker route from silently stealing the wake-word microphone.
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

    # Always rank visible inputs when auto-routing is active. A valid PortAudio
    # default can still be the wrong source after a Bluetooth card appears.
    input_candidates: list[tuple[int, int]] = []
    for index, device in enumerate(devices):
        try:
            if int(device.get("max_input_channels", 0)) <= 0:
                continue
        except (TypeError, ValueError):
            continue

        name = str(device.get("name", "")).strip().lower()
        if "kinect" in name or "xbox nui" in name:
            priority = 0
        elif "usb" in name:
            priority = 1
        elif "pulse" in name:
            priority = 3
        elif "pipewire" in name:
            priority = 4
        elif name in {"default", "sysdefault"} or "default" in name:
            priority = 5
        elif "bluez" in name or "bluetooth" in name:
            priority = 20
        elif "monitor" in name:
            priority = 30
        else:
            priority = 8
        input_candidates.append((priority, index))

    if input_candidates:
        _, input_index = min(input_candidates)
    elif input_index >= len(devices):
        input_index = -1

    # Output remains host-session driven. Preserve an already-valid output so a
    # Bluetooth sink selected through pactl keeps working; only repair -1/bad
    # PortAudio defaults here.
    output_valid = False
    if 0 <= output_index < len(devices):
        try:
            output_valid = int(devices[output_index].get("max_output_channels", 0)) > 0
        except (TypeError, ValueError):
            output_valid = False

    if not output_valid:
        output_index = -1
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
