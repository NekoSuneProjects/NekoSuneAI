from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PendingPairing:
    request_id: str
    device_id: str
    name: str
    remote_ip: str
    created_epoch: float
    device_type: str = "android"
    status: str = "pending"
    issued_token: str = ""


class DevicePairingManager:
    """Local-network pairing for Android companion devices.

    Pairing requests are intentionally unauthenticated so a new phone does not
    need the dashboard token. They are LAN-only by default, short-lived and must
    be explicitly approved from the authenticated Docker dashboard.

    Approved phones receive a separate device token. Only a SHA-256 hash is
    persisted on the Pi; the plaintext token is returned through the approved
    pairing request and then lives on the phone.
    """

    def __init__(self, storage_path: str | None = None, ttl_seconds: int = 300) -> None:
        self.storage_path = Path(storage_path or os.getenv("DEVICE_PAIRING_FILE", "data/device_pairings.json"))
        self.ttl_seconds = max(60, int(os.getenv("DEVICE_PAIRING_TTL_SECONDS", str(ttl_seconds))))
        self.allow_remote = os.getenv("DEVICE_PAIRING_ALLOW_REMOTE", "false").strip().lower() in {"1", "true", "yes", "on"}
        self._lock = threading.RLock()
        self._pending: dict[str, PendingPairing] = {}
        self._paired: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.storage_path.read_text("utf-8"))
            self._paired = dict(raw.get("paired") or {})
        except Exception:
            self._paired = {}

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"paired": self._paired}, indent=2, sort_keys=True), "utf-8")
        tmp.replace(self.storage_path)

    @staticmethod
    def _is_lan(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip.split("%", 1)[0])
            return addr.is_private or addr.is_loopback or addr.is_link_local
        except ValueError:
            return False

    def request(self, device_id: str, name: str, remote_ip: str, device_type: str = "android") -> dict:
        device_id = device_id.strip()[:128]
        if not device_id:
            raise ValueError("device_id is required")
        if not self.allow_remote and not self._is_lan(remote_ip):
            raise PermissionError("pairing requests are limited to the local network")
        now = time.time()
        with self._lock:
            self._cleanup(now)
            for old in self._pending.values():
                if old.device_id == device_id and old.status == "pending":
                    return self._public_pending(old)
            item = PendingPairing(
                request_id=secrets.token_urlsafe(24),
                device_id=device_id,
                name=(name.strip() or "Android phone")[:120],
                remote_ip=remote_ip[:80],
                created_epoch=now,
                device_type=str(device_type).strip().lower()[:40] or "android",
            )
            self._pending[item.request_id] = item
            return self._public_pending(item)

    def _cleanup(self, now: float | None = None) -> None:
        now = now or time.time()
        expired = [rid for rid, item in self._pending.items() if now - item.created_epoch > self.ttl_seconds]
        for rid in expired:
            self._pending.pop(rid, None)

    @staticmethod
    def _public_pending(item: PendingPairing) -> dict:
        return {
            "request_id": item.request_id,
            "device_id": item.device_id,
            "name": item.name,
            "device_type": item.device_type,
            "remote_ip": item.remote_ip,
            "created_epoch": item.created_epoch,
            "status": item.status,
        }

    def pending(self) -> list[dict]:
        with self._lock:
            self._cleanup()
            return [
                self._public_pending(x)
                for x in sorted(self._pending.values(), key=lambda x: x.created_epoch, reverse=True)
                if x.status == "pending"
            ]

    def approve(self, request_id: str) -> dict:
        with self._lock:
            self._cleanup()
            item = self._pending.get(request_id)
            if not item or item.status != "pending":
                raise ValueError("pairing request was not found or has expired")
            token = secrets.token_urlsafe(36)
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            self._paired[item.device_id] = {
                "device_id": item.device_id,
                "name": item.name,
                "device_type": item.device_type,
                "token_sha256": digest,
                "approved_epoch": time.time(),
                "last_ip": item.remote_ip,
            }
            self._save()
            item.status = "approved"
            item.issued_token = token
            return {"ok": True, "device_id": item.device_id, "name": item.name}

    def reject(self, request_id: str) -> dict:
        with self._lock:
            self._cleanup()
            item = self._pending.get(request_id)
            if not item:
                raise ValueError("pairing request was not found or has expired")
            item.status = "rejected"
            return {"ok": True}

    def status(self, request_id: str, device_id: str) -> dict:
        with self._lock:
            self._cleanup()
            item = self._pending.get(request_id)
            if not item or item.device_id != device_id:
                return {"status": "expired"}
            result = {"status": item.status, "request_id": item.request_id}
            if item.status == "approved" and item.issued_token:
                result["device_token"] = item.issued_token
                item.issued_token = ""
                self._pending.pop(request_id, None)
            elif item.status == "rejected":
                self._pending.pop(request_id, None)
            return result

    def authorize_device_token(self, token: str) -> bool:
        if not token:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            return any(
                secrets.compare_digest(str(item.get("token_sha256", "")), digest)
                for item in self._paired.values()
            )

    def paired(self) -> list[dict]:
        with self._lock:
            return [
                {k: v for k, v in item.items() if k != "token_sha256"}
                for item in sorted(self._paired.values(), key=lambda x: float(x.get("approved_epoch", 0)), reverse=True)
            ]

    def revoke(self, device_id: str) -> dict:
        with self._lock:
            existed = self._paired.pop(device_id, None) is not None
            if existed:
                self._save()
            return {"ok": True, "revoked": existed}


