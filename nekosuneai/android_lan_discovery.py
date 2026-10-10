"""Allowlisted Android game-agent discovery for the PiProxy node."""
from __future__ import annotations

import ipaddress
import socket
import time
import json
import urllib.request
import urllib.error


class AndroidLanDiscovery:
    def __init__(self, config):
        self.enabled = bool(config.get("game_lan_enabled", False))
        self.targets = {}
        self._cache = {}
        self.cache_seconds = max(1, min(60, int(config.get('game_lan_probe_cache_seconds', 10))))
        for item in config.get("game_lan_devices", []):
            ident = str(item.get("id", "")).strip()
            if not ident or not ident.replace("-", "").replace("_", "").isalnum():
                raise ValueError("Invalid Android LAN device identifier")
            if ident in self.targets:
                raise ValueError("Duplicate Android LAN device")
            ip = ipaddress.ip_address(str(item.get("ip", "")))
            if not (ip.is_private or ip.is_loopback):
                raise ValueError("Android LAN device must have a private IP")
            port = int(item.get("port", 0))
            if port < 1 or port > 65535:
                raise ValueError("Invalid Android LAN port")
            self.targets[ident] = (str(ip), port, str(item.get('token', '')))

    def inventory(self):
        if not self.enabled:
            return []
        return [{"id": device_id, "platform": "android", "configured": True}
                for device_id in self.targets]

    def status(self, device_id):
        if not self.enabled:
            raise PermissionError("LAN gaming is disabled")
        if device_id not in self.targets:
            raise PermissionError("Unknown or disallowed game device")
        address, port, token = self.targets[device_id]
        now = time.monotonic()
        cached = self._cache.get(device_id)
        if cached and now - cached[0] < self.cache_seconds:
            return dict(cached[1])
        started = now
        try:
            if len(token) < 32:
                raise ValueError('Missing configured LAN authentication token')
            host = '[' + address + ']' if ':' in address else address
            request = urllib.request.Request(
                f'http://{host}:{port}/v1/lan-game/status',
                headers={'X-Neko-LAN-Bridge-Token': token}, method='GET')
            with urllib.request.urlopen(request, timeout=1.5) as response:
                if response.status != 200:
                    raise ValueError('Worker did not accept status request')
                payload = response.read(4096)
            status = json.loads(payload)
            result = {'id': device_id, 'reachable': status.get('online') is True,
                      'node_id': status.get('node_id'),
                      'foreground_package': status.get('foreground_package'),
                      'game_running': status.get('game_running') is True,
                      'latency_ms': round((time.monotonic() - started) * 1000)}
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            result = {'id': device_id, 'reachable': False}
        self._cache[device_id] = (time.monotonic(), result)
        return dict(result)

    def statuses(self):
        return [self.status(device_id) for device_id in self.targets] if self.enabled else []
