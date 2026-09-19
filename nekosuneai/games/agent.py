"""The game-agnostic control loop.

One tick is: observe the world through the driver, ask the LLM for a short
in-character thought plus a single high-level command as JSON, speak the
thought so it lands in chat and TTS, run the command, then feed the outcome
back in as context for the next tick.

The loop owns a daemon thread and swallows its own exceptions, so a
misbehaving driver or model degrades into narration rather than taking the
application down with it.
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

# After a tick whose observation was time-sensitive - a VRChat chat bubble that
# just changed, say - poll again this soon instead of waiting out the full tick
# interval. Bubbles routinely vanish before a multi-second tick would see a reply.
_FAST_POLL_SECONDS = 1.5

# Rolling context handed back to the model, in messages.
_MAX_LOG_MESSAGES = 12

# Game replies are short JSON, so cap generation: local models answer quickly
# and a slow one cannot stall the tick.
_GAME_REPLY_MAX_TOKENS = 200

# Verbs that are meaningless without a subject in their args.
_NAME_VERBS = {
    "mine", "collect", "gather", "bring", "store", "deposit", "find_in_chests",
    "withdraw", "drop", "craft", "place", "place_at", "smelt", "cook", "equip",
    "plant", "plant_tree",
}

# Arg keys any of which counts as "the subject is already specified".
_SUBJECT_ARG_KEYS = ("name", "item", "block", "seed", "sapling", "input")

# Everyday words mapped to a concrete name the bridge can look up. Scanned in
# order, so the more specific spellings must come before the looser ones
# ("logs" before "log", since both match the text "logs").
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
    """Guess what the goal is talking about, so "I need wood" can become oak_log."""
    haystack = f" {(goal or '').lower()} "
    for word, mapped in _SUBJECT_ALIASES.items():
        if word in haystack:
            return mapped
    return None


# --------------------------------------------------------------------------
# Verb coercion
# --------------------------------------------------------------------------

_MOVE_INTENTS = {
    "walk", "move", "explore", "wander", "goto", "come", "follow", "mine",
    "collect", "gather", "hunt", "go_home", "forward", "press",
}
_TALK_INTENTS = {"say", "chat", "startconversation", "tell"}

# Movement verbs to try, best first, when the asked-for verb is unavailable.
_MOVE_FALLBACKS = ("walk", "explore", "wander", "move_mouse", "forward")
# Those among them that take a duration rather than the original args.
_TIMED_MOVES = ("walk", "wander", "explore")
# Last-resort verbs when nothing else matches.
_INERT_FALLBACKS = ("wait", "look", "say")

_DEFAULT_VERB = "wait"


def _coerce_verb(
    verb: str, args: dict[str, Any], verbs: list[str]
) -> tuple[str, dict[str, Any]]:
    """Map a requested verb onto one the active driver supports.

    Stops "unknown verb" errors when a Minecraft-trained model asks for verbs the
    universal/VRChat/etc. driver doesn't have.
    """
    if verb and verb in verbs:
        return verb, args

    available = set(verbs)

    if verb in _TALK_INTENTS and "say" in available:
        return "say", args

    if verb in _MOVE_INTENTS or not verb:
        for candidate in _MOVE_FALLBACKS:
            if candidate in available:
                replacement = {"seconds": 2} if candidate in _TIMED_MOVES else args
                return candidate, replacement

    for candidate in _INERT_FALLBACKS:
        if candidate in available:
            return candidate, {}

    return (verbs[0] if verbs else _DEFAULT_VERB), {}


# --------------------------------------------------------------------------
# Parsing the model's action
# --------------------------------------------------------------------------

_FENCE_PREFIX = re.compile(r"^```(?:json)?")


def _first_json_object(text: str) -> str | None:
    """Slice out the first brace-balanced object, ignoring any prose around it."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for index in range(start, len(text)):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _extract_command(reply: str) -> dict[str, Any] | None:
    """Best-effort parse of the model's JSON action (tolerant of fences/prose)."""
    if not reply:
        return None

    text = _FENCE_PREFIX.sub("", reply.strip()).strip().strip("`").strip()
    blob = _first_json_object(text)
    if blob is None:
        return None

    # Retry with single quotes swapped out; small models emit Python-ish dicts.
    for attempt in (blob, blob.replace("'", '"')):
        try:
            parsed = json.loads(attempt)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# --------------------------------------------------------------------------
