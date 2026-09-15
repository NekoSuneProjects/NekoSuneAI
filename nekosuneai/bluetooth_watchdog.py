"""Auto-detect and keep a pre-paired Bluetooth speaker connected on Linux.

The host owns BlueZ and PipeWire/PulseAudio. In Docker we talk to those host
services through the mounted system D-Bus and audio-session sockets; the
container does not pair devices itself. A speaker only needs to be paired (and
ideally trusted) on the host once. After that NekoSuneAI can discover it,
reconnect it and make its BlueZ sink the default output automatically.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

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
# A `pactl list cards` profile line, e.g.
#   a2dp-sink-aac: High Fidelity Playback (A2DP Sink, AAC) (sinks: 1, sources: 0, priority: 516, available: yes)
_PROFILE_RE = re.compile(
    r"^\s{2,}([A-Za-z0-9_+-]+):\s+.*?priority:\s*(\d+).*?available:\s*(\w+)\s*\)?\s*$",
    re.M,
)


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
        # Why A2DP could not be selected, surfaced on the status page: the
        # old code failed silently and only ever said "sink is not ready yet".
        self._detected_profile_error = ""
        # Result of the one-off startup probe, so a dead audio session is
        # visible immediately rather than only once a speaker fails to arrive.
        self.audio_server_ok: bool | None = None
        self.audio_server_message = ""
        # Which device has already had a role renegotiation attempted, so a
        # speaker the owner is listening through is never dropped repeatedly.
        self._role_retry_address = ""

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
        # Address is deliberately optional. When it is blank (or still contains
        # the example AA:BB:... value) the watchdog discovers a paired audio
        # device automatically, preferring Amazon Alexa/Echo names.
        if not self.config.bluetooth_reconnect_enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self.audio_server_ok, self.audio_server_message = self.audio_server_probe()
        if not self.audio_server_ok:
            self.notify(self.audio_server_message)
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
            "profile_error": self._detected_profile_error,
            "audio_server_ok": self.audio_server_ok,
            "audio_server": self.audio_server_message,
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
        return bool(
            re.search(
                r"^\s*Icon:\s*audio-(?:card|headset)\s*$",
                info,
                re.I | re.M,
            )
        )

    @staticmethod
    def _is_paired_or_trusted_info(info: str) -> bool:
        # BlueZ versions differ in whether they expose Paired, Bonded, or both.
        # Trust is also sufficient evidence that this is a host-known device.
        return any(
            BluetoothSpeakerWatchdog._info_flag(info, key)
            for key in ("Paired", "Bonded", "Trusted")
        )

    def _ensure_adapter_powered(self) -> None:
        """Best-effort power-on of the host Bluetooth adapter through BlueZ."""
        if shutil.which("bluetoothctl"):
            self._run(["bluetoothctl", "power", "on"])

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
        trusted/paired audio devices. Keyboards, controllers and other
        Bluetooth devices are ignored because they do not expose an audio-sink
        UUID/icon.
        """
        if not shutil.which("bluetoothctl"):
            return None
        self._ensure_adapter_powered()
        result = self._run(["bluetoothctl", "devices"])
        if result.returncode != 0:
            return None

        candidates: list[tuple[tuple[int, int, int, int, str], str, str]] = []
        for address, listed_name in _DEVICE_LINE_RE.findall(result.stdout):
            info = self._device_info(address)
            if (
                not info
                or not self._is_audio_device_info(info)
                or not self._is_paired_or_trusted_info(info)
            ):
                continue
            name = (
                self._info_value(info, "Alias")
                or self._info_value(info, "Name")
                or listed_name.strip()
                or address
            )
            lowered_name = name.lower()
            preferred = (
                0
                if any(x in lowered_name for x in _PREFERRED_SPEAKER_NAMES)
                else 1
            )
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
            # Only pin to a configured MAC when BlueZ knows it, it is an audio
            # device, and it is already paired/bonded/trusted on the host. This
            # intentionally ignores the AA:BB:CC:DD:EE:FF example placeholder.
            if (
                info
                and self._is_audio_device_info(info)
                and self._is_paired_or_trusted_info(info)
            ):
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

    def _bluez_card(self, address: str) -> dict[str, Any] | None:
        """This speaker's BlueZ card, with the profiles it actually offers.

        Guessing profile names blind does not work. A speaker's card exposes a
        codec-specific set -- an Echo Dot may offer `a2dp-sink-sbc_xq` or
        `a2dp-sink-aac` and no plain `a2dp-sink` at all -- and a name that is
        not on the card's own list is simply rejected, so nothing switches to
        A2DP, no sink is ever created, and the watchdog reports "connected,
        but its A2DP audio sink is not ready yet" forever. Read the real list
        instead.
        """
        if not shutil.which("pactl"):
            self._detected_profile_error = (
                "pactl is not on PATH, so this node cannot talk to the audio "
                "server at all (apt install pulseaudio-utils)."
            )
            return None
        result = self._run(["pactl", "list", "cards"])
        if result.returncode != 0:
            self._detected_profile_error = self._diagnose_unreachable_server(result)
            return None
        address_key = address.replace(":", "_").lower()
        for block in re.split(r"\n(?=Card #)", result.stdout):
            name = self._info_value(block, "Name")
            if "bluez" not in name.lower() or address_key not in name.lower():
                continue
            profiles: list[tuple[int, str]] = []
            for profile, priority, available in _PROFILE_RE.findall(block):
                if available.strip().lower() == "no":
                    continue
                profiles.append((int(priority), profile))
            return {
                "card": name,
                "active": self._info_value(block, "Active Profile"),
                # Highest priority first: the audio server's own ranking of
                # its codecs is a better answer than any list hardcoded here.
                "profiles": [item[1] for item in sorted(profiles, reverse=True)],
            }
        # The server answered but has no card for this speaker. Which of the
        # several reasons that can be matters a great deal to the owner, and
        # they are distinguishable from what it did return.
        self._detected_profile_error = self._diagnose_missing_card(address, result.stdout)
        return None

    def _diagnose_unreachable_server(self, result: subprocess.CompletedProcess[str]) -> str:
        """`pactl` ran but could not talk to an audio server.

        "Connection refused" reads as "the server is down", which sends the
        owner to the host to check a session that is usually running fine. The
        far more common cause in a container is that the socket PULSE_SERVER
        names is not *present* -- an empty directory Docker created because the
        bind-mount source did not exist when the container was made. Look at
        the path before blaming the server.
        """
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        reason = detail[-1] if detail else f"pactl exited {result.returncode}"
        target = os.environ.get("PULSE_SERVER", "")
        socket_path = target.split("unix:", 1)[-1].split(",")[0] if target.startswith("unix:") else ""
        where = f" (PULSE_SERVER={target})" if target else ""

        if socket_path:
            path = Path(socket_path)
            if not path.exists():
                listing = ""
                if path.parent.is_dir():
                    entries = sorted(item.name for item in path.parent.iterdir())
                    listing = (
                        f" {path.parent} contains: {', '.join(entries[:6])}."
                        if entries
                        else f" {path.parent} is empty -- Docker creates an empty "
                        "directory when a bind-mount source is missing at container "
                        "creation, so the mount is pointing at the wrong path or the "
                        "container predates the socket. If the host has no session "
                        "either, `sudo loginctl enable-linger <user>` keeps one alive "
                        "on a headless Pi."
                    )
                else:
                    listing = f" {path.parent} does not exist in this container."
                return (
                    f"The audio socket {socket_path} does not exist here{where}.{listing} "
                    "Check the pulse mount in compose.pi-proxy.yml against the host's real "
                    "path (`ls -la /run/user/*/pulse/`), then recreate the container with "
                    "`docker compose up -d --force-recreate`. scripts/detect-pulse-audio.sh "
                    "writes the correct PULSE_RUNTIME_DIR/PULSE_COOKIE_FILE into .env."
                )
            if not path.is_socket():
                return (
                    f"{socket_path} exists but is not a socket{where} -- the bind mount is "
                    "pointing at the wrong thing. Compare it with the host's "
                    "`ls -la /run/user/*/pulse/` and recreate the container."
                )

        return (
            f"Cannot reach the audio server{where}: {reason}. The socket exists, so the "
            "server is refusing the connection: check PULSE_COOKIE is mounted from the "
            "same user that owns the session, and that the host's pipewire-pulse (or "
            "pulseaudio) is still running for that user."
        )

    def audio_server_probe(self) -> tuple[bool, str]:
        """Is an audio server reachable at all? Checked once at startup.

        Without this the first sign of a dead audio session is a Bluetooth
        speaker that never becomes ready -- which reads as a Bluetooth problem
        and sends the owner to the wrong place. Local WAV playback (`paplay`)
        goes through the same server, so this failing predicts silent TTS and
        chimes too, not just Bluetooth.
        """
        if not shutil.which("pactl"):
            return False, "pactl is not installed (apt install pulseaudio-utils)."
        result = self._run(["pactl", "info"])
        if result.returncode != 0:
            return False, self._diagnose_unreachable_server(result)
        server = self._info_value(result.stdout, "Server Name") or "audio server"
        sink = self._info_value(result.stdout, "Default Sink")
        return True, f"{server} reachable (default sink: {sink or 'none'})."

    def _diagnose_missing_card(self, address: str, listing: str) -> str:
        """Say why this speaker has no card, given what the server did report."""
        cards = [
            self._info_value(block, "Name")
            for block in re.split(r"\n(?=Card #)", listing)
            if self._info_value(block, "Name")
        ]
        if not cards:
            return (
                "The audio server reports no sound cards at all. It is reachable "
                "but has no devices -- check it is the same server session that "
                "owns the Pi's audio hardware."
            )
        bluez = [name for name in cards if "bluez" in name.lower()]
        if not bluez:
            # The common one, and invisible from BlueZ's side: bluetoothctl
            # happily connects an A2DP speaker while the audio server has no
            # Bluetooth support compiled in or installed, so no card is ever
            # created and nothing explains why.
            return (
                f"The audio server has {len(cards)} card(s) but none from Bluetooth "
                f"({', '.join(cards[:4])}). Its Bluetooth module is missing: install "
                "libspa-0.2-bluetooth (PipeWire) or pulseaudio-module-bluetooth "
                "(PulseAudio) on the host and restart the audio server. BlueZ will "
                "keep reporting the speaker as connected regardless."
            )
        return (
            f"The audio server has Bluetooth cards ({', '.join(bluez[:3])}) but none "
            f"for {address}. The speaker may be connected to a different host, or "
            "connected without its audio profile."
        )

    def _handle_no_a2dp_profile(self, address: str, card: dict[str, Any]) -> None:
        """The card exists but carries no A2DP sink profile.

        The interesting case is a card whose only profiles are telephony ones
        (`audio-gateway`, `headset-*`): the speaker has connected in the wrong
        direction, as the audio *source*, treating this Pi as its output device
        rather than the other way round. Amazon Echo devices do this readily,
        since they support both roles -- and the result is a card that can
        never produce a playback sink no matter how long the watchdog waits.

        When BlueZ says the device does advertise an A2DP Audio Sink, the roles
        were simply negotiated badly and a disconnect/reconnect initiated from
        this side usually settles them correctly. Tried once per device, not in
        a loop: repeatedly dropping a speaker the owner is listening through
        would be worse than the fault.
        """
        profiles = ", ".join(card["profiles"][:6]) or "none"
        telephony_only = all(
            name.lower().startswith(("audio-gateway", "headset-", "off"))
            for name in card["profiles"]
        )
        advertises_sink = self._is_audio_device_info(self._device_info(address))

        if telephony_only and advertises_sink and self._role_retry_address != address:
            self._role_retry_address = address
            self.notify(
                f"{self._detected_name or address} connected as an audio gateway "
                "(it is trying to play *to* this Pi). Reconnecting to renegotiate."
            )
            self._run(["bluetoothctl", "disconnect", address])
            time.sleep(2.0)
            self._run(["bluetoothctl", "connect", address])
            self._detected_profile_error = (
                f"{card['card']} connected in the wrong role (active: "
                f"{card['active'] or 'unknown'}); reconnecting to renegotiate A2DP."
            )
            return

        if telephony_only:
            self._detected_profile_error = (
                f"{card['card']} is in a telephony role, not a music one (active: "
                f"{card['active'] or 'unknown'}; available: {profiles}). The speaker "
                "has connected as the audio source, treating this Pi as its output. "
                "On an Echo: remove this Pi from the Alexa app's Bluetooth devices, "
                "say \"Alexa, pair Bluetooth\" so it becomes discoverable as a "
                "speaker, then connect to it from the Pi with `bluetoothctl connect "
                f"{address}`."
            )
            return

        self._detected_profile_error = (
            f"{card['card']} offers no A2DP sink profile "
            f"(active: {card['active'] or 'unknown'}). Available: {profiles}."
        )

    def _activate_a2dp_profile(self, address: str) -> bool:
        """Switch this speaker's card to the best A2DP sink profile it has."""
        card = self._bluez_card(address)
        if not card:
            return False
        a2dp = [name for name in card["profiles"] if name.lower().startswith("a2dp-sink")]
        if not a2dp:
            self._handle_no_a2dp_profile(address, card)
            return False
        if card["active"] in a2dp:
            return True
        for profile in a2dp:
            if self._run(["pactl", "set-card-profile", card["card"], profile]).returncode == 0:
                self._detected_profile_error = ""
                self.notify(f"Switched {card['card']} to {profile}.")
                return True
        self._detected_profile_error = (
            f"{card['card']} rejected every A2DP profile it advertises "
            f"({', '.join(a2dp[:4])})."
        )
        return False

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

    def _current_default_sink(self) -> str:
        if not shutil.which("pactl"):
            return ""
        result = self._run(["pactl", "get-default-sink"])
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _set_default_sink(self, address: str) -> str | None:
        if not shutil.which("pactl"):
            return None

        # BlueZ can report Connected=yes before PipeWire has finished creating
        # the A2DP sink. Give it a few seconds instead of declaring success too
        # early and sending TTS to the previous default output.
        #
        # The profile switch is retried rather than attempted once: the card
        # frequently does not exist yet on the first look (BlueZ has connected,
        # the audio server has not caught up), and a single early attempt that
        # found no card left the speaker parked on HFP/off with no sink for as
        # long as it stayed connected.
        selected: str | None = None
        for attempt in range(20):
            selected = self._find_sink_for_address(address)
            if selected:
                break
            if attempt in (2, 6, 12):
                self._activate_a2dp_profile(address)
            time.sleep(0.5)

        if not selected:
            # Say what actually went wrong. "The A2DP sink is not ready yet"
            # on its own is unactionable when the real cause is a card sitting
            # on a headset profile, or offering no A2DP profile at all.
            if not self._detected_profile_error:
                # _bluez_card records a specific diagnosis when it cannot find
                # the card, so only the "card exists, sink did not appear"
                # case is left to describe here.
                card = self._bluez_card(address)
                if card is not None:
                    self._detected_profile_error = (
                        f"{card['card']} is on profile '{card['active'] or 'unknown'}' "
                        "and no sink appeared."
                    )
            return None
        self._detected_profile_error = ""

        # Nothing to do when this sink is already the default. The watchdog
        # re-ran this every poll interval, and the stream-moving below with
        # it, which meant an active music stream was torn off its sink and
        # reattached every few seconds -- audible as periodic dropouts, and a
        # steady CPU cost on a Pi for no change.
        if self._current_default_sink() == selected:
            return selected

        changed = self._run(["pactl", "set-default-sink", selected])
        if changed.returncode != 0:
            return None

        # Move any already-open players to the new Bluetooth sink too. New TTS
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
            self._ensure_adapter_powered()
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
                detail = self._detected_profile_error or "The audio server has not created its sink."
                return (
                    False,
                    f"{name} is connected over Bluetooth, but its A2DP audio sink is not ready. "
                    f"{detail} NekoSuneAI will keep retrying automatically.",
                )

            self._detected_sink = sink
            self._last_ready = True
            self._role_retry_address = ""

            return (
                True,
                f"{name} ({address}) was auto-detected and selected as the default Bluetooth output.",
            )
        except Exception as exc:
            self._last_connected = False
            self._last_ready = False
            return False, f"Alexa Bluetooth auto-detection/reconnect failed: {exc}"

    def _still_healthy(self) -> bool:
        """Cheap "nothing has changed" check for an already-working link.

        Two short subprocess calls, against the full reconnect path's
        enumerate-every-paired-device plus a sink wait that can block for ten
        seconds. Only worth running when the speaker was ready last time.
        """
        if not (self._last_ready and self._detected_address and self._detected_sink):
            return False
        try:
            if not self._is_connected(self._detected_address):
                return False
        except RuntimeError:
            return False
        return self._current_default_sink() == self._detected_sink

    def _loop(self) -> None:
        interval = max(3.0, self.config.bluetooth_reconnect_interval_seconds)
        while not self._stop.is_set():
            was_ready = self._last_ready
            if self._still_healthy():
                self._stop.wait(interval)
                continue
            ok, message = self.reconnect_now()
            if ok and was_ready is not True:
                self.notify(message)
            elif not ok and was_ready is not False:
                self.notify(message + " The watchdog will keep trying.")
            self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()
