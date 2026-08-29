from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import requests


@dataclass(slots=True)
class MobileNotifier:
    """Send important NekoSuneAI events to an ntfy-compatible server.

    The feature is deliberately opt-in. It works with a self-hosted ntfy server
    on the Raspberry Pi or with another ntfy-compatible endpoint. No ntfy
    Python package is required; requests is already part of NekoSuneAI's base
    requirements.
    """

    base_url: str
    topic: str
    token: str = ""
    min_level: str = "warning"

    @classmethod
    def from_env(cls) -> "MobileNotifier | None":
        enabled = os.getenv("MOBILE_NOTIFY_ENABLED", "false").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return None

        base_url = os.getenv("MOBILE_NOTIFY_URL", "http://127.0.0.1:2586").strip().rstrip("/")
        topic = os.getenv("MOBILE_NOTIFY_TOPIC", "").strip()
        if not base_url or not topic:
            return None

        return cls(
            base_url=base_url,
            topic=topic,
            token=os.getenv("MOBILE_NOTIFY_TOKEN", "").strip(),
            min_level=os.getenv("MOBILE_NOTIFY_MIN_LEVEL", "warning").strip().lower(),
        )

    def should_send(self, level: str) -> bool:
        order = {"none": 0, "info": 1, "warning": 2, "danger": 3}
        actual = order.get((level or "none").lower(), 0)
        minimum = order.get(self.min_level, 2)
        return actual >= minimum

    def send(self, message: str, level: str = "warning") -> None:
        if not message or not self.should_send(level):
            return
        threading.Thread(
            target=self._send_sync,
            args=(message, level),
            daemon=True,
            name="nekosuneai-mobile-notify",
        ).start()

    def _send_sync(self, message: str, level: str) -> None:
        headers = {
            "Title": "NekoSuneAI",
            "Tags": "rotating_light" if level == "danger" else "warning",
            "Priority": "max" if level == "danger" else "high",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            requests.post(
                f"{self.base_url}/{self.topic}",
                data=message.encode("utf-8"),
                headers=headers,
                timeout=8,
            ).raise_for_status()
        except requests.RequestException as exc:
            print(f"NekoSuneAI mobile notification failed: {exc}")