class MdnsAdvertiser:
    """Advertise the NekoSuneAI server to Android NSD.

    The mDNS record always contains the local IPv4/port so discovery still works
    without DNS. When NEKOSUNEAI_PUBLIC_URL is configured with HTTPS, the same
    record also advertises that public origin and Android should prefer it for
    pairing and all later API traffic.
    """

    def __init__(self, port: int, name: str = "NekoSuneAI") -> None:
        self.port = int(port)
        self.name = name
        host_label = os.getenv("NEKOSUNEAI_INSTANCE_NAME", "").strip() or socket.gethostname()
        self.instance_name = f"{name} - {host_label}"[:60]
        self.public_url = os.getenv("NEKOSUNEAI_PUBLIC_URL", "").strip().rstrip("/")
        if self.public_url and not self.public_url.lower().startswith("https://"):
            print("NekoSuneAI discovery: ignoring NEKOSUNEAI_PUBLIC_URL because it is not HTTPS")
            self.public_url = ""
        self._zc = None
        self._info = None

    @staticmethod
    def _local_ipv4() -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"
        finally:
            sock.close()

    def start(self) -> bool:
        try:
            from zeroconf import ServiceInfo, Zeroconf

            ip = self._local_ipv4()
            properties = {
                b"pairing": b"1",
                b"path": b"/",
                b"name": self.name.encode("utf-8"),
                b"instance": self.instance_name.encode("utf-8"),
                b"local_url": f"http://{ip}:{self.port}".encode("utf-8"),
            }
            if self.public_url:
                properties[b"public_url"] = self.public_url.encode("utf-8")
                properties[b"preferred_scheme"] = b"https"

            self._zc = Zeroconf()
            self._info = ServiceInfo(
                "_nekosuneai._tcp.local.",
                f"{self.instance_name}._nekosuneai._tcp.local.",
                addresses=[socket.inet_aton(ip)],
                port=self.port,
                properties=properties,
                server=f"{socket.gethostname()}.local.",
            )
            self._zc.register_service(self._info, allow_name_change=True)
            if self.public_url:
                print(f"NekoSuneAI discovery: advertising HTTPS pairing origin {self.public_url} with local fallback http://{ip}:{self.port}")
            else:
                print(f"NekoSuneAI discovery: advertising local pairing origin http://{ip}:{self.port}")
            return True
        except Exception as exc:
            print(f"NekoSuneAI mDNS discovery unavailable: {exc}")
            self.stop()
            return False

    def stop(self) -> None:
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
        except Exception:
            pass
        try:
            if self._zc:
                self._zc.close()
        except Exception:
            pass
        self._zc = None
        self._info = None
