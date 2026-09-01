"""Authenticated, capability-scoped peripheral nodes.

The core assistant never sends an arbitrary command to a node.  Every node
declares a small capability manifest and every queued action is checked
against that manifest.  State-changing capabilities require explicit
confirmation unless the owner has deliberately changed their policy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any


_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$")
_VALID_KINDS = {"read", "write"}
_VALID_POLICIES = {"allow", "confirm", "deny"}
_APPROVED_DEVICE_PAIRING_ID = "approved-device"


class PeripheralNodeRegistry:
    """Persistent pairing, status and command queue for lightweight nodes."""

    def __init__(self, storage_path: str | Path | None = None, online_seconds: int = 90) -> None:
        default_path = os.getenv("PERIPHERAL_NODES_FILE", "data/peripheral_nodes.json")
        self.storage_path = Path(storage_path or default_path)
        self.online_seconds = max(15, int(online_seconds))
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._pairings: dict[str, dict[str, Any]] = {}
        self._nodes: dict[str, dict[str, Any]] = {}
        self._audit: list[dict[str, Any]] = []
        self._load()

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalise_manifest(raw: Any) -> dict[str, dict[str, str]]:
        if not isinstance(raw, (dict, list)):
            raise ValueError("capabilities must be an object or list")
        entries = raw.items() if isinstance(raw, dict) else ((str(item), {}) for item in raw)
        result: dict[str, dict[str, str]] = {}
        for name, details in entries:
            capability = str(name).strip().lower()
            if not _CAPABILITY_RE.fullmatch(capability):
                raise ValueError(f"invalid capability name: {capability or '<empty>'}")
            settings = details if isinstance(details, dict) else {}
            kind = str(settings.get("kind", "read")).strip().lower()
            if kind not in _VALID_KINDS:
                raise ValueError(f"invalid capability kind for {capability}")
            default_policy = "allow" if kind == "read" else "confirm"
            policy = str(settings.get("policy", default_policy)).strip().lower()
            if policy not in _VALID_POLICIES:
                raise ValueError(f"invalid capability policy for {capability}")
            if kind == "write" and policy == "allow":
                policy = "confirm"
            result[capability] = {"kind": kind, "policy": policy}
        if not result:
            raise ValueError("at least one capability is required")
        if len(result) > 128:
            raise ValueError("a node may declare at most 128 capabilities")
        return result

    def _load(self) -> None:
        try:
            raw = json.loads(self.storage_path.read_text("utf-8"))
            if isinstance(raw, dict):
                self._nodes = dict(raw.get("nodes") or {})
                self._audit = list(raw.get("audit") or [])[-500:]
        except Exception:
            self._nodes, self._audit = {}, []

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"nodes": self._nodes, "audit": self._audit[-500:]}, indent=2, sort_keys=True),
            "utf-8",
        )
        tmp.replace(self.storage_path)

    def _log(self, event: str, node_id: str, **details: Any) -> None:
        self._audit.append({"epoch": time.time(), "event": event, "node_id": node_id, **details})
        del self._audit[:-500]

    def create_pairing(self, name: str = "New node", ttl_seconds: int = 300) -> dict[str, Any]:
        """Create a short-lived, one-use code from an authenticated dashboard."""
        with self._lock:
            now = time.time()
            self._cleanup_pairings(now)
            code = "-".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
            pairing_id = secrets.token_urlsafe(18)
            self._pairings[pairing_id] = {
                "code_sha256": self._hash(code),
                "name": str(name).strip()[:80] or "New node",
                "expires_epoch": now + max(60, min(int(ttl_seconds), 1800)),
            }
            return {
                "pairing_id": pairing_id,
                "pairing_code": code,
                "expires_epoch": self._pairings[pairing_id]["expires_epoch"],
            }

    def _cleanup_pairings(self, now: float | None = None) -> None:
        current = time.time() if now is None else now
        for pairing_id in [
            key for key, item in self._pairings.items() if float(item.get("expires_epoch", 0)) <= current
        ]:
            self._pairings.pop(pairing_id, None)

    def register(
        self,
        pairing_id: str,
        pairing_code: str,
        node_id: str,
        name: str,
        node_type: str,
        capabilities: Any,
        remote_ip: str = "",
    ) -> dict[str, Any]:
        node_id = str(node_id).strip()[:128]
        if not node_id or not re.fullmatch(r"[A-Za-z0-9._:-]+", node_id):
            raise ValueError("node_id must contain only letters, numbers, dot, colon, underscore or hyphen")
        manifest = self._normalise_manifest(capabilities)

        approved_device = str(pairing_id).strip() == _APPROVED_DEVICE_PAIRING_ID
        approved_device_token = str(pairing_code).strip()
        pairing: dict[str, Any] | None = None
        if approved_device:
            # Reuse the same owner-approved request flow as the Android app.
            # DevicePairingManager persists approved token hashes, so a fresh
            # manager safely validates the one-time token returned by
            # /api/pairing/status after the owner presses Approve.
            from .device_pairing import DevicePairingManager

            if not DevicePairingManager().authorize_device_token(approved_device_token):
                raise PermissionError("device pairing approval is invalid or expired")
        else:
            with self._lock:
                self._cleanup_pairings()
                pairing = self._pairings.get(str(pairing_id))
                if not pairing or not secrets.compare_digest(
                    str(pairing.get("code_sha256", "")), self._hash(str(pairing_code).strip().upper())
                ):
                    raise PermissionError("invalid or expired pairing code")

        with self._changed:
            token = secrets.token_urlsafe(42)
            now = time.time()
            self._nodes[node_id] = {
                "node_id": node_id,
                "name": str(name).strip()[:80] or str((pairing or {}).get("name") or "Peripheral node"),
                "node_type": str(node_type).strip().lower()[:40] or "generic",
                "token_sha256": self._hash(token),
                "capabilities": manifest,
                "registered_epoch": now,
                "last_seen_epoch": now,
                "last_ip": str(remote_ip)[:80],
                "latency_ms": None,
                "battery_percent": None,
                "state": {},
                "commands": [],
                "next_command_id": 1,
            }
            if not approved_device:
                self._pairings.pop(str(pairing_id), None)
            self._log(
                "registered",
                node_id,
                node_type=self._nodes[node_id]["node_type"],
                pairing_mode="device-approval" if approved_device else "node-code",
            )
            self._save()
            self._changed.notify_all()
            return {"node": self._public(self._nodes[node_id]), "device_token": token}

    def authorize(self, node_id: str, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            node = self._nodes.get(str(node_id))
            return bool(node) and secrets.compare_digest(str(node.get("token_sha256", "")), self._hash(token))

    def heartbeat(
        self,
        node_id: str,
        state: dict[str, Any] | None = None,
        latency_ms: float | None = None,
        battery_percent: float | None = None,
        remote_ip: str = "",
        ack_command_id: int | None = None,
    ) -> dict[str, Any]:
        with self._changed:
            node = self._nodes.get(str(node_id))
            if not node:
                raise ValueError("node is not registered")
            node["last_seen_epoch"] = time.time()
            node["last_ip"] = str(remote_ip)[:80]
            if latency_ms is not None:
                node["latency_ms"] = max(0.0, min(float(latency_ms), 3_600_000.0))
            if battery_percent is not None:
                node["battery_percent"] = max(0.0, min(float(battery_percent), 100.0))
            if state is not None:
                encoded = json.dumps(state, default=str)
                if len(encoded) > 64_000:
                    raise ValueError("node state is too large")
                node["state"] = dict(state)
            if ack_command_id is not None:
                acknowledged = max(0, int(ack_command_id))
                node["commands"] = [
                    command for command in node.get("commands", [])
                    if int(command.get("id", 0)) > acknowledged
                ]
                self._log("commands_acknowledged", str(node_id), through=acknowledged)
            self._save()
            self._changed.notify_all()
            return self._public(node)

    def enqueue(
        self,
        node_id: str,
        capability: str,
        arguments: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
        requested_by: str = "assistant",
    ) -> dict[str, Any]:
        capability = str(capability).strip().lower()
        with self._changed:
            node = self._nodes.get(str(node_id))
            if not node:
                raise ValueError("node is not registered")
            spec = dict(node.get("capabilities") or {}).get(capability)
            if not spec:
                raise ValueError(f"node does not advertise {capability}")
            policy = str(spec.get("policy", "deny"))
            if policy == "deny":
                raise PermissionError(f"{capability} is denied for this node")
            if policy == "confirm" and not confirmed:
                raise PermissionError(f"{capability} requires explicit confirmation")
            item = {
                "id": int(node.get("next_command_id", 1)),
                "capability": capability,
                "arguments": dict(arguments or {}),
                "created_epoch": time.time(),
                "requested_by": str(requested_by)[:80],
                "confirmed": bool(confirmed),
            }
            node["next_command_id"] = item["id"] + 1
            node.setdefault("commands", []).append(item)
            del node["commands"][:-100]
            self._log("command_queued", str(node_id), capability=capability, command_id=item["id"])
            self._save()
            self._changed.notify_all()
            return item

    def action_policy(self, node_id: str, capability: str) -> str:
        """Return allow/confirm/deny for a declared capability.

        Missing nodes and capabilities are denied so routine previews fail
        closed instead of promising an action that cannot be executed.
        """
        with self._lock:
            node = self._nodes.get(str(node_id))
            if not node:
                return "deny"
            spec = dict(node.get("capabilities") or {}).get(str(capability).strip().lower())
            return str(spec.get("policy", "deny")) if spec else "deny"

    def wait_commands(self, node_id: str, after: int = 0, wait_seconds: float = 25.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + max(0.0, min(float(wait_seconds), 30.0))
        with self._changed:
            node = self._nodes.get(str(node_id))
            if not node:
                raise ValueError("node is not registered")
            while True:
                node["last_seen_epoch"] = time.time()
                pending = [x for x in node.get("commands", []) if int(x.get("id", 0)) > int(after)]
                if pending:
                    return pending
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._changed.wait(remaining)

    def set_policy(self, node_id: str, capability: str, policy: str) -> dict[str, Any]:
        policy = str(policy).strip().lower()
        if policy not in _VALID_POLICIES:
            raise ValueError("policy must be allow, confirm, or deny")
        with self._lock:
            node = self._nodes.get(str(node_id))
            if not node:
                raise ValueError("node is not registered")
            spec = dict(node.get("capabilities") or {}).get(str(capability).strip().lower())
            if not spec:
                raise ValueError("capability was not found")
            spec["policy"] = policy
            node["capabilities"][str(capability).strip().lower()] = spec
            self._log("policy_changed", str(node_id), capability=capability, policy=policy)
            self._save()
            return self._public(node)

    def list_nodes(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public(item) for item in self._nodes.values()]

    def audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._audit[-max(1, min(int(limit), 500)):])

    def revoke(self, node_id: str) -> bool:
        with self._lock:
            existed = self._nodes.pop(str(node_id), None) is not None
            if existed:
                self._log("revoked", str(node_id))
                self._save()
            return existed

    def _public(self, node: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in node.items() if key not in {"token_sha256", "commands"}}
        result["online"] = time.time() - float(node.get("last_seen_epoch", 0)) < self.online_seconds
        result["pending_commands"] = len(node.get("commands") or [])
        return result
