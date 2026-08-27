"""Keep a pre-paired Bluetooth speaker connected on Linux/BlueZ hosts."""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from typing import Callable

from .config import Config


class BluetoothSpeakerWatchdog:
    def __init__(self, config: Config, notify: Callable[[str], None]) -> None:
        self.config = config
        self.notify = notify
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_connected: bool | None = None

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)

    def start(self) -> None:
        if not self.config.bluetooth_reconnect_enabled or not self.config.bluetooth_speaker_address:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="bluetooth-speaker-watchdog")
        self._thread.start()

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.config.bluetooth_reconnect_enabled,
            "address": self.config.bluetooth_speaker_address or "",
            "connected": self._last_connected,
            "running": bool(self._thread and self._thread.is_alive()),
        }

    def _is_connected(self, address: str) -> bool:
        if not shutil.which("bluetoothctl"):
            raise RuntimeError("bluetoothctl is unavailable. Install BlueZ or use the Docker image.")
        result = self._run(["bluetoothctl", "info", address])
        return result.returncode == 0 and bool(re.search(r"^\s*Connected:\s*yes\s*$", result.stdout, re.I | re.M))

    def _set_default_sink(self, address: str) -> None:
        if not shutil.which("pactl"):
            return
        result = self._run(["pactl", "list", "short", "sinks"])
        address_key = address.replace(":", "_").lower()
        sinks = []
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) >= 2 and "bluez" in columns[1].lower():
                sinks.append(columns[1])
        selected = next((sink for sink in sinks if address_key in sink.lower()), sinks[0] if len(sinks) == 1 else None)
        if selected:
            self._run(["pactl", "set-default-sink", selected])

    def reconnect_now(self) -> tuple[bool, str]:
        address = (self.config.bluetooth_speaker_address or "").strip()
        if not address:
            return False, "Set the Alexa Bluetooth address first."
        if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", address):
            return False, "Alexa Bluetooth address must look like AA:BB:CC:DD:EE:FF."
        try:
            if not self._is_connected(address):
                result = self._run(["bluetoothctl", "connect", address])
                connected = self._is_connected(address)
                if not connected:
                    detail = (result.stderr or result.stdout or "BlueZ did not connect the speaker.").strip()
                    self._last_connected = False
                    return False, f"Alexa reconnect failed: {detail}"
            self._set_default_sink(address)
            self._last_connected = True
            return True, "Alexa Bluetooth speaker is connected and selected as the default output."
        except Exception as exc:
            self._last_connected = False
            return False, f"Alexa reconnect failed: {exc}"

    def _loop(self) -> None:
        interval = max(3.0, self.config.bluetooth_reconnect_interval_seconds)
        while not self._stop.is_set():
            was_connected = self._last_connected
            ok, message = self.reconnect_now()
            if ok and was_connected is False:
                self.notify(message)
            elif not ok and was_connected is not False:
                self.notify(message + " The watchdog will keep trying.")
            self._stop.wait(interval)
