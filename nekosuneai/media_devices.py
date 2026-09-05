from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin
from xml.sax.saxutils import escape

import requests


class MediaTargetError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _clamp_volume(value: int) -> int:
    return max(0, min(100, int(value)))


def normalize_media_target(value: str | None) -> str:
    v = str(value or "").strip().lower().replace("_", " ")
    aliases = {
        "": "local",
        "speaker": "local",
        "local speaker": "local",
        "cast": "chromecast",
        "google cast": "chromecast",
        "googlecast": "chromecast",
        "upnp": "dlna",
        "upnp renderer": "dlna",
        "androidtv": "android-tv",
        "android tv": "android-tv",
        "adb": "android-tv",
        "lg": "lg-webos",
        "lg tv": "lg-webos",
        "webos": "lg-webos",
        "webos tv": "lg-webos",
        "samsung": "samsung-tv",
        "samsung tv": "samsung-tv",
    }
    return aliases.get(v, v.replace(" ", "-"))


def default_media_target() -> str:
    return normalize_media_target(_env("MEDIA_TARGET", "local"))


class BaseMediaTarget:
    name = "unknown"

    def play_url(self, url: str, *, title: str = "", content_type: str = "audio/mpeg") -> str:
        raise MediaTargetError(f"{self.name} does not support starting a URL.")

    def control(self, action: str, value: float | int | None = None) -> str:
        raise MediaTargetError(f"{self.name} does not support {action}.")


class ChromecastTarget(BaseMediaTarget):
    name = "Chromecast"

    def _cast(self):
        try:
            import pychromecast  # type: ignore
        except ImportError as exc:
            raise MediaTargetError("Chromecast support requires the pychromecast package.") from exc

        host = _env("CAST_HOST")
        friendly = _env("CAST_DEVICE")
        browser = None
        try:
            if friendly:
                chromecasts, browser = pychromecast.get_listed_chromecasts(
                    friendly_names=[friendly],
                    known_hosts=[host] if host else None,
                    discovery_timeout=5,
                )
            elif host:
                # pychromecast 13.x expects CastInfo in Chromecast(), not a raw
                # IP string. Discover through a known host so this stays valid
                # on the Python 3.10-compatible release used by NekoSuneAI.
                chromecasts, browser = pychromecast.get_chromecasts(known_hosts=[host])
                chromecasts = [
                    cast for cast in chromecasts
                    if str(getattr(getattr(cast, "cast_info", None), "host", "")) == host
                    or str(getattr(getattr(cast, "socket_client", None), "host", "")) == host
                ] or chromecasts
            else:
                raise MediaTargetError("Set CAST_DEVICE or CAST_HOST for Chromecast control.")

            if not chromecasts:
                label = friendly or host
                raise MediaTargetError(f"Chromecast '{label}' was not found on the LAN.")
            cast = chromecasts[0]
            cast.wait(timeout=10)
            return cast
        finally:
            if browser is not None:
                try:
                    browser.stop_discovery()
                except Exception:
                    pass

    def play_url(self, url: str, *, title: str = "", content_type: str = "audio/mpeg") -> str:
        cast = self._cast()
        mc = cast.media_controller
        mc.play_media(url, content_type, title=title or None)
        mc.block_until_active(timeout=10)
        return f"Casting {title or 'media'} to {cast.name}."

    def control(self, action: str, value: float | int | None = None) -> str:
        cast = self._cast()
        mc = cast.media_controller
        if action == "play":
            mc.play()
        elif action == "pause":
            mc.pause()
        elif action == "stop":
            mc.stop()
        elif action == "next":
            mc.queue_next()
        elif action == "previous":
            mc.queue_prev()
        elif action == "seek":
            mc.seek(float(value or 0))
        elif action == "volume":
            cast.set_volume(_clamp_volume(int(value or 0)) / 100.0)
        else:
            raise MediaTargetError(f"Unsupported Chromecast action: {action}")
        return f"Chromecast {action} command sent."


@dataclass
class DlnaServices:
    avtransport: str
    rendering: str = ""