# Mindcraft (!command) translation
# --------------------------------------------------------------------------

# andy-4 and friends emit !command("arg", n) rather than our JSON, so the common
# Mindcraft vocabulary is mapped onto our verbs below.
_MINDCRAFT_RE = re.compile(r"!([a-zA-Z]+)\s*(?:\(([^)]*)\))?")

_THOUGHT_MAX_CHARS = 160
_FALSEY_WORDS = ("false", "0", "off", "no")
_COMBAT_MODE_HINTS = ("defen", "hunt", "combat", "fight")

# A handler receives the parsed argument list plus the thought text, and returns
# the verb to run and its args.
Handler = Callable[[list[str], str], "tuple[str, dict[str, Any]]"]


def _split_cmd_args(raw: str) -> list[str]:
    parts = []
    for part in (raw or "").split(","):
        cleaned = part.strip().strip('"').strip("'").strip()
        if cleaned != "":
            parts.append(cleaned)
    return parts


def _first_or_empty(args: list[str], key: str) -> dict[str, Any]:
    return {key: args[0]} if args else {}


def _h_follow(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "follow", _first_or_empty(a, "player")


def _h_come(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "come", _first_or_empty(a, "player")


def _h_give(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    # !givePlayer("player", "item", count)
    out: dict[str, Any] = {}
    if a:
        out["player"] = a[0]
        if len(a) > 1:
            out["name"] = a[1]
        if len(a) > 2 and a[2].isdigit():
            out["count"] = int(a[2])
    return "bring", out


def _h_collect(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    if not a:
        return "mine", {}
    # A count above one means a gathering run rather than a single break.
    if len(a) > 1 and a[1].isdigit() and int(a[1]) > 1:
        return "gather", {"name": a[0], "count": int(a[1])}
    return "mine", {"name": a[0]}


def _h_mode(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    # Mindcraft mode toggles only mean anything when switched on. Combat and
    # eating are automatic here, so a combat mode becomes one defend sweep and
    # everything else no-ops rather than having the bot re-issue it forever.
    enabled = not (len(a) > 1 and str(a[1]).lower() in _FALSEY_WORDS)
    mode = a[0].lower() if a else ""
    if enabled and any(hint in mode for hint in _COMBAT_MODE_HINTS):
        return "defend", {"seconds": 4}
    return "wait", {}


def _h_hunt(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "hunt", _first_or_empty(a, "animal")


def _h_attack(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "attack", _first_or_empty(a, "target")


def _h_place(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "place", _first_or_empty(a, "name")


def _h_craft(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    if len(a) > 1 and a[1].isdigit():
        return "craft", {"name": a[0], "count": int(a[1])}
    return "craft", _first_or_empty(a, "name")


def _h_equip(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "equip", _first_or_empty(a, "name")


def _h_eat(_a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "eat", {}


def _h_smelt(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "smelt", _first_or_empty(a, "input")


def _h_cook(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "cook", _first_or_empty(a, "food")


def _h_fish(_a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "fish", {}


def _h_find_village(_a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "find_village", {}


def _h_trade(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "trade", _first_or_empty(a, "item")


def _h_goto(a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    if len(a) >= 2:
        try:
            return "goto", {"x": int(float(a[0])), "z": int(float(a[-1]))}
        except ValueError:
            pass
    return "explore", {}


def _h_look(_a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "look", {}


def _h_explore(_a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "explore", {}


def _h_tell(a: list[str], thought: str) -> tuple[str, dict[str, Any]]:
    # The first argument names the target player; everything after is the message.
    text = ", ".join(a[1:]) if len(a) > 1 else (thought or (a[0] if a else ""))
    return "say", {"text": text}


def _h_say(a: list[str], thought: str) -> tuple[str, dict[str, Any]]:
    return "say", {"text": (", ".join(a) if a else thought)}


def _h_sleep(_a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "sleep", {}


def _h_stop(_a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    return "stop", {}


_HANDLER_GROUPS: tuple[tuple[tuple[str, ...], Handler], ...] = (
    (("followplayer",), _h_follow),
    (("gotoplayer", "goto_player", "comehere", "come"), _h_come),
    (("giveplayer", "givetoplayer", "give", "tossto", "dropto"), _h_give),
    (
        ("searchforblock", "collectblock", "collectblocks", "minepblock",
         "mineblock", "collect"),
        _h_collect,
    ),
    (("setmode", "mode", "setgoal", "goal"), _h_mode),
    (("searchforentity", "huntentity"), _h_hunt),
    (("attack", "attackplayer", "attackentity", "defend"), _h_attack),
    (("placeblock", "placehere"), _h_place),
    (("craftrecipe", "craft", "craftitem"), _h_craft),
    (("equip",), _h_equip),
    (("eat", "consume"), _h_eat),
    (("smeltitem", "smelt"), _h_smelt),
    (("cook",), _h_cook),
    (("activate", "useitem", "fish", "fishing"), _h_fish),
    (("findvillage", "findvillager", "findvillagers"), _h_find_village),
    (("trade", "tradewith"), _h_trade),
    (("gotocoordinate", "gotoxz", "navigateto"), _h_goto),
    (
        ("nearbyblocks", "stats", "inventory", "entities", "lookaround", "viewchest"),
        _h_look,
    ),
    (("movearound", "moveaway", "explore", "newaction", "wander"), _h_explore),
    (("startconversation", "sendmessage", "tell", "whisper", "msg"), _h_tell),
    (("say", "chat", "endconversation", "stfu"), _h_say),
    (("sleep", "rest"), _h_sleep),
    (("stop", "stay"), _h_stop),
)

_MINDCRAFT_HANDLERS: dict[str, Handler] = {
    name: handler for names, handler in _HANDLER_GROUPS for name in names
}


def _h_unknown(_a: list[str], _t: str) -> tuple[str, dict[str, Any]]:
    """Unrecognised !command: surface the thought and keep the bot moving."""
    return "wander", {"seconds": 2}


def _extract_mindcraft(reply: str) -> dict[str, Any] | None:
    """Translate a Mindcraft-style !command(...) into our {verb,args}."""
    match = _MINDCRAFT_RE.search(reply or "")
    if not match:
        return None

    name = match.group(1).lower()
    args = _split_cmd_args(match.group(2) or "")
    thought = (reply[: match.start()].strip() or reply.strip())[:_THOUGHT_MAX_CHARS]

    verb, verb_args = _MINDCRAFT_HANDLERS.get(name, _h_unknown)(args, thought)
    return {"thought": thought, "verb": verb, "args": verb_args}


# --------------------------------------------------------------------------
# The agent
# --------------------------------------------------------------------------


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

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="NekoSuneAIGameAgent", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        # Stopping the driver aborts whatever is in flight - a long pathfinder
        # move, say - so the current observe/act call fails fast and the loop
        # unwinds instead of blocking until that action finishes on its own.
        self._safe_driver_stop()

    def _safe_driver_stop(self) -> None:
        try:
            self.driver.stop()
        except Exception:
            pass

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def set_goal(self, goal: str) -> None:
        self.goal = goal.strip() or self.goal
        self._wake.set()  # act on the new order right away

    # -- prompt -------------------------------------------------------------

    def _driver_text(self, method: str) -> str:
        """Read an optional descriptive hook off the driver, if it has one."""
        if not hasattr(self.driver, method):
            return ""
        try:
            return getattr(self.driver, method)() or ""
        except Exception:
            return ""

    def _game_system_prompt(self) -> str:
        """Compact system prompt for the game, built once and cached.

        Deliberately omits the full companion persona - sliders, memory,
        boundaries and the rest. The game only needs an identity, the mission,
        the verb list and the output format, which keeps the prompt small and
        the model fast.
        """
        if self._system_prompt_cache is not None:
            return self._system_prompt_cache

        profile = self.profile_getter() or {}
        name = profile.get("companion_name", "NekoSuneAI")
        verbs = self.driver.available_verbs()
        mission = self._driver_text("mission")
        verbs_help = self._driver_text("verbs_help")

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

    # -- loop ---------------------------------------------------------------

    def _run(self) -> None:
        try:
            self.driver.start()
        except Exception as exc:
            self.narrate(f"I couldn't start the game: {exc}", "anxious")
            return

        self.narrate(f"Alright, let's play. Goal: {self.goal}.", "happy")

        while not self._stop.is_set():
            try:
                fast_poll = self._tick()
            except Exception as exc:
                self.narrate(f"Something went wrong: {exc}", "anxious")
                fast_poll = False

            # Sleep until the next tick, but wake at once on a new order or stop.
            # A time-sensitive observation shortens the wait.
            delay = (
                min(self.tick_seconds, _FAST_POLL_SECONDS)
                if fast_poll
                else self.tick_seconds
            )
            self._wake.wait(delay)
            self._wake.clear()

        self._safe_driver_stop()
        self.narrate("Okay, I'm done playing for now.", "neutral")

    def _ask_model(self, system_prompt: str, user_prompt: str):
        """One generation call, with the thinking sound bracketing it."""
        thinking_timer = start_thinking_sound(self.config)
        try:
            return generate_reply(
                GenerationRequest(
                    user_text=user_prompt,
                    profile=self.profile_getter(),
                    config=self.config,
                    source="game",
                    system_override=system_prompt,
                    use_shared_history=False,
                    history=list(self._log),
                    max_tokens=_GAME_REPLY_MAX_TOKENS,
                )
            )
        finally:
            stop_thinking_sound(thinking_timer)

    @staticmethod
    def _read_command(reply: str) -> tuple[dict[str, Any] | None, str, str, dict[str, Any]]:
        """Prefer our JSON; fall back to translating Mindcraft !command syntax."""
        command = _extract_command(reply) or _extract_mindcraft(reply)
        if command is None:
            return None, "", "", {}

        raw_args = command.get("args")
        return (
            command,
            str(command.get("thought", "")).strip(),
            str(command.get("verb", "")).strip().lower(),
            raw_args if isinstance(raw_args, dict) else {},
        )

    def _fill_missing_subject(
        self, verb: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Infer the subject from the goal when a subject-taking verb lacks one."""
        if verb not in _NAME_VERBS:
            return args
        if any(args.get(key) for key in _SUBJECT_ARG_KEYS):
            return args

        subject = _infer_subject(self.goal)
        return {**args, "name": subject} if subject else args

    def _record(self, thought: str, verb: str, args: dict[str, Any], outcome_text: str) -> None:
        self._log.append(
            {"role": "assistant", "content": thought or f"{verb} {args}"}
        )
        self._log.append({"role": "user", "content": f"Result: {outcome_text}"})
        if len(self._log) > _MAX_LOG_MESSAGES:
            self._log = self._log[-_MAX_LOG_MESSAGES:]

    def _tick(self) -> bool:
        """Run one observe-decide-act cycle.

        Returns True when the observation was time-sensitive - VRChat chat-bubble
        text that just changed, for instance - so the caller polls again sooner
        and short-lived bubbles are not missed.
        """
        if self._stop.is_set():
            return False

        observation = self.driver.observe()
        try:
            self.on_update(observation.raw)
        except Exception:
            pass
        if self._stop.is_set():
            return False

        fast_poll = bool(observation.raw.get("scene_changed"))

        verbs = self.driver.available_verbs()
        user_prompt = (
            f"Goal: {self.goal}\n\nWorld state:\n{observation.text}\n\n"
            "Your next single action (JSON only):"
        )
        result = self._ask_model(self._game_system_prompt(), user_prompt)

        if self._stop.is_set():
            return False

        command, thought, verb, args = self._read_command(result.reply)

        if thought:
            self.narrate(thought, detect_emotion(thought))
            self.remember(f"While playing {self.driver.name}: {thought}")
        elif command is None:
            # No usable action came back, so show a snippet rather than nothing.
            snippet = result.reply.strip().replace("\n", " ")[:_THOUGHT_MAX_CHARS]
            if snippet:
                self.narrate(snippet, result.emotion)

        # Map onto a verb this driver really supports, so a Minecraft-trained
        # model still does something sensible in VRChat or the universal driver.
        if not verb or verb not in verbs:
            verb, args = _coerce_verb(verb, args, verbs)
        args = self._fill_missing_subject(verb, args)

        outcome = self.driver.act(GameCommand(verb=verb, args=args))
        outcome_text = str(outcome.get("message", outcome))

        # Surface failures so the user can see why nothing is happening.
        if isinstance(outcome, dict) and outcome.get("ok") is False:
            self.narrate(f"({verb}: {outcome_text})", "anxious")

        self._record(thought, verb, args, outcome_text)
        return fast_poll
