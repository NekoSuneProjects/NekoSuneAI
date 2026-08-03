"""GameAgent - the game-agnostic LLM control loop.

Each tick it observes the world, asks the LLM (via the shared engine) for a
short first-person thought plus one high-level command as JSON, narrates the
thought (so it appears in chat / TTS), executes the command through the
driver, and feeds the outcome back in. Runs on a daemon thread and never
crashes the app.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Callable

from ..config import Config
from ..engine import GenerationRequest, detect_emotion, generate_reply
from ..media_player import start_thinking_sound, stop_thinking_sound
from .base import GameCommand, GameDriver

# Wait this long (instead of the full tick interval) after a tick whose
# observation flagged something time-sensitive (e.g. VRChat chat-bubble text
# that just changed) — short-lived chat bubbles disappear well before a
# typical multi-second tick_seconds would notice a follow-up message.
_FAST_POLL_SECONDS = 1.5

# Verbs that need a subject (item/block) in their args.
_NAME_VERBS = {
    "mine", "collect", "gather", "bring", "store", "deposit", "find_in_chests",
    "withdraw", "drop", "craft", "place", "place_at", "smelt", "cook", "equip",
    "plant", "plant_tree",
}
# Map everyday words in a goal to a concrete Minecraft name the bridge can find.
_SUBJECT_ALIASES = {
    "wood": "oak_log", "wooden": "oak_log", "logs": "log", "log": "log", "timber": "log",
    "plank": "planks", "stick": "stick", "cobble": "cobblestone", "cobblestone": "cobblestone",
    "stone": "stone", "diamond": "diamond", "iron": "iron", "gold": "gold",
    "coal": "coal", "redstone": "redstone", "copper": "copper", "lapis": "lapis",
    "emerald": "emerald", "dirt": "dirt", "sand": "sand", "gravel": "gravel",
    "wheat": "wheat", "carrot": "carrot", "potato": "potato", "food": "beef",
    "wool": "wool", "glass": "glass", "water": "water", "bucket": "bucket",
    "pickaxe": "pickaxe", "axe": "axe", "sword": "sword", "shovel": "shovel",
    "armor": "armor", "torch": "torch", "bed": "bed",
}


def _infer_subject(goal: str) -> str | None:
    g = f" {(goal or '').lower()} "
    for word, mapped in _SUBJECT_ALIASES.items():
        if f"{word}" in g:
            return mapped
    return None


_MOVE_INTENTS = {
    "walk", "move", "explore", "wander", "goto", "come", "follow", "mine",
    "collect", "gather", "hunt", "go_home", "forward", "press",
}
_TALK_INTENTS = {"say", "chat", "startconversation", "tell"}


def _coerce_verb(verb: str, args: dict[str, Any], verbs: list[str]) -> tuple[str, dict[str, Any]]:
    """Map a requested verb onto one the active driver supports.

    Stops "unknown verb" errors when a Minecraft-trained model asks for verbs the
    universal/VRChat/etc. driver doesn't have.
    """
    if verb and verb in verbs:
        return verb, args
    vset = set(verbs)
    if verb in _TALK_INTENTS and "say" in vset:
        return "say", args
    if verb in _MOVE_INTENTS or not verb:
        for cand in ("walk", "explore", "wander", "move_mouse", "forward"):
            if cand in vset:
                return cand, ({"seconds": 2} if cand in ("walk", "wander", "explore") else args)
    for cand in ("wait", "look", "say"):
        if cand in vset:
            return cand, {}
    return (verbs[0] if verbs else "wait"), {}


def _extract_command(reply: str) -> dict[str, Any] | None:
    """Best-effort parse of the model's JSON action (tolerant of fences/prose)."""
    if not reply:
        return None
    text = reply.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip().strip("`").strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start:i + 1]
                for attempt in (blob, blob.replace("'", '"')):
                    try:
                        data = json.loads(attempt)
                        if isinstance(data, dict):
                            return data
                    except Exception:
                        pass
                break
    return None