def _ssdp_discover(timeout: float = 2.0) -> list[str]:
    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST:239.255.255.250:1900\r\n"
        'MAN:"ssdp:discover"\r\n'
        "MX:1\r\n"
        "ST:urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
    ).encode("ascii")
    locations: list[str] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    try:
        sock.sendto(message, ("239.255.255.250", 1900))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                break
            for line in data.decode("utf-8", "ignore").splitlines():
                if line.lower().startswith("location:"):
                    location = line.split(":", 1)[1].strip()
                    if location and location not in locations:
                        locations.append(location)
    finally:
        sock.close()
    return locations


def _dlna_services_from_description(location: str) -> DlnaServices | None:
    response = requests.get(location, timeout=5)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    base = location
    for element in root.iter():
        if element.tag.endswith("URLBase") and element.text:
            base = element.text.strip()
            break
    av = ""
    rendering = ""
    for service in root.iter():
        if not service.tag.endswith("service"):
            continue
        values = {
            child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
            for child in service
        }
        stype = values.get("serviceType", "")
        control = values.get("controlURL", "")
        if "AVTransport" in stype:
            av = urljoin(base, control)
        elif "RenderingControl" in stype:
            rendering = urljoin(base, control)
    return DlnaServices(avtransport=av, rendering=rendering) if av else None


def _soap(url: str, service: str, action: str, fields: dict[str, Any]) -> requests.Response:
    body_fields = "".join(
        f"<{key}>{escape(str(value))}</{key}>" for key, value in fields.items()
    )
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:1">'
        f"{body_fields}</u:{action}></s:Body></s:Envelope>"
    )
    response = requests.post(
        url,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"urn:schemas-upnp-org:service:{service}:1#{action}"',
        },
        timeout=6,
    )
    response.raise_for_status()
    return response


class DlnaTarget(BaseMediaTarget):
    name = "DLNA/UPnP"

    def _services(self) -> DlnaServices:
        av = _env("DLNA_AVTRANSPORT_URL")
        rendering = _env("DLNA_RENDERING_URL")
        if av:
            return DlnaServices(avtransport=av, rendering=rendering)
        description = _env("DLNA_DEVICE_URL")
        candidates = [description] if description else _ssdp_discover()
        for location in candidates:
            try:
                services = _dlna_services_from_description(location)
                if services:
                    return services
            except Exception:
                continue
        raise MediaTargetError(
            "No DLNA MediaRenderer found. Set DLNA_DEVICE_URL or DLNA_AVTRANSPORT_URL."
        )

    def play_url(self, url: str, *, title: str = "", content_type: str = "audio/mpeg") -> str:
        services = self._services()
        _soap(
            services.avtransport,
            "AVTransport",
            "SetAVTransportURI",
            {"InstanceID": 0, "CurrentURI": url, "CurrentURIMetaData": ""},
        )
        _soap(
            services.avtransport,
            "AVTransport",
            "Play",
            {"InstanceID": 0, "Speed": 1},
        )
        return f"Playing {title or 'media'} on the DLNA renderer."

    def control(self, action: str, value: float | int | None = None) -> str:
        services = self._services()
        if action in {"play", "pause", "stop", "next", "previous"}:
            names = {
                "play": "Play",
                "pause": "Pause",
                "stop": "Stop",
                "next": "Next",
                "previous": "Previous",
            }
            fields: dict[str, Any] = {"InstanceID": 0}
            if action == "play":
                fields["Speed"] = 1
            _soap(services.avtransport, "AVTransport", names[action], fields)
        elif action == "seek":
            seconds = max(0, int(float(value or 0)))
            target = f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
            _soap(
                services.avtransport,
                "AVTransport",
                "Seek",
                {"InstanceID": 0, "Unit": "REL_TIME", "Target": target},
            )
        elif action == "volume":
            if not services.rendering:
                raise MediaTargetError(
                    "This DLNA renderer did not publish RenderingControl."
                )
            _soap(
                services.rendering,
                "RenderingControl",
                "SetVolume",
                {
                    "InstanceID": 0,
                    "Channel": "Master",
                    "DesiredVolume": _clamp_volume(int(value or 0)),
                },
            )
        else:
            raise MediaTargetError(f"Unsupported DLNA action: {action}")
        return f"DLNA {action} command sent."


