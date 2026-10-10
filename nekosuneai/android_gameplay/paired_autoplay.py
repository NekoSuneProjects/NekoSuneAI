"""Optional supervised Android autoplay using the EXISTING AgentRuntime.

Only the locally configured, trusted inference endpoint is used. Remote commands
may set an approved goal, but may not supply model URLs or arbitrary programs.
"""
from __future__ import annotations
import json
import threading
import time
from pathlib import Path
from typing import Callable


class GuardedAndroidDevice:
    """Keep existing gameplay input inside the owner's approved foreground app."""

    def __init__(self, device, package: str, is_allowed: Callable[[], bool], on_action=None):
        self._device, self._package, self._allowed = device, package, is_allowed
        self._on_action = on_action

    def _check(self):
        if not self._allowed():
            raise PermissionError("Approved session has ended or is paused")
        if self._device.foreground_package() != self._package:
            raise PermissionError("Foreground application is no longer the approved game")

    # No delegation of private/raw ADB methods (_run, shell, force_stop).
    # Input may only use these explicitly guarded entry points.
    _INPUT = frozenset({"tap", "long_press", "swipe", "back", "keyevent"})
    _READ = frozenset({"screenshot", "foreground_package", "screen_size",
                       "package_version", "device_environment", "environment_name",
                       "list_devices", "getprop", "list_packages", "input_help"})

    def __getattr__(self, name):
        if name not in self._INPUT | self._READ:
            raise AttributeError(f"Paired autoplay does not expose device operation: {name}")
        target = getattr(self._device, name)
        if not callable(target):
            raise AttributeError(f"Unsupported device operation: {name}")
        def guarded(*args, **kwargs):
            self._check()
            if name == "keyevent":
                # No Home, settings, purchases or unrestricted key injection.
                raise PermissionError("Unrestricted key events are disabled in paired autoplay")
            result = target(*args, **kwargs)
            if name in self._INPUT and self._on_action:
                self._on_action()
            return result
        return guarded


class PairedAutoplay:
    def __init__(self, worker, model_url: str, model: str,
                 config_file: str = "config.json"):
        if not model_url.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
            raise ValueError("Autoplay model URL must use HTTPS or loopback")
        if not model or len(model) > 128:
            raise ValueError("Configure a model name locally")
        self.worker = worker
        self.model_url, self.model = model_url, model
        self.config_file = Path(config_file)
        self.runtime = None
        self.thread = None
        self.last_state = "idle"
        self.latest_log = ""

    def _account_action(self):
        self.worker.actions_used += 1
        if self.worker.actions_used >= self.worker.max_actions:
            self.stop()

    def start(self, goal: str):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("An autonomous run is already active")
        if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 500:
            raise ValueError("Supply an approved goal of 1–500 characters")
        self.worker._active()
        if self.worker.paused:
            raise PermissionError("Resume the paused session before autoplay")
        package = self.worker.package
        guarded = GuardedAndroidDevice(
            self.worker.device, package,
            lambda: self.worker.session_id != "" and self.worker.package == package
            and not self.worker.paused and not self.worker.stop_event.is_set()
            and time.monotonic() < self.worker.session_deadline
            and self.worker.actions_used < self.worker.max_actions,
            on_action=self._account_action,
        )
        from .ollama_client import OllamaClient
        from .memory import GameMemory
        from .runtime import AgentRuntime
        from .vision import TemplateVision, HybridVision, NullVision, OCRVision
        config = json.loads(self.config_file.read_text(encoding="utf-8")) if self.config_file.exists() else {}
        vision_cfg = config.get("vision") or {}
        model_cfg = config.get("ollama") or {}
        # Keep inference on the selected, locally configured host; the model URL
        # and identity are NEVER received from an untrusted game command.
        ollama = OllamaClient(
            base_url=self.model_url, model=self.model,
            vision_enabled=bool(model_cfg.get("vision_enabled", False)),
            timeout=min(120, max(10, int(model_cfg.get("timeout_seconds", 60)))),
        )
        templates = TemplateVision(
            str(vision_cfg.get("templates_root", "templates")), package,
            threshold=float(vision_cfg.get("template_threshold", 0.86)),
        )
        if ollama.vision_enabled:
            vision = templates
        else:
            vision = HybridVision(
                templates, NullVision(),
                OCRVision() if vision_cfg.get("ocr_enabled", True) else None,
                game_id=package,
            )
        memory = GameMemory(directory=str((config.get("memory") or {}).get("directory", "memory")),
                            game_id=package, enabled=True)
        self.runtime = AgentRuntime(
            device=guarded, ollama=ollama, vision=vision, memory=memory,
            game_name=package, package_name=package,
            profile_rules=["Never purchase with real money or spend premium currency.",
                           "Stop when the target is uncertain or unrecognised."],
            goal=goal.strip(), max_actions=max(1, self.worker.max_actions - self.worker.actions_used),
            never_spend_premium=True, auto_launch=False,
            on_log=lambda line: setattr(self, "latest_log", str(line)[-500:]),
            on_state=lambda state: setattr(self, "last_state", str(state)),
        )
        self.last_state = "starting"
        self.thread = threading.Thread(target=self.runtime.run, daemon=True,
                                       name="nekosuneai-android-paired-autoplay")
        self.thread.start()
        return {"autoplay": "started", "game_id": package, "session_id": self.worker.session_id}

    def pause(self):
        if self.runtime:
            self.runtime.pause()

    def resume(self):
        if self.runtime:
            self.runtime.resume()

    def stop(self):
        if self.runtime:
            self.runtime.stop()
        self.last_state = "stopping" if self.thread and self.thread.is_alive() else "stopped"

    def status(self):
        return {"status": self.last_state, "running": bool(self.thread and self.thread.is_alive()),
                "latest_log": self.latest_log}
