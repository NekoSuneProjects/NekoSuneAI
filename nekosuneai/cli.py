"""The terminal front end.

Runs the read-dispatch-reply loop: take a turn from the keyboard or the
microphone, route it through the slash-command registry, and otherwise treat it
as conversation - checking for a memory reset, a standing instruction, a media
request or a web lookup before asking the model.

Commands live in a registry rather than one long branch, so ``/help``, the
welcome banner and the dispatcher all stay in step as commands are added.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .audio_input import (
    capture_voice_turn,
    describe_selected_microphone,
    describe_stt_backend,
    print_input_devices,
    recalibrate_microphone,
    resolve_input_device_info,
)
from .config import Config, normalize_tts_provider, parse_input_mode
from .engine import GenerationRequest, generate_reply
from .defaults import VOICE_COMMAND_ALIASES
from .memory import MemoryStore
from .models import CommandResult, SessionState, UserTurn
from .media import handle_media_request
from .sticky import is_reset_command, try_clear_sticky_instruction, try_set_sticky_instruction
from .storage import (
    append_history,
    ensure_runtime_dirs,
    list_profiles,
    load_profile,
    reset_history,
    save_profile,
    set_active_profile,
)
from .tts import (
    describe_tts_voice,
    get_xtts_device,
    list_xtts_speakers,
    play_audio_file,
    play_alert_sound,
    print_xtts_speakers,
    resolve_optional_path,
    should_play_audio_after_synthesis,
    speak_text,
)
from .utils import console_safe_text
from .web_search import (
    extract_web_query_from_request,
    fetch_web_context,
    should_auto_search,
)

_ON_WORDS = {"on", "true", "1", "yes"}
_OFF_WORDS = {"off", "false", "0", "no"}
_TTS_CHOICES = {"xtts", "gtts", "google-tts", "google_tts", "google"}

_COMMAND_SUMMARY = (
    "Commands: /help, /mode <voice|text>, /listen, /ask, /recalibrate, /mics, "
    "/mic <index|default>, /tts [xtts|gtts], /speakers, /speaker <name>, /voice [on|off], "
    "/web [on|off|auto on|auto off|clear|<query>], /play <query>, /music <query>, /pause, /resume, /stop, "
    "/performance, /profiles, /profile, /profile use <id>, "
    "/name <new name>, /me <your name>, "
    "/reset, /exit"
)

# Every command and what it does, in the order /help prints them.
_HELP_LINES = (
    ("/help", "Show commands"),
    ("/mode", "Show the current input mode"),
    ("/mode voice", "Turn on hands-free microphone input"),
    ("/mode text", "Switch back to keyboard input"),
    ("/listen", "Capture one spoken turn right now"),
    ("/ask", "Alias for /listen"),
    ("/recalibrate", "Relearn the room noise before listening"),
    ("/mics", "List available microphone devices"),
    ("/mic", "Show the selected microphone"),
    ("/mic <index>", "Choose a microphone from /mics"),
    ("/mic default", "Use the system default microphone"),
    ("/tts", "Show the current TTS provider"),
    ("/tts xtts", "Use XTTS-v2 voice synthesis (default)"),
    ("/tts gtts", "Use Google gTTS voice synthesis"),
    ("/speakers", "List available XTTS built-in voices (XTTS mode)"),
    ("/speaker", "Show the current XTTS voice (XTTS mode)"),
    ("/speaker <name>", "Switch XTTS built-in voice (XTTS mode)"),
    ("/voice", "Toggle spoken replies on or off"),
    ("/voice on", "Always speak replies"),
    ("/voice off", "Stop speaking replies"),
    ("/web", "Show web browsing status"),
    ("/web on", "Enable web browsing"),
    ("/web off", "Disable web browsing"),
    ("/web auto on", "Auto-search for likely web/current-event prompts"),
    ("/web auto off", "Disable auto web search"),
    ("/web clear", "Clear queued web context"),
    ("/web <query>", "Search now and use results on the next reply"),
    ("/play <query>", "Search and play music on the preferred platform"),
    ("/music <query>", "Search the default music platform"),
    ("/pause", "Pause current media playback"),
    ("/resume", "Resume paused media playback"),
    ("/stop", "Stop current media playback"),
    ("/performance", "Show the auto-tuned performance profile"),
    ("/profiles", "List saved profiles"),
    ("/profile", "Show the current saved profile"),
    ("/profile use <id>", "Switch to a different saved profile"),
    ("/name <new name>", "Rename your companion"),
    ("/me <your name>", "Set your name"),
    ("/reset", "Clear conversation history"),
    ("/exit", "Quit the app"),
)
_HELP_COLUMN_WIDTH = 24


def _on_off(flag: bool) -> str:
    return "on" if flag else "off"


# --------------------------------------------------------------------------
# Status output
# --------------------------------------------------------------------------


def print_welcome(profile: dict[str, Any], config: Config, state: SessionState) -> None:
    print()
    print(f"{profile['companion_name']} is ready.")
    print(
        f"Provider: {config.llm_provider} | Model: {config.model} | Input: {state.input_mode} | "
        f"Voice output: {_on_off(state.voice_enabled)}"
    )
    print(
        f"TTS provider: {config.tts_provider} | TTS language: {config.tts_language} | "
        f"Speech recognition: {describe_stt_backend(config)} | "
        f"Language: {config.stt_language}"
    )

    if config.tts_provider == "xtts":
        print(
            f"XTTS voice: {describe_tts_voice(config)} | XTTS device: {get_xtts_device(config)}"
        )
        print(
            f"XTTS streaming: {_on_off(config.xtts_stream_output)} "
            f"(buffer {config.xtts_stream_buffer_seconds:.1f}s) | "
            f"Reply limit: {config.llm_num_predict} tokens"
        )
    else:
        print(
            f"gTTS voice: {describe_tts_voice(config)} | "
            f"Reply limit: {config.llm_num_predict} tokens"
        )

    print(
        f"Web browsing: {_on_off(config.web_browsing_enabled)} | "
        f"Auto-search: {_on_off(config.web_auto_search)} | "
        f"Provider: {config.web_search_provider} | "
        f"Max results: {config.web_max_results}"
    )
    print(
        f"Media region: {config.media_region} | "
        f"Default music: {config.music_provider_default}"
    )
    if config.music_provider_default == "soundcloud":
        print(f"SoundCloud stream endpoint: {config.soundcloud_stream_endpoint}")

    print(
        f"Performance: {config.performance_profile} | "
        f"Auto-tune: {_on_off(config.auto_tune_performance)} "
        f"({config.auto_tune_goal})"
    )
    print(f"Hardware: {config.system_summary}")
    print(f"Microphone: {describe_selected_microphone(config)}")
    print(
        "Hands-free mode listens after each reply. Text mode keeps the keyboard prompt."
    )
    print(_COMMAND_SUMMARY)
    print()


def print_help() -> None:
    print()
    for name, description in _HELP_LINES:
        print(f"{name.ljust(_HELP_COLUMN_WIDTH)}{description}")
    print()
    print("Say the companion's name + a standing rule (e.g. \"NekoSuneAI, always")
    print("speak to me in 0s and 1s\") to make it stick until you say \"stop\".")
    print("Say \"reset\" or \"clear\" to cancel that AND wipe long-term memory.")
    print()


def print_performance_summary(config: Config) -> None:
    print()
    print(f"Performance profile: {config.performance_profile}")
    print(
        f"Auto-tune: {_on_off(config.auto_tune_performance)} "
        f"({config.auto_tune_goal})"
    )
    print(f"Hardware: {config.system_summary}")
    print(
        f"Active settings: provider {config.llm_provider} | reply limit {config.llm_num_predict} | "
        f"STT {describe_stt_backend(config)} | "
        f"TTS {config.tts_provider}"
    )
    if config.tts_provider == "xtts":
        print(f"XTTS device: {get_xtts_device(config)} at speed {config.xtts_speed:.2f}")
    for note in config.performance_notes:
        print(f"- {note}")
    print()


def print_web_status(config: Config, state: SessionState) -> None:
    print(
        "Web browsing: "
        f"{_on_off(config.web_browsing_enabled)} | "
        f"Auto-search: {_on_off(config.web_auto_search)} | "
        f"Provider: {config.web_search_provider} | "
        f"Max results: {config.web_max_results} | "
        f"Timeout: {config.web_timeout_seconds}s | "
        f"Region: {config.web_region} | "
        f"SafeSearch: {config.web_safesearch}"
    )
    if config.web_search_provider == "searxng":
        print(f"SearXNG URL: {config.web_search_url}")

    queued_query = state.pending_web_query or "none"
    queued_status = "yes" if state.pending_web_context else "no"
    print(f"Queued web query: {queued_query} | Queued context ready: {queued_status}")


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def parse_voice_setting(argument: str) -> bool | None:
    normalized = argument.strip().lower()
    if normalized in _ON_WORDS:
        return True
    if normalized in _OFF_WORDS:
        return False
    return None


def parse_tts_provider(argument: str) -> str | None:
    normalized = argument.strip().lower()
    if normalized in _TTS_CHOICES:
        return normalize_tts_provider(normalized)
    return None


def map_spoken_command(text: str) -> str:
    normalized = " ".join(text.strip().lower().split())
    return VOICE_COMMAND_ALIASES.get(normalized, text)


# --------------------------------------------------------------------------
# Multi-part command handlers
# --------------------------------------------------------------------------


def handle_web_command(command: str, config: Config, state: SessionState) -> None:
    if command.strip().lower() == "/web":
        print_web_status(config, state)
        return

    argument = command[4:].strip()
    if not argument:
        print_web_status(config, state)
        return

    lowered_argument = argument.lower()

    if lowered_argument in {"on", "off"}:
        config.web_browsing_enabled = lowered_argument == "on"
        if not config.web_browsing_enabled:
            state.pending_web_context = None
            state.pending_web_query = None
        print(f"Web browsing is now {_on_off(config.web_browsing_enabled)}.")
        return

    if lowered_argument in {"clear", "reset"}:
        state.pending_web_context = None
        state.pending_web_query = None
        print("Cleared queued web context.")
        return

    if lowered_argument == "auto":
        print(f"Web auto-search is {_on_off(config.web_auto_search)}.")
        return

    if lowered_argument.startswith("auto "):
        setting = parse_voice_setting(argument[5:])
        if setting is None:
            print("Use /web auto on or /web auto off.")
            return
        config.web_auto_search = setting
        print(f"Web auto-search is now {_on_off(config.web_auto_search)}.")
        return

    if not config.web_browsing_enabled:
        print("Web browsing is off. Run /web on first.")
        return

    # Anything else is treated as a search to run right now.
    bundle = fetch_web_context(argument, config)
    state.pending_web_query = bundle.query
    state.pending_web_context = bundle.context
    print(
        f"Queued {bundle.result_count} web results for the next reply "
        f"(query: {bundle.query})."
    )


def _forget_recognizer(state: SessionState) -> None:
    """Drop the cached recogniser so the next listen rebuilds it."""
    state.speech_recognizer = None
    state.speech_recognizer_signature = None
    state.mic_calibrated = False


def handle_microphone_command(
    command: str,
    config: Config,
    state: SessionState,
) -> None:
    if command.lower() == "/mic":
        print(f"Microphone is currently {describe_selected_microphone(config)}.")
        return

    selection = command[5:].strip()
    if not selection:
        print("Use /mic <index> or /mic default.")
        return

    if selection.lower() == "default":
        config.mic_device_index = None
        _forget_recognizer(state)
        print(f"Microphone is now {describe_selected_microphone(config)}.")
        return

    try:
        device_index = int(selection)
        device_info = resolve_input_device_info(device_index)
    except ValueError:
        print("Use /mic <index> or /mic default.")
        return
    except RuntimeError as exc:
        print(exc)
        return

    config.mic_device_index = device_index
    _forget_recognizer(state)
    print(f"Microphone is now #{device_info['index']} ({device_info['name']}).")


def handle_speaker_command(
    command: str,
    config: Config,
    state: SessionState,
) -> None:
    if config.tts_provider != "xtts":
        print("XTTS speaker controls are only available when /tts xtts is active.")
        return

    if command.lower() == "/speaker":
        print(console_safe_text(f"XTTS voice is currently {describe_tts_voice(config)}."))
        return

    selection = command[9:].strip()
    if not selection:
        print("Use /speaker <name>.")
        return

    if resolve_optional_path(config.xtts_speaker_wav) is not None:
        print(
            "XTTS is currently using XTTS_SPEAKER_WAV. "
            "Clear that setting to use built-in speakers."
        )
        return

    selected_speaker = next(
        (
            speaker
            for speaker in list_xtts_speakers(config, state)
            if speaker.lower() == selection.lower()
        ),
        None,
    )
    if selected_speaker is None:
        print("That XTTS speaker was not found. Run /speakers to list valid names.")
        return

    config.xtts_speaker = selected_speaker
    print(console_safe_text(f"XTTS voice is now {selected_speaker}."))


# --------------------------------------------------------------------------
# Command registry
# --------------------------------------------------------------------------


@dataclass
class _Ctx:
    """What a command handler is given: the raw text plus the session."""

    command: str
    argument: str
    profile: dict[str, Any]
    state: SessionState
    config: Config


Handler = Callable[[_Ctx], CommandResult]


def _done() -> CommandResult:
    return CommandResult(handled=True)


def _cmd_help(_ctx: _Ctx) -> CommandResult:
    print_help()
    return _done()


def _cmd_show_mode(ctx: _Ctx) -> CommandResult:
    print(f"Input mode is {ctx.state.input_mode}.")
    return _done()


def _cmd_set_mode(ctx: _Ctx) -> CommandResult:
    new_mode = parse_input_mode(ctx.argument)
    if new_mode is None:
        print("Use /mode voice or /mode text.")
        return _done()
    ctx.state.input_mode = new_mode
    print(f"Input mode is now {new_mode}.")
    return _done()


def _cmd_listen(ctx: _Ctx) -> CommandResult:
    voice_turn = capture_voice_turn(ctx.config, ctx.profile, ctx.state)
    return CommandResult(handled=True, injected_turn=voice_turn)


def _cmd_recalibrate(ctx: _Ctx) -> CommandResult:
    _forget_recognizer(ctx.state)
    recalibrate_microphone(ctx.config, ctx.state)
    return _done()


def _cmd_list_mics(_ctx: _Ctx) -> CommandResult:
    try:
        print_input_devices()
    except RuntimeError as exc:
        print(exc)
    return _done()


def _cmd_mic(ctx: _Ctx) -> CommandResult:
    handle_microphone_command(ctx.command, ctx.config, ctx.state)
    return _done()


def _cmd_show_tts(ctx: _Ctx) -> CommandResult:
    print(f"TTS provider is currently {ctx.config.tts_provider}.")
    return _done()


def _cmd_set_tts(ctx: _Ctx) -> CommandResult:
    selected_provider = parse_tts_provider(ctx.argument)
    if selected_provider is None:
        print("Use /tts xtts or /tts gtts.")
        return _done()

    ctx.config.tts_provider = selected_provider
    print(f"TTS provider is now {ctx.config.tts_provider}.")
    if ctx.config.tts_provider == "gtts":
        print("gTTS selected. XTTS speaker commands are disabled.")
    return _done()


def _cmd_list_speakers(ctx: _Ctx) -> CommandResult:
    if ctx.config.tts_provider != "xtts":
        print("XTTS speakers are only available when /tts xtts is active.")
        return _done()
    try:
        print_xtts_speakers(ctx.config, ctx.state)
    except RuntimeError as exc:
        print(exc)
    return _done()


def _cmd_speaker(ctx: _Ctx) -> CommandResult:
    try:
        handle_speaker_command(ctx.command, ctx.config, ctx.state)
    except RuntimeError as exc:
        print(exc)
    return _done()


def _cmd_toggle_voice(ctx: _Ctx) -> CommandResult:
    ctx.state.voice_enabled = not ctx.state.voice_enabled
    print(f"Voice output is now {_on_off(ctx.state.voice_enabled)}.")
    return _done()


def _cmd_set_voice(ctx: _Ctx) -> CommandResult:
    setting = parse_voice_setting(ctx.argument)
    if setting is None:
        print("Use /voice, /voice on, or /voice off.")
        return _done()
    ctx.state.voice_enabled = setting
    print(f"Voice output is now {_on_off(ctx.state.voice_enabled)}.")
    return _done()


def _cmd_web(ctx: _Ctx) -> CommandResult:
    try:
        handle_web_command(ctx.command, ctx.config, ctx.state)
    except RuntimeError as exc:
        print(f"[Web] {exc}")
    return _done()


def _play_query(ctx: _Ctx) -> CommandResult:
    action = handle_media_request(f"play {ctx.argument}", ctx.profile, ctx.config)
    if action.handled:
        save_profile(ctx.profile)
        print(action.response)
    return _done()


def _cmd_transport(ctx: _Ctx) -> CommandResult:
    """/pause, /resume and /stop all map straight onto a media verb."""
    action = handle_media_request(
        ctx.command.strip().lower()[1:], ctx.profile, ctx.config
    )
    if action.handled:
        print(action.response)
    return _done()


def _cmd_show_profile(ctx: _Ctx) -> CommandResult:
    print()
    print(json.dumps(ctx.profile, indent=2, ensure_ascii=False))
    print()
    return _done()


def _cmd_use_profile(ctx: _Ctx) -> CommandResult:
    target_profile_id = ctx.argument
    if not target_profile_id:
        print("Use /profile use <profile_id>.")
        return _done()

    try:
        active_profile = set_active_profile(target_profile_id)
    except RuntimeError as exc:
        print(exc)
        return _done()

    # Mutate in place: the same dict is held by the caller's loop.
    ctx.profile.clear()
    ctx.profile.update(active_profile)
    print(f"Active profile is now {ctx.profile.get('profile_name', target_profile_id)}.")
    return _done()


def _cmd_list_profiles(_ctx: _Ctx) -> CommandResult:
    print()
    print("Saved profiles:")
    for summary in list_profiles():
        suffix = " (active)" if summary["is_active"] else ""
        print(
            f"- {summary['profile_id']}: {summary['profile_name']} "
            f"[{summary['companion_name']}]"
            f"{suffix}"
        )
    print()
    return _done()


def _cmd_performance(ctx: _Ctx) -> CommandResult:
    print_performance_summary(ctx.config)
    return _done()


def _cmd_reset(_ctx: _Ctx) -> CommandResult:
    reset_history()
    print("Conversation history cleared.")
    return _done()


def _cmd_exit(_ctx: _Ctx) -> CommandResult:
    return CommandResult(handled=True, should_exit=True)


def _cmd_rename_companion(ctx: _Ctx) -> CommandResult:
    if ctx.argument:
        ctx.profile["companion_name"] = ctx.argument
        save_profile(ctx.profile)
        print(f"Your companion is now named {ctx.argument}.")
    return _done()


def _cmd_rename_user(ctx: _Ctx) -> CommandResult:
    if ctx.argument:
        ctx.profile["user_name"] = ctx.argument
        save_profile(ctx.profile)
        print(f"Saved your name as {ctx.argument}.")
    return _done()


# Commands matched on the whole line, lowercased.
_EXACT_COMMANDS: dict[str, Handler] = {
    "/help": _cmd_help,
    "/mode": _cmd_show_mode,
    "/listen": _cmd_listen,
    "/ask": _cmd_listen,
    "/voiceask": _cmd_listen,
    "/recalibrate": _cmd_recalibrate,
    "/mics": _cmd_list_mics,
    "/mic": _cmd_mic,
    "/tts": _cmd_show_tts,
    "/speakers": _cmd_list_speakers,
    "/speaker": _cmd_speaker,
    "/voice": _cmd_toggle_voice,
    "/web": _cmd_web,
    "/pause": _cmd_transport,
    "/resume": _cmd_transport,
    "/stop": _cmd_transport,
    "/profile": _cmd_show_profile,
    "/profiles": _cmd_list_profiles,
    "/performance": _cmd_performance,
    "/perf": _cmd_performance,
    "/reset": _cmd_reset,
    "/exit": _cmd_exit,
}

# Commands that take an argument. Longest prefix wins, so "/profile use " is
# tested before any shorter prefix could shadow it.
_PREFIX_COMMANDS: tuple[tuple[str, Handler], ...] = tuple(
    sorted(
        (
            ("/mode ", _cmd_set_mode),
            ("/mic ", _cmd_mic),
            ("/tts ", _cmd_set_tts),
            ("/speaker ", _cmd_speaker),
            ("/voice ", _cmd_set_voice),
            ("/web ", _cmd_web),
            ("/play ", _play_query),
            ("/music ", _play_query),
            ("/profile use ", _cmd_use_profile),
            ("/name ", _cmd_rename_companion),
            ("/me ", _cmd_rename_user),
        ),
        key=lambda pair: -len(pair[0]),
    )
)


def handle_command(
    incoming_text: str,
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> CommandResult:
    """Run ``incoming_text`` as a slash command, or report it was not one."""
    command = incoming_text.strip()
    lowered = command.lower()

    handler = _EXACT_COMMANDS.get(lowered)
    if handler is not None:
        return handler(_Ctx(command, "", profile, state, config))

    for prefix, prefix_handler in _PREFIX_COMMANDS:
        if lowered.startswith(prefix):
            argument = command[len(prefix):].strip()
            return prefix_handler(_Ctx(command, argument, profile, state, config))

    return CommandResult(handled=False)


# --------------------------------------------------------------------------
# Turn handling
# --------------------------------------------------------------------------


def get_next_user_turn(
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> UserTurn | None:
    if state.input_mode == "voice":
        try:
            return capture_voice_turn(config, profile, state)
        except RuntimeError as exc:
            print()
            print(f"[Mic] {exc}")
            print("[Mic] Switching back to text mode so you can keep chatting.")
            print()
            state.input_mode = "text"
            return None

    try:
        user_text = input(f"{profile['user_name']}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSee you soon.")
        raise SystemExit from None

    return UserTurn(text=user_text, from_voice=False) if user_text else None


def resolve_user_turn(
    turn: UserTurn,
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> tuple[str, bool]:
    """Run commands until something is left to say. Returns (text, should_exit)."""
    current_turn = turn

    while True:
        incoming_text = (
            map_spoken_command(current_turn.text)
            if current_turn.from_voice
            else current_turn.text
        )
        result = handle_command(incoming_text, profile, state, config)

        if result.should_exit:
            return "", True

        # A command such as /listen produces a fresh turn to run in its place.
        if result.injected_turn is not None:
            current_turn = result.injected_turn
            continue

        if result.handled:
            return "", False

        return incoming_text, False


def _say(reply: str, profile: dict[str, Any], state: SessionState, config: Config) -> None:
    """Print + persist + optionally speak a reply. Shared by every reply path
    (media, sticky/reset acknowledgements, and the normal LLM turn) so voice
    output and history logging stay consistent across all of them."""
    print()
    print(console_safe_text(f"{profile['companion_name']}: {reply}"))
    print()

    if not state.voice_enabled:
        return

    audio_path = None
    try:
        audio_path = speak_text(reply, config, state)
        if should_play_audio_after_synthesis(config):
            play_audio_file(audio_path, config.speaker_device_index)
    except Exception as exc:
        latest_path = audio_path or "audio/latest_reply.(wav|mp3)"
        print(
            "[Voice] Voice generation or playback failed. "
            f"The latest audio file is at {latest_path}: {exc}"
        )


def _record_exchange(user_text: str, reply: str) -> None:
    append_history("user", user_text)
    append_history("assistant", reply)


def _handle_standing_instructions(
    user_text: str,
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
    memory_store: MemoryStore,
) -> bool:
    """Deal with reset / set / clear of the sticky instruction.

    Returns True when the turn was fully answered here.
    """
    if is_reset_command(user_text):
        state.sticky_instruction = None
        if config.rag_enabled:
            try:
                memory_store.wipe(profile["profile_id"])
            except Exception as exc:
                print(f"[Memory] Could not wipe memory: {exc}")
        reply = "Memory reset — back to a blank slate."
    elif try_clear_sticky_instruction(user_text):
        state.sticky_instruction = None
        reply = "Cleared — back to normal."
    elif try_set_sticky_instruction(user_text, profile, state):
        reply = "Got it — I'll stick to that until you say stop."
    else:
        return False

    _record_exchange(user_text, reply)
    _say(reply, profile, state, config)
    return True


def _resolve_web_context(
    user_text: str,
    state: SessionState,
    config: Config,
) -> str | None:
    """Queued context if there is some, otherwise a fresh search when warranted."""
    if not config.web_browsing_enabled:
        return None

    web_query = state.pending_web_query

    if state.pending_web_context:
        web_context = state.pending_web_context
        state.pending_web_context = None
        state.pending_web_query = None
        if web_query:
            print(f"[Web] Using queued results for: {web_query}")
        return web_context

    if not web_query:
        inferred_query = extract_web_query_from_request(user_text)
        if inferred_query:
            web_query = inferred_query
            print(f"[Web] Interpreted your request as lookup: {web_query}")

    if not web_query and config.web_auto_search and should_auto_search(user_text):
        web_query = user_text

    if not web_query:
        return None

    web_context = None
    try:
        bundle = fetch_web_context(web_query, config)
    except RuntimeError as exc:
        print(f"[Web] {exc}")
    else:
        web_context = bundle.context
        print(f"[Web] Found {bundle.result_count} results for: {bundle.query}")
    finally:
        state.pending_web_query = None

    return web_context


def main() -> None:
    ensure_runtime_dirs()
    config = Config.from_env()
    profile = load_profile()
    state = SessionState(
        voice_enabled=config.voice_enabled,
        input_mode=config.input_mode,
    )
    memory_store = MemoryStore(config)

    print_welcome(profile, config, state)

    while True:
        try:
            turn = get_next_user_turn(profile, state, config)
        except SystemExit:
            break

        if turn is None:
            continue

        try:
            user_text, should_exit = resolve_user_turn(turn, profile, state, config)
        except RuntimeError as exc:
            print()
            print(f"[Mic] {exc}")
            print("[Mic] Staying in text mode for now.")
            print()
            state.input_mode = "text"
            continue

        if should_exit:
            print("See you soon.")
            break
        if not user_text:
            continue

        if _handle_standing_instructions(
            user_text, profile, state, config, memory_store
        ):
            continue

        try:
            media_action = handle_media_request(user_text, profile, config)
        except RuntimeError as exc:
            print()
            print(f"[Media] {exc}")
            print()
            continue

        if media_action.handled:
            save_profile(profile)
            _record_exchange(user_text, media_action.response)
            print()
            print(
                console_safe_text(
                    f"{profile['companion_name']}: {media_action.response}"
                )
            )
            print()
            continue

        web_context = _resolve_web_context(user_text, state, config)
        extra_system = [state.sticky_instruction] if state.sticky_instruction else None

        try:
            generated = generate_reply(GenerationRequest(
                user_text=user_text, profile=profile, config=config,
                web_context=web_context, extra_system=extra_system or [],
            ))
            reply = generated.reply
            if generated.alert_level != "none":
                play_alert_sound(generated.alert_level, config)
        except RuntimeError as exc:
            print()
            print(f"[Companion error] {exc}")
            print()
            continue

        _record_exchange(user_text, reply)
        _say(reply, profile, state, config)