class AndroidTvTarget(BaseMediaTarget):
    name = "Android TV/ADB"

    KEYCODES = {
        "play": "126",
        "pause": "127",
        "stop": "86",
        "next": "87",
        "previous": "88",
        "toggle": "85",
    }

    def _adb(self, *args: str) -> str:
        adb = _env("ADB_PATH") or shutil.which("adb")
        host = _env("ANDROID_TV_HOST")
        if not adb:
            raise MediaTargetError("adb is not installed or ADB_PATH is not configured.")
        if not host:
            raise MediaTargetError(
                "Set ANDROID_TV_HOST to the TV's LAN address, optionally with :5555."
            )
        target = host if ":" in host else host + ":5555"
        subprocess.run(
            [adb, "connect", target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
        completed = subprocess.run(
            [adb, "-s", target, *args],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if completed.returncode != 0:
            raise MediaTargetError(
                (completed.stderr or completed.stdout or "ADB command failed").strip()
            )
        return completed.stdout.strip()

    def control(self, action: str, value: float | int | None = None) -> str:
        if action in self.KEYCODES:
            self._adb("shell", "input", "keyevent", self.KEYCODES[action])
        elif action == "seek":
            millis = max(0, int(float(value or 0) * 1000))
            self._adb(
                "shell", "cmd", "media_session", "dispatch", "seekto", str(millis)
            )
        elif action == "volume":
            percent = _clamp_volume(int(value or 0))
            try:
                self._adb(
                    "shell",
                    "media",
                    "volume",
                    "--stream",
                    "3",
                    "--set",
                    str(round(percent * 15 / 100)),
                )
            except MediaTargetError:
                self._adb("shell", "input", "keyevent", "24" if percent >= 50 else "25")
        else:
            raise MediaTargetError(f"Unsupported Android TV action: {action}")
        return f"Android TV {action} command sent."


class LgWebOsTarget(BaseMediaTarget):
    name = "LG webOS"

    def _request(self, uri: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            import websocket  # type: ignore
        except ImportError as exc:
            raise MediaTargetError("LG webOS support requires websocket-client.") from exc
        host = _env("LG_WEBOS_HOST")
        key = _env("LG_WEBOS_CLIENT_KEY")
        if not host:
            raise MediaTargetError("Set LG_WEBOS_HOST to your TV's LAN address.")
        ws = websocket.create_connection(f"ws://{host}:3000/", timeout=5)
        try:
            register: dict[str, Any] = {
                "type": "register",
                "id": "register_0",
                "payload": {
                    "pairingType": "PROMPT",
                    "manifest": {
                        "manifestVersion": 1,
                        "appVersion": "1.0",
                        "signed": {
                            "created": "20260905",
                            "appId": "com.nekosuneai.remote",
                            "vendorId": "NekoSuneProjects",
                            "localizedAppNames": {"": "NekoSuneAI"},
                            "localizedVendorNames": {"": "NekoSuneProjects"},
                            "permissions": [
                                "CONTROL_AUDIO",
                                "CONTROL_INPUT_MEDIA_PLAYBACK",
                                "CONTROL_POWER",
                            ],
                        },
                        "permissions": [
                            "CONTROL_AUDIO",
                            "CONTROL_INPUT_MEDIA_PLAYBACK",
                            "CONTROL_POWER",
                        ],
                    },
                },
            }
            if key:
                register["payload"]["client-key"] = key
            ws.send(json.dumps(register))
            registered = json.loads(ws.recv())
            if registered.get("type") == "error":
                raise MediaTargetError(str(registered.get("error") or "webOS pairing failed"))
            new_key = str((registered.get("payload") or {}).get("client-key") or "")
            if new_key and not key:
                print(
                    "[media] LG webOS paired. Set "
                    f"LG_WEBOS_CLIENT_KEY={new_key} to avoid re-pairing."
                )
            request_id = "neko_" + uuid.uuid4().hex[:10]
            ws.send(
                json.dumps(
                    {
                        "type": "request",
                        "id": request_id,
                        "uri": uri,
                        "payload": payload or {},
                    }
                )
            )
            for _ in range(4):
                result = json.loads(ws.recv())
                if result.get("id") == request_id:
                    if result.get("type") == "error":
                        raise MediaTargetError(
                            str(result.get("error") or "webOS request failed")
                        )
                    return result.get("payload") or {}
            return {}
        finally:
            ws.close()

    def control(self, action: str, value: float | int | None = None) -> str:
        uris = {
            "play": "ssap://media.controls/play",
            "pause": "ssap://media.controls/pause",
            "stop": "ssap://media.controls/stop",
            "next": "ssap://media.controls/fastForward",
            "previous": "ssap://media.controls/rewind",
        }
        if action in uris:
            self._request(uris[action])
        elif action == "volume":
            self._request(
                "ssap://audio/setVolume",
                {"volume": _clamp_volume(int(value or 0))},
            )
        elif action == "seek":
            raise MediaTargetError(
                "LG webOS does not expose a reliable absolute seek command through "
                "the generic SSAP media controls; use next/previous/fast-forward/rewind "
                "where the active app supports them."
            )
        else:
            raise MediaTargetError(f"Unsupported LG webOS action: {action}")
        return f"LG webOS {action} command sent."


class SamsungTvTarget(BaseMediaTarget):
    name = "Samsung TV"

    KEYS = {
        "play": "KEY_PLAY",
        "pause": "KEY_PAUSE",
        "stop": "KEY_STOP",
        "next": "KEY_FF",
        "previous": "KEY_REWIND",
    }

    def _send_key(self, key: str, repeats: int = 1) -> None:
        try:
            import websocket  # type: ignore
        except ImportError as exc:
            raise MediaTargetError("Samsung TV support requires websocket-client.") from exc
        host = _env("SAMSUNG_TV_HOST")
        if not host:
            raise MediaTargetError("Set SAMSUNG_TV_HOST to your TV's LAN address.")
        token = _env("SAMSUNG_TV_TOKEN")
        name = base64.b64encode(
            _env("SAMSUNG_TV_NAME", "NekoSuneAI").encode("utf-8")
        ).decode("ascii")
        use_ssl = _env("SAMSUNG_TV_SSL", "1").lower() not in {
            "0", "false", "no", "off"
        }
        scheme = "wss" if use_ssl else "ws"
        port = 8002 if use_ssl else 8001
        url = (
            f"{scheme}://{host}:{port}/api/v2/channels/samsung.remote.control"
            f"?name={name}" + (f"&token={token}" if token else "")
        )
        kwargs: dict[str, Any] = {"timeout": 5}
        if use_ssl:
            kwargs["sslopt"] = {"cert_reqs": 0}
        ws = websocket.create_connection(url, **kwargs)
        try:
            for _ in range(max(1, repeats)):
                ws.send(
                    json.dumps(
                        {
                            "method": "ms.remote.control",
                            "params": {
                                "Cmd": "Click",
                                "DataOfCmd": key,
                                "Option": "false",
                                "TypeOfRemote": "SendRemoteKey",
                            },
                        }
                    )
                )
                time.sleep(0.08)
        finally:
            ws.close()

    def control(self, action: str, value: float | int | None = None) -> str:
        if action in self.KEYS:
            self._send_key(self.KEYS[action])
        elif action == "volume":
            target = _clamp_volume(int(value or 0))
            self._send_key("KEY_VOLUP" if target >= 50 else "KEY_VOLDOWN", repeats=2)
        elif action == "seek":
            self._send_key("KEY_FF" if float(value or 0) >= 0 else "KEY_REWIND")
        else:
            raise MediaTargetError(f"Unsupported Samsung TV action: {action}")
        return f"Samsung TV {action} command sent."


def get_media_target(name: str | None = None) -> BaseMediaTarget:
    target = normalize_media_target(name or default_media_target())
    if target == "chromecast":
        return ChromecastTarget()
    if target == "dlna":
        return DlnaTarget()
    if target == "android-tv":
        return AndroidTvTarget()
    if target == "lg-webos":
        return LgWebOsTarget()
    if target == "samsung-tv":
        return SamsungTvTarget()
    raise MediaTargetError(f"Unknown remote media target: {target}")


def control_remote_media(
    action: str,
    *,
    target: str | None = None,
    value: float | int | None = None,
) -> str:
    return get_media_target(target).control(action, value)


def play_remote_media(
    url: str,
    *,
    target: str | None = None,
    title: str = "",
    content_type: str = "audio/mpeg",
) -> str:
    return get_media_target(target).play_url(
        url,
        title=title,
        content_type=content_type,
    )