# andy-4 (Mindcraft) emits !command("arg", n) syntax instead of our JSON. Map the
# common Mindcraft commands to our verbs so its actions actually run.
_MINDCRAFT_RE = re.compile(r"!([a-zA-Z]+)\s*(?:\(([^)]*)\))?")


def _split_cmd_args(raw: str) -> list[str]:
    out = []
    for part in (raw or "").split(","):
        p = part.strip().strip('"').strip("'").strip()
        if p != "":
            out.append(p)
    return out


def _extract_mindcraft(reply: str) -> dict[str, Any] | None:
    """Translate a Mindcraft-style !command(...) into our {verb,args}."""
    m = _MINDCRAFT_RE.search(reply or "")
    if not m:
        return None
    name = m.group(1).lower()
    a = _split_cmd_args(m.group(2) or "")
    thought = (reply[: m.start()].strip() or reply.strip())[:160]

    def cmd(verb, args=None):
        return {"thought": thought, "verb": verb, "args": args or {}}

    if name in ("followplayer",):
        return cmd("follow", {"player": a[0]} if a else {})
    if name in ("gotoplayer", "goto_player", "comehere", "come"):
        return cmd("come", {"player": a[0]} if a else {})
    if name in ("giveplayer", "givetoplayer", "give", "tossto", "dropto"):
        # !givePlayer("player", "item", count)
        out = {}
        if a:
            out["player"] = a[0]
            if len(a) > 1:
                out["name"] = a[1]
            if len(a) > 2 and a[2].isdigit():
                out["count"] = int(a[2])
        return cmd("bring", out)
    if name in ("searchforblock", "collectblock", "collectblocks", "minepblock", "mineblock", "collect"):
        out = {}
        if a:
            out["name"] = a[0]
            if len(a) > 1 and a[1].isdigit() and int(a[1]) > 1:
                return {"thought": thought, "verb": "gather", "args": {"name": a[0], "count": int(a[1])}}
        return cmd("mine", out)
    if name in ("setmode", "mode", "setgoal", "goal"):
        # Mindcraft mode toggles (only meaningful when turned ON). Combat/eat are
        # automatic here, so map combat modes to a defend sweep and otherwise
        # no-op so the bot doesn't spin re-issuing them.
        on = not (len(a) > 1 and str(a[1]).lower() in ("false", "0", "off", "no"))
        mode = (a[0].lower() if a else "")
        if on and ("defen" in mode or "hunt" in mode or "combat" in mode or "fight" in mode):
            return cmd("defend", {"seconds": 4})
        return cmd("wait")
    if name in ("searchforentity", "huntentity"):
        return cmd("hunt", {"animal": a[0]} if a else {})
    if name in ("attack", "attackplayer", "attackentity", "defend"):
        return cmd("attack", {"target": a[0]} if a else {})
    if name in ("placeblock", "placehere"):
        return cmd("place", {"name": a[0]} if a else {})
    if name in ("craftrecipe", "craft", "craftitem"):
        return cmd("craft", {"name": a[0], "count": int(a[1])} if len(a) > 1 and a[1].isdigit() else ({"name": a[0]} if a else {}))
    if name in ("equip",):
        return cmd("equip", {"name": a[0]} if a else {})
    if name in ("eat", "consume"):
        return cmd("eat")
    if name in ("smeltitem", "smelt"):
        return cmd("smelt", {"input": a[0]} if a else {})
    if name in ("cook",):
        return cmd("cook", {"food": a[0]} if a else {})
    if name in ("activate", "useitem", "fish", "fishing"):
        return cmd("fish")
    if name in ("findvillage", "findvillager", "findvillagers"):
        return cmd("find_village")
    if name in ("trade", "tradewith"):
        return cmd("trade", {"item": a[0]} if a else {})
    if name in ("gotocoordinate", "gotoxz", "navigateto"):
        if len(a) >= 2:
            try:
                return cmd("goto", {"x": int(float(a[0])), "z": int(float(a[-1]))})
            except ValueError:
                pass
        return cmd("explore")
    if name in ("nearbyblocks", "stats", "inventory", "entities", "lookaround", "viewchest"):
        return cmd("look")
    if name in ("movearound", "moveaway", "explore", "newaction", "wander"):
        return cmd("explore")
    if name in ("startconversation", "sendmessage", "tell", "whisper", "msg"):
        # First arg is the target player, the rest is the message.
        text = ", ".join(a[1:]) if len(a) > 1 else (thought or (a[0] if a else ""))
        return cmd("say", {"text": text})
    if name in ("say", "chat", "endconversation", "stfu"):
        return cmd("say", {"text": (", ".join(a) if a else thought)})
    if name in ("sleep", "rest"):
        return cmd("sleep")
    if name in ("stop", "stay"):
        return cmd("stop")
    # Unknown !command — at least surface the thought and keep moving.
    return cmd("wander", {"seconds": 2})


