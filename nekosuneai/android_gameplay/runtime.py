from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import cv2
import numpy as np

from .device import AndroidDevice
from .memory import GameMemory
from .ollama_client import OllamaClient, OllamaError
from .vision import TemplateVision, HybridVision
from .learning import GameLearning, outcome


@dataclass
class AgentRuntime:
    device: AndroidDevice
    ollama: OllamaClient
    vision: TemplateVision | HybridVision
    memory: GameMemory
    game_name: str
    package_name: str
    profile_rules: list[str]
    goal: str

    capture_interval_ms: int = 120
    pause_after_action_ms: int = 180
    max_actions: int = 500
    never_spend_premium: bool = True
    stop_on_repeated_failures: int = 8
    auto_launch: bool = True

    fast_mode: bool = True
    frame_change_threshold: float = 1.8
    unchanged_wait_ms: int = 120
    decision_cooldown_ms: int = 20
    model_min_interval_ms: int = 1200
    idle_backoff_max_ms: int = 5000
    max_consecutive_waits: int = 2
    log_model_latency: bool = True
    auto_upgrade: bool = False
    min_energy: int = 10
    village_retry_seconds: int = 180
    learning_options: dict = field(default_factory=dict)
    learning_root: str = "."
    learning: Optional[GameLearning] = field(default=None, init=False)

    on_frame: Optional[Callable] = None
    on_log: Optional[Callable[[str], None]] = None
    on_state: Optional[Callable[[str], None]] = None

    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _pause: threading.Event = field(default_factory=threading.Event, init=False)
    history: list[dict] = field(default_factory=list, init=False)
    _last_observations: Optional[list] = field(default=None, init=False)
    _ignore_learning: bool = field(default=False, init=False)
    _village_retry_after: float = field(default=0.0, init=False)
    _village_wait: float = field(default=0.0, init=False)
    _last_model_call: float = field(default=0.0, init=False)

    def log(self, message: str):
        if self.on_log:
            self.on_log(message)

    def state(self, message: str):
        if self.on_state:
            self.on_state(message)

    def stop(self):
        self._stop.set()
        self._pause.clear()

    def pause(self):
        self._pause.set()
        self.state("Paused")

    def resume(self):
        self._pause.clear()
        self.state("Running")

    @staticmethod
    def _signature(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (96, 54), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _change_score(old_sig, new_sig) -> float:
        if old_sig is None:
            return 999.0
        return float(np.mean(cv2.absdiff(old_sig, new_sig)))

    def _safe_wait(self, reason: str) -> dict:
        return {
            "action": "wait",
            "seconds": max(0.08, self.unchanged_wait_ms / 1000.0),
            "reason": reason,
        }

    @staticmethod
    def _norm_to_pixel(v, limit: int) -> int:
        v = max(0.0, min(1000.0, float(v)))
        return int(round((v / 1000.0) * max(0, limit - 1)))

    def _validate(self, action: dict, w: int, h: int, observations=None) -> dict:
        if not isinstance(action, dict):
            return self._safe_wait("Invalid action object")

        action = dict(action)
        kind = str(action.get("action", "")).strip().lower()
        allowed = {
            "tap", "long_press", "swipe",
            "back", "home", "key", "text",
            "wait", "stop",
        }
        if kind not in allowed:
            return self._safe_wait(f"Unsupported action: {kind or 'missing'}")
        action["action"] = kind

        try:
            if kind in {"tap", "long_press"}:
                # Preferred normalized coordinate format.
                if "target_id" in action:
                    target = next((item for item in observations or []
                                   if str(item.get("id")) == str(action["target_id"])), None)
                    if target is None:
                        return self._safe_wait("Unknown detection target")
                    if (target.get("name") == "ocr/text"
                            and getattr(getattr(self, "ollama", None), "vision_enabled", True) is False):
                        return self._safe_wait("Plain screen text is not a button; choose a detected control target_id")
                    if target.get("enabled") is False:
                        return self._safe_wait("Target is disabled, completed, or unaffordable")
                    if self.never_spend_premium and self._costs_real_money(target):
                        return self._safe_wait("Real-money purchase; only the person may decide to pay")
                    x, y = target["center"]
                    x, y = max(0, min(w - 1, int(x))), max(0, min(h - 1, int(y)))
                elif "nx" in action and "ny" in action:
                    x = self._norm_to_pixel(action["nx"], w)
                    y = self._norm_to_pixel(action["ny"], h)
                elif "x" in action and "y" in action:
                    # Backward compatibility.
                    x = max(0, min(w - 1, int(float(action["x"]))))
                    y = max(0, min(h - 1, int(float(action["y"]))))
                else:
                    return self._safe_wait(f"Incomplete {kind}")

                action["x"], action["y"] = x, y
                if ("target_id" not in action and observations is not None
                        and getattr(getattr(self, "ollama", None), "vision_enabled", True) is False):
                    target = next((item for item in observations
                                   if item["name"] != "ocr/text"
                                   and item["box"][0] <= x < item["box"][0]+item["box"][2]
                                   and item["box"][1] <= y < item["box"][1]+item["box"][3]), None)
                    if target is None:
                        return self._safe_wait("No detected target at those coordinates; choose a visible target_id")
                    action["target_id"] = target["id"]
                    x, y = target["center"]
                    action["x"], action["y"] = x, y
                # Also reject coordinate-based taps into known unavailable upgrade slots.
                for item in observations or []:
                    if item.get("enabled") is False and "box" in item:
                        bx, by, bw, bh = item.get("guard_box", item["box"])
                        if bx <= x < bx+bw and by <= y < by+bh:
                            return self._safe_wait("Unavailable upgrade target")

                if kind == "long_press":
                    action["duration_ms"] = max(
                        100, min(5000, int(action.get("duration_ms", 600)))
                    )

            elif kind == "swipe":
                if "from_target_id" in action or "to_target_id" in action:
                    source = next((m for m in observations or [] if str(m.get("id")) == str(action.get("from_target_id"))), None)
                    target = next((m for m in observations or [] if str(m.get("id")) == str(action.get("to_target_id"))), None)
                    if source is None or target is None or source is target:
                        return self._safe_wait("Unknown drag targets")
                    if source.get("enabled") is False or target.get("enabled") is False:
                        return self._safe_wait("Disabled drag target")
                    if source.get("name") == "coinmaster/merge_item":
                        if (target.get("name") != "coinmaster/merge_item"
                                or source.get("appearance_group") != target.get("appearance_group")):
                            return self._safe_wait("Merge items do not match")
                    action["x1"], action["y1"] = source["center"]
                    action["x2"], action["y2"] = target["center"]
                elif all(k in action for k in ("nx1", "ny1", "nx2", "ny2")):
                    action["x1"] = self._norm_to_pixel(action["nx1"], w)
                    action["y1"] = self._norm_to_pixel(action["ny1"], h)
                    action["x2"] = self._norm_to_pixel(action["nx2"], w)
                    action["y2"] = self._norm_to_pixel(action["ny2"], h)
                elif all(k in action for k in ("x1", "y1", "x2", "y2")):
                    action["x1"] = max(0, min(w - 1, int(float(action["x1"]))))
                    action["y1"] = max(0, min(h - 1, int(float(action["y1"]))))
                    action["x2"] = max(0, min(w - 1, int(float(action["x2"]))))
                    action["y2"] = max(0, min(h - 1, int(float(action["y2"]))))
                else:
                    return self._safe_wait("Incomplete swipe ignored")

                action["duration_ms"] = max(
                    50, min(5000, int(action.get("duration_ms", 250)))
                )

            elif kind == "key":
                action["key"] = str(action.get("key", "")).strip()
                if not action["key"]:
                    return self._safe_wait("Missing key")

            elif kind == "text":
                action["text"] = str(action.get("text", ""))[:200]

            elif kind == "wait":
                action["seconds"] = max(
                    0.08, min(2.0, float(action.get("seconds", 0.12)))
                )

        except (TypeError, ValueError, KeyError):
            return self._safe_wait(f"Malformed {kind}")

        return action

    def _execute(self, action: dict):
        kind = action["action"]
        if kind == "tap":
            self.device.tap(action["x"], action["y"])
        elif kind == "long_press":
            self.device.long_press(
                action["x"], action["y"], action["duration_ms"]
            )
        elif kind == "swipe":
            self.device.swipe(
                action["x1"], action["y1"],
                action["x2"], action["y2"],
                action["duration_ms"],
            )
        elif kind == "back":
            self.device.back()
        elif kind == "home":
            self.device.home()
        elif kind == "key":
            self.device.keyevent(action["key"])
        elif kind == "text":
            self.device.type_text(action["text"])
        elif kind == "wait":
            time.sleep(action["seconds"])
        elif kind == "stop":
            self.stop()

    def _observations(self, frame):
        h, w = frame.shape[:2]
        return [{"id": index, **m.details, "name": m.name,
                 **({"text": m.text} if m.text is not None else {}),
                 "confidence": round(m.confidence, 4), "center": list(m.center),
                 "normalized_center": [round(m.center[0]/max(1, w-1)*1000),
                                       round(m.center[1]/max(1, h-1)*1000)],
                 "box": [m.x, m.y, m.width, m.height]}
                for index, m in enumerate(self.vision.scan(frame))]

    @staticmethod
    def _costs_real_money(target):
        from .coinmaster_ui import looks_like_money
        return looks_like_money(target.get("text"))

    def _blocked(self, action, observations):
        if self._ignore_learning or self.learning is None:
            return False
        return self.learning.blocked(action, observations)

    def _scene_action(self, observations, consecutive_waits=0):
        """Deterministic taps for Coin Master screens with one obvious next move."""
        if self.package_name != "com.moonactive.cmboard":
            return None
        action = self._pick_scene_action(observations, consecutive_waits)
        if action is not None or consecutive_waits < 2:
            return action
        # Learning judges a whole kind of target, not one instance of it, so two
        # bad taps can veto the only move a screen offers and stall the run for
        # good. Once the loop has visibly stalled, try the blocked move again.
        self._ignore_learning = True
        try:
            action = self._pick_scene_action(observations, consecutive_waits)
        finally:
            self._ignore_learning = False
        if action is not None:
            action["ignore_learning"] = True
            action["reason"] += " (retrying a target learning had vetoed; nothing else is available)"
        return action

    def _pick_scene_action(self, observations, consecutive_waits):
        return (self._collect_free_action(observations)
                or self._close_popup_action(observations)
                or self._dismiss_action(observations)
                or self._close_panel_action(observations)
                or self._treasure_action(observations)
                or self._attack_action(observations)
                or self._upgrade_action(observations)
                or self._energy_action(observations)
                or self._village_action(observations)
                or self._leave_village_action(observations)
                or self._spin_action(observations)
                or self._continue_action(observations, consecutive_waits))

    def _leave_village_action(self, observations):
        # Nothing here is affordable any more, so go back and earn more coins.
        upgrades = [m for m in observations if m["name"] == "coinmaster/building_upgrade"]
        if not upgrades or any(m.get("enabled") is True for m in upgrades):
            return None
        for item in observations:
            if item["name"] != "coinmaster/back_to_board" or item.get("enabled") is not True:
                continue
            prices = [m["price_coins"] for m in upgrades
                      if isinstance(m.get("price_coins"), (int, float))]
            short_of = f" (cheapest is {min(prices):,})" if prices else ""
            action = {"action": "tap", "target_id": item["id"],
                      "reason": f"Nothing affordable yet{short_of}; roll for coins instead"}
            if self._blocked(action, observations):
                continue
            # Each fruitless visit doubles the wait, so a village that is far out
            # of reach is not checked every few minutes for nothing.
            self._village_wait = min(self.village_retry_seconds * 8,
                                     max(self.village_retry_seconds, self._village_wait * 2))
            self._village_retry_after = time.monotonic() + self._village_wait
            return action
        return None

    def _spin_action(self, observations):
        # Holding the dice starts AutoRoll; the energy rule stops it in time.
        for item in observations:
            if item["name"] != "coinmaster/spin" or item.get("spinning"):
                continue
            energy = item.get("energy")
            if not isinstance(energy, int) or energy <= self.min_energy:
                continue
            action = {"action": "long_press", "target_id": item["id"], "duration_ms": 1500,
                      "reason": f"Hold the dice to auto-roll ({energy} energy left)"}
            if not self._blocked(action, observations):
                return action
        return None

    def _continue_action(self, observations, consecutive_waits):
        # A reward screen has no button at all. Tap it when it says so, or once
        # the loop has visibly stalled, so a misread screen is not tapped blindly.
        for item in observations:
            if item["name"] != "coinmaster/tap_anywhere":
                continue
            if not item.get("explicit") and consecutive_waits < 2:
                return None
            action = {"action": "tap", "target_id": item["id"],
                      "reason": "Tap to continue past a reward screen"}
            if not self._blocked(action, observations):
                return action
        return None

    def _collect_free_action(self, observations):
        # A giveaway is worth taking, but only where no price is on screen: the
        # detector withholds these targets entirely once money is in view.
        for item in observations:
            if item["name"] == "coinmaster/collect_free" and item.get("enabled") is True:
                action = {"action": "tap", "target_id": item["id"],
                          "reason": f"Collect the free reward ({item.get('text', 'collect')})"}
                if not self._blocked(action, observations):
                    return action
        return None

    def _close_popup_action(self, observations):
        # Offers and event popups are closed, never bought: paying is the
        # person's decision, so the agent only ever reaches for the X.
        for item in observations:
            if item["name"] not in ("coinmaster/close_popup", "coinmaster/leave_merge"):
                continue
            if item.get("enabled") is not True:
                continue
            action = {"action": "tap", "target_id": item["id"],
                      "reason": ("Leave the merge event; it is not trained yet"
                                 if item["name"] == "coinmaster/leave_merge"
                                 else "Close an offer or popup without buying anything")}
            if not self._blocked(action, observations):
                return action
        return None

    def _close_panel_action(self, observations):
        if any(item["name"] == "coinmaster/unwanted_panel" for item in observations):
            return {"action": "back", "reason": "Close the friends attack list; it is not part of the goal"}
        return None

    def _energy_action(self, observations):
        # A running auto-spin burns one energy per roll, so halt it while some is left.
        for item in observations:
            if item["name"] != "coinmaster/spin" or not item.get("spinning"):
                continue
            energy = item.get("energy")
            if not isinstance(energy, int) or energy > self.min_energy:
                continue
            action = {"action": "tap", "target_id": item["id"],
                      "reason": f"Stop auto-spin: only {energy} energy left"}
            if not self._blocked(action, observations):
                return action
        return None

    def _gate_village_button(self, observations):
        """Close the village door while waiting for coins.

        The scripted rule alone was not enough: the model kept choosing the
        hammer itself, which is how the board/village ping-pong started.
        """
        waiting = time.monotonic() < self._village_retry_after
        for item in observations:
            if item["name"] != "coinmaster/open_village":
                continue
            item["enabled"] = not waiting
            item["interaction"] = ("nothing in the village is affordable yet; keep rolling"
                                   if waiting else
                                   "open the village to spend coins on buildings")

    def _village_action(self, observations):
        # The hammer's red badge means buildings are waiting for coins. It keeps
        # showing when they are simply too expensive, so after a fruitless visit
        # the board is given time to earn before going back in.
        if not self.auto_upgrade or time.monotonic() < self._village_retry_after:
            return None
        for item in observations:
            if item["name"] != "coinmaster/open_village" or not item.get("pending_upgrades"):
                continue
            action = {"action": "tap", "target_id": item["id"],
                      "reason": "Open the village to spend coins on pending upgrades"}
            if not self._blocked(action, observations):
                return action
        return None

    def _dismiss_action(self, observations):
        # A finished raid or attack leaves one OK button; nothing else is clickable.
        for item in observations:
            if item["name"] != "coinmaster/result_continue" or item.get("enabled") is not True:
                continue
            action = {"action": "tap", "target_id": item["id"],
                      "reason": f"Dismiss result dialog at {tuple(item['center'])}"}
            if not self._blocked(action, observations):
                return action
        return None

    def _treasure_action(self, observations):
        # The raid screen keeps offering bags until the last dig is spent; any bag works.
        bags = [m for m in observations if m["name"] == "coinmaster/treasure_choice"
                and m.get("enabled") is True]
        random.shuffle(bags)
        for bag in bags:
            action = {"action": "tap", "target_id": bag["id"],
                      "reason": f"Dig treasure bag at {tuple(bag['center'])}"}
            if not self._blocked(action, observations):
                return action
        return None

    def _attack_action(self, observations):
        # Every reticle on a raided village pays out; the header buttons next to
        # them do not, so pick a marker here instead of letting a guess land there.
        markers = [m for m in observations if m["name"] == "coinmaster/attack_target"
                   and m.get("enabled") is True]
        random.shuffle(markers)
        for marker in markers:
            action = {"action": "tap", "target_id": marker["id"],
                      "reason": f"Attack marked building at {tuple(marker['center'])}"}
            if not self._blocked(action, observations):
                return action
        return None

    def _upgrade_action(self, observations):
        if not self.auto_upgrade or self.package_name != "com.moonactive.cmboard":
            return None
        candidates = [m for m in observations if m["name"] == "coinmaster/building_upgrade"
                      and m.get("enabled") is True and m.get("state") == "affordable"
                      and isinstance(m.get("price_coins"), (int, float)) and m["price_coins"] > 0
                      and isinstance(m.get("balance_coins"), (int, float))
                      and m["balance_coins"] >= m["price_coins"]]
        for target in sorted(candidates, key=lambda m: m["price_coins"]):
            action = {"action": "tap", "target_id": target["id"],
                      "reason": f"Upgrade slot {target['slot']} for {target['price_coins']:,} normal coins"}
            if not self._blocked(action, observations):
                # Coins are flowing again, so the village is worth a visit.
                self._village_wait = 0.0
                self._village_retry_after = 0.0
                return action
        return None

    def run(self):
        self._stop.clear()
        self._last_observations = None
        self._village_retry_after = 0.0
        self._village_wait = 0.0
        self._last_model_call = 0.0
        failures = 0
        consecutive_waits = 0
        previous_sig = None

        self.state("Running")
        self.log(f"Game: {self.game_name or self.package_name or 'Unknown'}")
        self.log(f"Goal: {self.goal}")
        if self.fast_mode:
            self.log("FAST MODE enabled")

        if not self.ollama.health():
            self.state("Error")
            self.log("Ollama is not reachable. Check the URL/server.")
            return

        if self.ollama.vision_enabled:
            try:
                supports_vision, caps = self.ollama.model_supports_vision()
                if not supports_vision:
                    self.state("Error")
                    self.log(
                        f"MODEL HAS NO VISION: '{self.ollama.model}'. "
                        f"Capabilities reported by Ollama: {caps or 'none/unknown'}"
                    )
                    self.log(
                        "Use a vision model such as qwen2.5vl:3b or qwen3-vl:2b/4b."
                    )
                    return
                self.log(f"Vision model OK: {self.ollama.model}")
            except Exception as exc:
                self.log(f"Warning: could not verify model vision capability: {exc}")
        else:
            self.log("Local vision on CPU; Ollama receives text observations only.")

        try:
            devices = self.device.list_devices()
            if not devices and not self.device.serial:
                self.state("Error")
                self.log("No ADB devices found.")
                return

            if not self.device.serial and devices:
                self.device.serial = devices[0]
                self.log(f"Using ADB device: {self.device.serial}")

            env = self.device.device_environment()
            self.log(
                f"ADB environment: {self.device.environment_name()} | "
                f"model={env.get('model') or 'unknown'} | "
                f"android={env.get('release') or 'unknown'} | "
                f"serial={self.device.serial or 'default'}"
            )
            self.log(f"Android size: {self.device.screen_size()}")
            if self.learning_options.get("enabled", False):
                self.learning = GameLearning(
                    self.learning_root, self.package_name, self.device.package_version(self.package_name),
                    self.learning_options.get("layout_revision", "1"), self.goal,
                    self.learning_options.get("required_functions", []),
                    self.learning_options.get("confirmations", 3),
                )
                self.log(f"Learning: {self.learning.data['status']}; game version {self.learning.data['game_version']}; "
                         f"remaining: {', '.join(self.learning.remaining()) or 'none'}")

            if self.auto_launch and self.package_name:
                self.log(f"Launching: {self.package_name}")
                self.device.launch_package(self.package_name)
                time.sleep(0.45)

        except Exception as exc:
            self.state("Error")
            self.log(f"ADB error: {exc}")
            return

        for step in range(1, self.max_actions + 1):
            if self._stop.is_set():
                break

            while self._pause.is_set() and not self._stop.is_set():
                time.sleep(0.05)

            if self._stop.is_set():
                break

            try:
                frame = self.device.screenshot()
                h, w = frame.shape[:2]

                if self.on_frame:
                    self.on_frame(frame)

                current_sig = self._signature(frame)
                change_score = self._change_score(previous_sig, current_sig)
                frame_changed = change_score >= self.frame_change_threshold

                # Re-reading a frame that has not moved costs seconds and
                # returns the same answer, so keep the previous reading.
                if not frame_changed and self._last_observations is not None:
                    observations = self._last_observations
                else:
                    observations = self._observations(frame)
                    self._last_observations = observations
                self._gate_village_button(observations)

                if not self.ollama.vision_enabled and not observations:
                    self.log("No objects, text, or game templates detected; stopping without guessing input.")
                    break

                buttons = [item for item in observations if item["name"] == "ocr/button"]
                attacks = [item for item in observations if item["name"] == "coinmaster/attack_target"]
                results = [item for item in observations if item["name"] == "coinmaster/result_continue"]
                if results:
                    self.log("Result OK target: " + "; ".join(f"id {m['id']} @ {tuple(m['center'])}" for m in results))
                bags = [item for item in observations if item["name"] == "coinmaster/treasure_choice"]
                if bags:
                    self.log("Treasure bags: " + "; ".join(f"id {m['id']} @ {tuple(m['center'])}" for m in bags))
                if attacks:
                    self.log("Attack targets: " + "; ".join(f"id {m['id']} @ {tuple(m['center'])}" for m in attacks))
                if buttons:
                    self.log("OCR buttons: " + "; ".join(
                        f"{item['text']} @ {tuple(item['center'])}" for item in buttons))
                upgrades = [item for item in observations if item["name"] == "coinmaster/building_upgrade"]
                if upgrades:
                    self.log("Upgrades: " + "; ".join(
                        f"slot {item['slot']}: {item['state']} (cost {item['price_coins']}, coins {item['balance_coins']})"
                        for item in upgrades))

                action = self._scene_action(observations, consecutive_waits)
                latency = 0.0
                if action is None:
                    # One request at a time, with a floor between them: a stalled
                    # screen used to re-ask as fast as the GPU could answer.
                    gap = self.model_min_interval_ms/1000 - (time.monotonic() - self._last_model_call)
                    if gap > 0 and self._stop.wait(gap):
                        break
                    self._last_model_call = time.monotonic()
                    action, latency = self.ollama.decide(
                        game_name=self.game_name,
                        package_name=self.package_name,
                        profile_rules=self.profile_rules,
                        user_goal=self.goal,
                        frame=frame,
                        width=w,
                        height=h,
                        observations=observations,
                        history=self.history,
                        memory=({"learning": self.learning.context(observations)} if self.learning
                                else self.memory.summary()),
                        never_spend_premium=self.never_spend_premium,
                        consecutive_waits=consecutive_waits,
                        frame_changed=frame_changed,
                    )

                action = self._validate(action, w, h, observations)
                if (self.learning and not action.get("ignore_learning")
                        and self.learning.blocked(action, observations)):
                    self.log("Learning rejected a repeated ineffective action; choose another visible target or method.")
                    action = self._safe_wait("Previously ineffective target/method")

                if action["action"] == "wait":
                    consecutive_waits += 1
                else:
                    consecutive_waits = 0

                # Show the actual Android coordinates sent to ADB.
                coord = ""
                if action["action"] in {"tap", "long_press"}:
                    coord = f" @ ({action['x']},{action['y']})"
                elif action["action"] == "swipe":
                    coord = (
                        f" @ ({action['x1']},{action['y1']})"
                        f" -> ({action['x2']},{action['y2']})"
                    )

                latency_text = (
                    f" | Ollama {latency:.2f}s"
                    if self.log_model_latency else ""
                )
                self.log(
                    f"[{step}] {action['action']}{coord} — "
                    f"{action.get('reason', '')}{latency_text}"
                )

                self.history.append(action)
                self.history = self.history[-30:]
                if self._stop.is_set():
                    break
                if self._pause.is_set():
                    continue
                self._execute(action)

                if self.learning and action["action"] not in {"wait", "stop"}:
                    if self._stop.wait(max(.8, self.pause_after_action_ms / 1000)):
                        break
                    after_frame = self.device.screenshot()
                    after_observations = self._observations(after_frame)
                    difference = self._change_score(current_sig, self._signature(after_frame))
                    if outcome(action, observations, after_observations, difference)[0] != "confirmed":
                        if self._stop.wait(1.2):
                            break
                        after_frame = self.device.screenshot()
                        after_observations = self._observations(after_frame)
                        difference = self._change_score(current_sig, self._signature(after_frame))
                    result, reason, promoted = self.learning.record(action, observations, after_observations, difference)
                    self.log(f"Learning {result}: {reason}")
                    self.log(f"Training coverage: {len(self.learning.required)-len(self.learning.remaining())}"
                             f"/{len(self.learning.required)} functions confirmed")
                    if promoted:
                        self.log(f"Training checklist complete. Skill v{self.learning.data['skill_version']} saved: "
                                 f"{self.learning.skill_path}. Continuing play.")
                    if result == "confirmed":
                        self.memory.remember_success({**action, "verification": reason})

                failures = 0
                previous_sig = current_sig

                if action["action"] == "stop":
                    break

                delay_ms = (
                    self.decision_cooldown_ms
                    if self.fast_mode
                    else self.pause_after_action_ms
                )
                if consecutive_waits:
                    # Nothing is happening, so ease off rather than burning GPU
                    # on the same unchanged screen: 120ms, 240ms, 480ms, ... 
                    delay_ms = max(delay_ms, min(self.idle_backoff_max_ms,
                                                 self.unchanged_wait_ms * 2**consecutive_waits))
                if delay_ms > 0 and self._stop.wait(delay_ms / 1000.0):
                    break

            except Exception as exc:
                failures += 1
                msg = f"Agent error ({failures}): {exc}"
                self.log(msg)
                if not isinstance(exc, OllamaError):
                    self.memory.remember_failure(msg)
                if failures >= self.stop_on_repeated_failures:
                    self.log("Too many repeated failures; stopping.")
                    break
                time.sleep(max(0.1, self.capture_interval_ms / 1000.0))

        self.state("Stopped")
