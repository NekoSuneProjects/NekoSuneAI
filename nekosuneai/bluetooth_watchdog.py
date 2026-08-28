"""Auto-detect and keep a pre-paired Bluetooth speaker connected on Linux.

The host owns BlueZ and PipeWire/PulseAudio.  In Docker we talk to those host
services through the mounted system D-Bus and audio-session sockets; the
container does not pair devices itself.  A speaker only needs to be paired (and
ideally trusted) on the host once.  After that NekoSuneAI can discover it,
reconnect it and make its BlueZ sink the default output automatically.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from typing import Callable

from .config import Config


_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
_DEVICE_LINE_RE = re.compile(
    r"^\s*Device\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s+(.+?)\s*$",
    re.M,
)
_BLUEZ_SINK_MAC_RE = re.compile(
    r"bluez_(?:output|sink)\.([0-9A-Fa-f]{2}(?:_[0-9A-Fa-f]{2}){5})(?:\.|$)",
    re.I,
)
_AUDIO_UUID_MARKERS = (
    "audio sink",
    "advanced audio distribution",
    "0000110b-0000-1000-8000-00805f9b34fb",  # A2DP Audio Sink
    "0000110d-0000-1000-8000-00805f9b34fb",  # A2DP profile
)
_PREFERRED_SPEAKER_NAMES = ("alexa", "echo", "amazon")


class BluetoothSpeakerWatchdog:
    def __init__(self, config: Config, notify: Callable[[str], None]) -> None:
        self.config = config
        self.notify = notify
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_connected: bool | None = None
        self._last_ready: bool | None = None
        self._detected_address = ""
        self._detected_name = ""
        self._detected_sink = ""

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def start(self) -> None:
        # Address is deliberately optional.  When it is blank (or still contains
        # the example AA:BB:... value) the watchdog discovers a paired audio
        # device automatically, preferring Amazon Alexa/Echo names.
        if not self.config.bluetooth_reconnect_enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="bluetooth-speaker-watchdog",
        )
        self._thread.start()

    def status(self) -> dict[str, object]:
        configured = (self.config.bluetooth_speaker_address or "").strip()
        return {
            "enabled": self.config.bluetooth_reconnect_enabled,
            "configured_address": configured,
            "address": self._detected_address or configured,
            "name": self._detected_name,
            "sink": self._detected_sink,
            "auto_detected": bool(
                self._detected_address
                and self._detected_address.lower() != configured.lower()
            ),
            "connected": self._last_connected,
            "ready": self._last_ready,
            "running": bool(self._thread and self._thread.is_alive()),
        }

    @staticmethod
    def _info_value(info: str, key: str) -> str:
        match = re.search(
            rf"^\s*{re.escape(key)}:\s*(.+?)\s*$",
            info,
            re.I | re.M,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _info_flag(info: str, key: str) -> bool:
        return BluetoothSpeakerWatchdog._info_value(info, key).lower() == "yes"

    @staticmethod
    def _is_audio_device_info(info: str) -> bool:
        lowered = info.lower()
        if any(marker in lowered for marker in _AUDIO_UUID_MARKERS):
            return True
        # BlueZ commonly labels Bluetooth speakers/headsets as audio-card.
        return bool(re.search(r"^\s*Icon:\s*audio-(?:card|headset)\s*$", info, re.I | re.M))

    def _device_info(self, address: str) -> str:
        if not shutil.which("bluetoothctl"):
            return ""
        result = self._run(["bluetoothctl", "info", address])
        if result.returncode != 0:
            return ""
        if not re.search(r"^\s*Device\s+", result.stdout, re.M):
            return ""
        return result.stdout

    def _is_connected(self, address: str) -> bool:
        if not shutil.which("bluetoothctl"):
            raise RuntimeError(
                "bluetoothctl is unavailable. Install BlueZ or use the Docker image."
            )
        info = self._device_info(address)
        return bool(info) and self._info_flag(info, "Connected")

    def _discover_paired_audio_device(self) -> tuple[str, str] | None:
        """Find the best host-paired Bluetooth audio device.

        Alexa/Echo/Amazon names win first, then already-connected devices, then
        trusted/paired audio devices.  Keyboards, controllers and other
        Bluetooth devices are ignored because they do not expose an audio-sink
        UUID/icon.
        """
        if not shutil.which("bluetoothctl"):
            return None
        result = self._run(["bluetoothctl", "devices"])
        if result.returncode != 0:
            return None

        candidates: list[tuple[tuple[int, int, int, int, str], str, str]] = []
        for address, listed_name in _DEVICE_LINE_RE.findall(result.stdout):
            info = self._device_info(address)
            if not info or not self._is_audio_device_info(info):
                continue
            name = (
                self._info_value(info, "Alias")
                or self._info_value(info, "Name")
                or listed_name.strip()
                or address
            )
            lowered_name = name.lower()
            preferred = 0 if any(x in lowered_name for x in _PREFERRED_SPEAKER_NAMES) else 1
            connected = 0 if self._info_flag(info, "Connected") else 1
            trusted = 0 if self._info_flag(info, "Trusted") else 1
            paired = 0 if self._info_flag(info, "Paired") else 1
            score = (preferred, connected, trusted, paired, name.lower())
            candidates.append((score, address.upper(), name))

        if not candidates:
            return None
        _score, address, name = min(candidates, key=lambda item: item[0])
        return address, name

    def _bluez_sinks(self) -> list[str]:
        if not shutil.which("pactl"):
            return []
        result = self._run(["pactl", "list", "short", "sinks"])
        if result.returncode != 0:
            return []
        sinks: list[str] = []
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) >= 2 and "bluez" in columns[1].lower():
                sinks.append(columns[1])
        return sinks

    @staticmethod
    def _address_from_sink(sink: str) -> str:
        match = _BLUEZ_SINK_MAC_RE.search(sink)
        if not match:
            return ""
        return match.group(1).replace("_", ":").upper()

    def _discover_from_existing_sink(self) -> tuple[str, str] | None:
        sinks = self._bluez_sinks()
        if not sinks:
            return None
        # A connected BlueZ sink is already a valid speaker even if bluetoothctl
        # cannot enumerate devices from inside a restricted container.
        for sink in sinks:
            address = self._address_from_sink(sink)
            if not address:
                continue
            info = self._device_info(address)
            name = (
                self._info_value(info, "Alias")
                or self._info_value(info, "Name")
                or "Bluetooth speaker"
            )
            return address, name
        return None

    def _resolve_target(self) -> tuple[str, str] | None:
        configured = (self.config.bluetooth_speaker_address or "").strip()
        if _MAC_RE.fullmatch(configured):
            info = self._device_info(configured)
            # Only pin to a configured MAC when BlueZ actually knows it.  This
            # intentionally ignores the AA:BB:CC:DD:EE:FF example placeholder.
            if info and self._is_audio_device_info(info):
                name = (
                    self._info_value(info, "Alias")
                    or self._info_value(info, "Name")
                    or configured
                )
                return configured.upper(), name

        discovered = self._discover_paired_audio_device()
        if discovered:
            return discovered
        return self._discover_from_existing_sink()

    def _activate_a2dp_profile(self, address: str) -> None:
        """Best-effort A2DP activation for PipeWire/PulseAudio BlueZ cards."""
        if not shutil.which("pactl"):
            return
        result = self._run(["pactl", "list", "short", "cards"])
        if result.returncode != 0:
            return
        address_key = address.replace(":", "_").lower()
        card = ""
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) >= 2 and "bluez" in columns[1].lower() and address_key in columns[1].lower():
                card = columns[1]
                break
        if not card:
            return
        for profile in ("a2dp-sink", "a2dp-sink-sbc", "a2dp_sink"):
            changed = self._run(["pactl", "set-card-profile", card, profile])
            if changed.returncode == 0:
                return

    def _find_sink_for_address(self, address: str) -> str | None:
        sinks = self._bluez_sinks()
        if not sinks:
            return None
        address_key = address.replace(":", "_").lower()
        selected = next(
            (sink for sink in sinks if address_key in sink.lower()),
            None,
        )
        if selected:
            return selected
        # When exactly one Bluetooth sink exists it is safe to use it even on a
        # backend whose sink name does not embed the MAC address.
        return sinks[0] if len(sinks) == 1 else None

    def _set_default_sink(self, address: str) -> str | None:
        if not shutil.which("pactl"):
            return None

        # BlueZ can report Connected=yes before PipeWire has finished creating
        # the A2DP sink.  Give it a few seconds instead of declaring success too
        # early and sending TTS to the previous default output.
        selected: str | None = None
        for attempt in range(20):
            selected = self._find_sink_for_address(address)
            if selected:
                break
            if attempt == 3:
                self._activate_a2dp_profile(address)
            time.sleep(0.5)

        if not selected:
            return None

        changed = self._run(["pactl", "set-default-sink", selected])
        if changed.returncode != 0:
            return None

        # Move any already-open players to the new Bluetooth sink too.  New TTS
        # streams will automatically follow the new default sink.
        inputs = self._run(["pactl", "list", "short", "sink-inputs"])
        if inputs.returncode == 0:
            for line in inputs.stdout.splitlines():
                columns = line.split()
                if not columns:
                    continue
                stream_id = columns[0]
                if stream_id.isdigit():
                    self._run(["pactl", "move-sink-input", stream_id, selected])
        return selected

    def reconnect_now(self) -> tuple[bool, str]:
        try:
            target = self._resolve_target()
            if not target:
                self._last_connected = False
                self._last_ready = False
                return (
                    False,
                    "No paired Bluetooth audio speaker was found. Pair Alexa on the host once; "
                    "after that NekoSuneAI will detect its address automatically.",
                )

            address, name = target
            self._detected_address = address
            self._detected_name = name

            connected = self._is_connected(address)
            if not connected:
                result = self._run(["bluetoothctl", "connect", address])
                # Give BlueZ a moment to publish the Connected property.
                for _ in range(8):
                    if self._is_connected(address):
                        connected = True
                        break
                    time.sleep(0.5)
                if not connected:
                    detail = (
                        result.stderr
                        or result.stdout
                        or "BlueZ did not connect the speaker."
                    ).strip()
                    self._last_connected = False
                    self._last_ready = False
                    return False, f"{name} Bluetooth reconnect failed: {detail}"

            self._last_connected = True
            sink = self._set_default_sink(address)
            if not sink:
                self._last_ready = False
                return (
                    False,
                    f"{name} is connected over Bluetooth, but its A2DP audio sink is not ready yet. "
                    "NekoSuneAI will keep retrying automatically.",
                )

            self._detected_sink = sink
            self._last_ready = True
            return (
                True,
                f"{name} ({address}) was auto-detected and selected as the default Bluetooth output.",
            )
        except Exception as exc:
            self._last_connected = False
            self._last_ready = False
            return False, f"Alexa Bluetooth auto-detection/reconnect failed: {exc}"

    def _loop(self) -> None:
        interval = max(3.0, self.config.bluetooth_reconnect_interval_seconds)
        while not self._stop.is_set():
            was_ready = self._last_ready
            ok, message = self.reconnect_now()
            if ok and was_ready is not True:
                self.notify(message)
            elif not ok and was_ready is not False:
                self.notify(message + " The watchdog will keep trying.")
            self._stop.wait(interval)