class GameAgent:
    def __init__(
        self,
        driver: GameDriver,
        config: Config,
        profile_getter: Callable[[], dict[str, Any]],
        narrate: Callable[[str, str], None],
        on_update: Callable[[dict[str, Any]], None] | None = None,
        remember: Callable[[str], None] | None = None,
        tick_seconds: float = 4.0,
        goal: str = "explore and survive",
    ) -> None:
        self.driver = driver
        self.config = config
        self.profile_getter = profile_getter
        self.narrate = narrate
        self.on_update = on_update or (lambda _state: None)
        self.remember = remember or (lambda _text: None)
        self.tick_seconds = max(1.0, tick_seconds)
        self.goal = goal

        self._stop = threading.Event()
        self._wake = threading.Event()  # fire a tick immediately (e.g. new order)
        self._thread: threading.Thread | None = None
        self._log: list[dict[str, str]] = []  # short rolling game history
        self._system_prompt_cache: str | None = None  # built once per session

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="NekoSuneAIGameAgent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        # Abort any in-flight action immediately (e.g. a long pathfinder move):
        # stopping the driver makes the current observe/act call fail fast so the
        # loop unwinds instead of blocking until the action finishes.
        try:
            self.driver.stop()
        except Exception:
            pass

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def set_goal(self, goal: str) -> None:
        self.goal = goal.strip() or self.goal
        self._wake.set()  # act on the new order right away

    def _game_system_prompt(self) -> str:
        """Compact system prompt for the game, built once and cached.

        Deliberately omits the full companion persona (personality sliders,
        memory, boundaries, etc.) — the game only needs identity, mission, the
        verb list, and the JSON format, so the prompt stays small and fast.
        """
        if self._system_prompt_cache is not None:
            return self._system_prompt_cache

        def _driver_text(method: str) -> str:
            if hasattr(self.driver, method):
                try:
                    return self.driver.__getattribute__(method)() or ""
                except Exception:
                    return ""
            return ""

        profile = self.profile_getter() or {}
        name = profile.get("companion_name", "NekoSuneAI")
        verbs = self.driver.available_verbs()
        mission = _driver_text("mission")
        verbs_help = _driver_text("verbs_help")
        prompt = (
            f"You are {name}, autonomously playing {self.driver.name}. "
            "Reply with ONLY one JSON object: "
            '{"thought":"<short in-character line>","verb":"<one verb>","args":{...}}. '
            "No prose, no markdown."
            + (f"\n{mission}" if mission else "")
            + f"\nVerbs: {', '.join(verbs)}."
            + (f"\n{verbs_help}" if verbs_help else "")
        )
        self._system_prompt_cache = prompt
        return prompt

    # ── loop ──────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            self.driver.start()
        except Exception as exc:
            self.narrate(f"I couldn't start the game: {exc}", "anxious")
            return
        self.narrate(f"Alright, let's play. Goal: {self.goal}.", "happy")

        while not self._stop.is_set():
            fast_poll = False
            try:
                fast_poll = self._tick()
            except Exception as exc:
                self.narrate(f"Something went wrong: {exc}", "anxious")
            # Wait for the next tick, but wake instantly on a new order / stop.
            # After a time-sensitive observation (e.g. a chat bubble just changed),
            # poll again sooner instead of waiting the full interval.
            wait_seconds = min(self.tick_seconds, _FAST_POLL_SECONDS) if fast_poll else self.tick_seconds
            self._wake.wait(wait_seconds)
            self._wake.clear()

        try:
            self.driver.stop()
        except Exception:
            pass
        self.narrate("Okay, I'm done playing for now.", "neutral")

    def _tick(self) -> bool:
        """Runs one observe-decide-act cycle. Returns True when the driver's
        observation flagged something time-sensitive (e.g. VRChat chat-bubble
        text that just changed) — the caller polls again sooner instead of
        waiting the full tick interval, so short-lived chat bubbles aren't
        missed."""
        if self._stop.is_set():
            return False
        obs = self.driver.observe()
        try:
            self.on_update(obs.raw)
        except Exception:
            pass
        if self._stop.is_set():
            return False
        fast_poll = bool(obs.raw.get("scene_changed"))

        # The system prompt (identity + mission + verbs + format) never changes
        # during a session, so build it ONCE and reuse it. This replaces the full
        # companion persona prompt (sliders/memory/etc.), which the game doesn't
        # need — a much smaller prompt = far faster responses on local models.
        system_prompt = self._game_system_prompt()
        verbs = self.driver.available_verbs()
        user_prompt = (
            f"Goal: {self.goal}\n\nWorld state:\n{obs.text}\n\nYour next single action (JSON only):"
        )

        thinking_timer = start_thinking_sound(self.config)
        try:
            result = generate_reply(
                GenerationRequest(
                    user_text=user_prompt,
                    profile=self.profile_getter(),
                    config=self.config,
                    source="game",
                    system_override=system_prompt,
                    use_shared_history=False,
                    history=list(self._log),
                    # Game replies are short JSON; cap tokens so local models
                    # (Ollama) respond fast and don't time out each tick.
                    max_tokens=200,
                )
            )
        finally:
            stop_thinking_sound(thinking_timer)

        if self._stop.is_set():
            return False

        # Prefer our JSON; if the model used Mindcraft !command syntax, translate it.
        command = _extract_command(result.reply) or _extract_mindcraft(result.reply)
        thought = str(command.get("thought", "")).strip() if command else ""
        verb = str(command.get("verb", "")).strip().lower() if command else ""
        args = (command.get("args") if command and isinstance(command.get("args"), dict) else {})

        if thought:
            self.narrate(thought, detect_emotion(thought))
            self.remember(f"While playing {self.driver.name}: {thought}")
        elif command is None:
            # Model didn't give a usable action — show a snippet so it's visible.
            snippet = result.reply.strip().replace("\n", " ")[:160]
            if snippet:
                self.narrate(snippet, result.emotion)

        # Map the requested verb onto one this driver actually supports (so a
        # Minecraft-trained model's verbs work in VRChat/universal/etc.).
        if not verb or verb not in verbs:
            verb, args = _coerce_verb(verb, args, verbs)

        # If a subject-needing verb came with no item/block, infer it from the
        # goal so "I need wood" -> mine {name: oak_log} instead of failing.
        if verb in _NAME_VERBS and not any(
            args.get(k) for k in ("name", "item", "block", "seed", "sapling", "input")
        ):
            subject = _infer_subject(self.goal)
            if subject:
                args = {**args, "name": subject}

        outcome = self.driver.act(GameCommand(verb=verb, args=args))
        outcome_text = str(outcome.get("message", outcome))
        # Surface failures so the user can see why nothing's happening.
        if isinstance(outcome, dict) and outcome.get("ok") is False:
            self.narrate(f"({verb}: {outcome_text})", "anxious")

        self._log.append({"role": "assistant", "content": thought or f"{verb} {args}"})
        self._log.append({"role": "user", "content": f"Result: {outcome_text}"})
        if len(self._log) > 12:
            self._log = self._log[-12:]
        return fast_poll
