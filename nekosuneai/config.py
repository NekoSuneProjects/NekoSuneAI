from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from dotenv import load_dotenv

from .performance import (
    choose_performance_profile,
    describe_system_capabilities,
    detect_system_capabilities,
    normalize_auto_tune_goal,
)


def parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return int(value)


def parse_optional_str_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_input_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"voice", "mic", "microphone", "handsfree", "hands-free"}:
        return "voice"
    return "text"


def normalize_stt_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"bridge", "remote", "nekoai-bridge"}:
        return "bridge"
    if normalized in {"google", "web"}:
        return "google"
    if normalized in {"vosk", "local-lite", "local_light", "pi"}:
        return "vosk"
    return "faster-whisper"


def normalize_llm_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {
        "claude",
        "claude-code",
        "claudecode",
        "claude-cli",
        "claude_code",
        "anthropic-cli",
    }:
        return "claude-code"
    if normalized in {"codex", "codex-cli", "codex_cli", "openai-codex"}:
        return "codex"
    if normalized in {"cli", "custom-cli", "command", "shell"}:
        return "cli"
    if normalized in {
        "openai",
        "chatgpt",
        "openai-compatible",
        "openai_compatible",
        "custom",
        "custom-openai",
        "openrouter",
        "open-router",
        "lmstudio",
        "lm-studio",
        "lm studio",
        "litellm",
    }:
        return "openai"
    return "ollama"


def resolve_model_label(
    provider: str,
    explicit_model: str | None,
    ollama_default: str,
    cli_model: str | None,
) -> str:
    if provider in {"claude-code", "codex", "cli"}:
        defaults = {
            "claude-code": "Claude Code (CLI)",
            "codex": "Codex (CLI)",
            "cli": "Custom CLI",
        }
        return cli_model or defaults.get(provider, provider)
    return explicit_model or ollama_default


def normalize_web_safesearch(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"off", "none", "disabled"}:
        return "off"
    if normalized in {"strict", "high"}:
        return "strict"
    return "moderate"


def normalize_web_search_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"duckduckgo", "duckduckgo-search", "ddg", "ddgs"}:
        return "duckduckgo"
    if normalized in {"searxng", "searx", "searx-ng"}:
        return "searxng"
    if normalized in {"gateway", "search-gateway", "openai-search"}:
        return "gateway"
    return "searxng"


def normalize_music_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"youtube", "youtube-music", "youtube_music", "yt", "ytmusic"}:
        return "youtube"
    if normalized in {"soundcloud", "sc"}:
        return "soundcloud"
    if normalized in {"deezer"}:
        return "deezer"
    if normalized in {"spotify"}:
        return "spotify"
    return "soundcloud"


def _normalize_singing_backend(value: str) -> str:
    v = (value or "").strip().lower()
    if v in {"local", "xtts", "gtts"}:
        return "local"
    if v == "rvc":
        return "rvc"
    return "cloud"


def normalize_tts_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"bridge", "remote", "nekoai-bridge"}:
        return "bridge"
    if normalized in {"gtts", "google-tts", "google_tts", "google"}:
        return "gtts"
    return "xtts"


def normalize_audio_output(value: str | None) -> str:
    """Where NekoSuneAI's audio (voice, singing, music) plays: always the
    server 'speaker' (the browser overlay output option was removed with the
    avatar bridge)."""
    return "speaker"


def normalize_rag_embedding_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"ollama", "ollama-embed", "ollama_embeddings"}:
        return "ollama"
    if normalized in {"openai", "openai-compatible", "api", "remote"}:
        return "openai"
    return "local"


def resolve_llm_api_url(provider: str, raw_url: str | None) -> str:
    if provider == "openai":
        candidate = (raw_url or "https://api.openai.com/v1/chat/completions").strip()
        parsed = urlparse(candidate)
        path = parsed.path.rstrip("/")
        if not path:
            return candidate.rstrip("/") + "/v1/chat/completions"
        if path == "/v1":
            return candidate.rstrip("/") + "/chat/completions"
        if path.endswith("/chat/completions"):
            return candidate
        return candidate

    candidate = (raw_url or "http://127.0.0.1:11434/api/chat").strip()
    parsed = urlparse(candidate)
    path = parsed.path.rstrip("/")
    if not path:
        return candidate.rstrip("/") + "/api/chat"
    if path == "/api":
        return candidate.rstrip("/") + "/chat"
    return candidate


def resolve_web_search_url(provider: str, raw_url: str | None) -> str:
    if provider == "searxng":
        candidate = (raw_url or "https://searxng.nekosunevr.co.uk/").strip()
        parsed = urlparse(candidate)
        path = parsed.path.rstrip("/")
        if not path:
            return candidate.rstrip("/") + "/search"
        if path.endswith("/search"):
            return candidate
        return candidate
    if provider == "gateway":
        candidate = (raw_url or "").strip().rstrip("/")
        if not candidate:
            return ""
        if candidate.endswith("/v1/search"):
            return candidate
        return candidate + "/v1/search"
    return (raw_url or "").strip()


def resolve_soundcloud_stream_endpoint(raw_url: str | None) -> str:
    candidate = (raw_url or "https://dl.nekosunevr.co.uk/api/stream").strip()
    parsed = urlparse(candidate)
    path = parsed.path.rstrip("/")
    if not path:
        return candidate.rstrip("/") + "/api/stream"
    return candidate


def parse_input_mode(argument: str) -> str | None:
    normalized = argument.strip().lower()
    if normalized in {"voice", "mic", "microphone", "handsfree", "hands-free"}:
        return "voice"
    if normalized in {"text", "typing", "keyboard"}:
        return "text"
    return None


@dataclass
class Config:
    auto_tune_performance: bool
    auto_tune_goal: str
    performance_profile: str
    performance_notes: tuple[str, ...]
    system_summary: str
    llm_provider: str
    model: str
    llm_api_url: str
    llm_api_key: str | None
    llm_keep_alive: str
    llm_num_predict: int
    llm_num_ctx: int
    llm_cli_command: str | None
    claude_cli_path: str | None
    codex_cli_path: str | None
    cli_model: str | None
    tts_provider: str
    audio_output: str
    tts_language: str
    tts_auto_language: bool
    xtts_model_name: str
    xtts_speaker: str
    xtts_speaker_wav: str | None
    xtts_use_gpu: bool
    xtts_stream_output: bool
    xtts_stream_chunk_size: int
    xtts_stream_buffer_seconds: float
    xtts_chunk_max_chars: int
    xtts_max_text_chars: int
    xtts_speed: float
    history_turns: int
    temperature: float
    request_timeout: int
    web_browsing_enabled: bool
    web_auto_search: bool
    web_search_provider: str
    web_search_url: str
    web_max_results: int
    web_timeout_seconds: int
    web_region: str
    web_safesearch: str
    web_search_gateway_provider: str
    web_search_api_key: str | None
    music_provider_default: str
    soundcloud_stream_endpoint: str
    voice_enabled: bool
    input_mode: str
    stt_provider: str
    stt_use_gpu: bool
    stt_model: str
    vosk_model_path: str
    stt_compute_type: str
    stt_beam_size: int
    stt_best_of: int
    stt_vad_filter: bool
    stt_language: str
    stt_timeout_seconds: float
    stt_phrase_time_limit_seconds: float
    stt_pause_threshold_seconds: float
    stt_non_speaking_duration_seconds: float
    stt_ambient_duration_seconds: float
    stt_energy_threshold: int
    stt_dynamic_energy_threshold: bool
    mic_device_index: int | None
    speaker_device_index: int | None
    mic_sample_rate: int | None
    mic_chunk_size: int
    mic_input_channels: int
    mic_channel_index: int
    rag_enabled: bool
    rag_embedding_provider: str
    rag_embedding_model: str
    rag_top_k: int
    rag_min_score: float
    game_enabled: bool
    game_tick_seconds: float
    singing_enabled: bool
    singing_backend: str
    singing_fetch_instrumental: bool
    rvc_model_path: str | None
    singing_api_url: str | None
    singing_api_key: str | None
    rvc_chat_enabled: bool
    rvc_chat_model_path: str | None
    rvc_chat_pitch: float
    rvc_chat_index_rate: float
    rvc_chat_protect: float
    thinking_sound_enabled: bool
    thinking_sound_path: str | None
    thinking_sound_delay_seconds: float
    vision_model: str | None
    vrchat_osc_host: str
    vrchat_osc_port: int
    vrchat_osc_read_port: int
    vrchat_log_dir: str | None
    vrchat_friends_enabled: bool
    vrchat_username: str | None
    vrchat_password: str | None
    vrchat_totp_secret: str | None
    mcp_enabled: bool
    mcp_servers_json: str
    mcp_timeout_seconds: float
    mcp_auto_route: bool
    warning_sound_path: str | None
    danger_sound_path: str | None
    bridge_ws_url: str | None
    bridge_auth_token: str | None
    bridge_user_id: str
    bridge_tts_voice: str | None
    emergency_broadcast_tts: bool
    monitor_tts_enabled: bool
    bridge_tts_engine: str
    bridge_tts_rate: str
    bridge_stt_timeout_seconds: float
    bluetooth_reconnect_enabled: bool
    bluetooth_speaker_address: str | None
    bluetooth_reconnect_interval_seconds: float
    wake_word_enabled: bool
    wake_word_model: str
    wake_word_framework: str
    wake_word_threshold: float
    wake_word_confirmation_frames: int
    wake_word_cooldown_seconds: float
    wake_word_sound_enabled: bool
    wake_word_sound_path: str | None
    home_assistant_mqtt_host: str | None
    home_assistant_mqtt_port: int
    home_assistant_mqtt_username: str | None
    home_assistant_mqtt_password: str | None

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        pause_threshold_ms = int(os.getenv("STT_END_SILENCE_TIMEOUT_MS", "900"))
        legacy_xtts_max_chars = max(80, int(os.getenv("XTTS_MAX_CHARS", "240")))
        xtts_chunk_max_chars = max(
            80,
            min(
                240,
                int(
                    os.getenv(
                        "XTTS_CHUNK_MAX_CHARS",
                        str(min(240, legacy_xtts_max_chars)),
                    )
                ),
            ),
        )
        xtts_max_text_chars = max(
            xtts_chunk_max_chars,
            int(
                os.getenv(
                    "XTTS_MAX_TEXT_CHARS",
                    str(legacy_xtts_max_chars if legacy_xtts_max_chars > 240 else 5000),
                )
            ),
        )
        auto_tune_performance = parse_bool_env("AUTO_TUNE_PERFORMANCE", True)
        auto_tune_goal = normalize_auto_tune_goal(os.getenv("AUTO_TUNE_GOAL", "balanced"))
        capabilities = detect_system_capabilities()
        performance_profile = (
            choose_performance_profile(capabilities, auto_tune_goal)
            if auto_tune_performance
            else None
        )

        xtts_use_gpu = (
            performance_profile.xtts_use_gpu
            if performance_profile is not None
            else parse_bool_env("XTTS_USE_GPU", True)
        )
        llm_num_predict = (
            performance_profile.ollama_num_predict
            if performance_profile is not None
            else max(48, int(os.getenv("OLLAMA_NUM_PREDICT", "1200")))
        )
        llm_num_ctx = max(0, int(os.getenv("OLLAMA_NUM_CTX", os.getenv("LLM_NUM_CTX", "0"))))
        xtts_stream_chunk_size = (
            performance_profile.xtts_stream_chunk_size
            if performance_profile is not None
            else max(10, int(os.getenv("XTTS_STREAM_CHUNK_SIZE", "20")))
        )
        xtts_stream_buffer_seconds = (
            performance_profile.xtts_stream_buffer_seconds
            if performance_profile is not None
            else max(0.0, float(os.getenv("XTTS_STREAM_BUFFER_SECONDS", "1.8")))
        )
        performance_notes = (
            tuple(performance_profile.notes) if performance_profile is not None else ()
        )
        return cls(
            auto_tune_performance=auto_tune_performance,
            auto_tune_goal=auto_tune_goal,
            performance_profile=(performance_profile.name if performance_profile else "manual"),
            performance_notes=performance_notes,
            system_summary=describe_system_capabilities(capabilities),
            llm_provider=normalize_llm_provider(os.getenv("LLM_PROVIDER", "ollama")),
            model=resolve_model_label(
                normalize_llm_provider(os.getenv("LLM_PROVIDER", "ollama")),
                parse_optional_str_env("LLM_MODEL"),
                os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
                parse_optional_str_env("CLI_MODEL"),
            ),
            llm_api_url=resolve_llm_api_url(
                normalize_llm_provider(os.getenv("LLM_PROVIDER", "ollama")),
                parse_optional_str_env("LLM_API_URL"),
            ),
            llm_api_key=parse_optional_str_env("LLM_API_KEY"),
            llm_keep_alive=os.getenv("LLM_KEEP_ALIVE", "10m"),
            llm_num_predict=llm_num_predict,
            llm_num_ctx=llm_num_ctx,
            llm_cli_command=parse_optional_str_env("LLM_CLI_COMMAND"),
            claude_cli_path=parse_optional_str_env("CLAUDE_CLI_PATH"),
            codex_cli_path=parse_optional_str_env("CODEX_CLI_PATH"),
            cli_model=parse_optional_str_env("CLI_MODEL"),
            tts_provider=normalize_tts_provider(os.getenv("TTS_PROVIDER", "xtts")),
            audio_output=normalize_audio_output(os.getenv("AUDIO_OUTPUT", "speaker")),
            tts_language=os.getenv("TTS_LANGUAGE", "en"),
            tts_auto_language=parse_bool_env("TTS_AUTO_LANGUAGE", True),
            xtts_model_name=os.getenv("XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2"),
            xtts_speaker=os.getenv("XTTS_SPEAKER", "Ana Florence"),
            xtts_speaker_wav=parse_optional_str_env("XTTS_SPEAKER_WAV"),
            xtts_use_gpu=xtts_use_gpu,
            xtts_stream_output=parse_bool_env("XTTS_STREAM_OUTPUT", True),
            xtts_stream_chunk_size=xtts_stream_chunk_size,
            xtts_stream_buffer_seconds=xtts_stream_buffer_seconds,
            xtts_chunk_max_chars=xtts_chunk_max_chars,
            xtts_max_text_chars=xtts_max_text_chars,
            xtts_speed=max(0.5, min(2.0, float(os.getenv("XTTS_SPEED", "1.0")))),
            history_turns=max(1, int(os.getenv("HISTORY_TURNS", "10"))),
            temperature=float(os.getenv("TEMPERATURE", "0.95")),
            request_timeout=max(5, int(os.getenv("REQUEST_TIMEOUT", "180"))),
            web_browsing_enabled=parse_bool_env("WEB_BROWSING_ENABLED", True),
            web_auto_search=parse_bool_env("WEB_AUTO_SEARCH", True),
            web_search_provider=normalize_web_search_provider(os.getenv("WEB_SEARCH_PROVIDER", "searxng")),
            web_search_url=resolve_web_search_url(
                normalize_web_search_provider(os.getenv("WEB_SEARCH_PROVIDER", "searxng")),
                parse_optional_str_env("WEB_SEARCH_URL"),
            ),
            web_max_results=max(1, min(10, int(os.getenv("WEB_MAX_RESULTS", "5")))),
            web_timeout_seconds=max(2, int(os.getenv("WEB_TIMEOUT_SECONDS", "15"))),
            web_region=os.getenv("WEB_REGION", "us-en"),
            web_safesearch=normalize_web_safesearch(os.getenv("WEB_SAFESEARCH", "moderate")),
            web_search_gateway_provider=os.getenv("WEB_SEARCH_GATEWAY_PROVIDER", "searxng-search"),
            web_search_api_key=parse_optional_str_env("WEB_SEARCH_API_KEY"),
            music_provider_default=normalize_music_provider(os.getenv("MUSIC_PROVIDER_DEFAULT", "soundcloud")),
            soundcloud_stream_endpoint=resolve_soundcloud_stream_endpoint(parse_optional_str_env("SOUNDCLOUD_STREAM_ENDPOINT")),
            voice_enabled=parse_bool_env("VOICE_ENABLED", True),
            input_mode=normalize_input_mode(os.getenv("INPUT_MODE", "text")),
            stt_provider=normalize_stt_provider(os.getenv("STT_PROVIDER", "faster-whisper")),
            stt_use_gpu=parse_bool_env("STT_USE_GPU", True),
            stt_model=os.getenv("STT_MODEL", "base.en"),
            vosk_model_path=os.getenv("VOSK_MODEL_PATH", "/app/models/vosk-model-small-en-us-0.15"),
            stt_compute_type=os.getenv("STT_COMPUTE_TYPE", "auto"),
            stt_beam_size=max(1, int(os.getenv("STT_BEAM_SIZE", "5"))),
            stt_best_of=max(1, int(os.getenv("STT_BEST_OF", "5"))),
            stt_vad_filter=parse_bool_env("STT_VAD_FILTER", True),
            stt_language=os.getenv("STT_LANGUAGE", "en"),
            stt_timeout_seconds=max(0.5, float(os.getenv("STT_TIMEOUT_SECONDS", "5"))),
            stt_phrase_time_limit_seconds=max(1.0, float(os.getenv("STT_PHRASE_TIME_LIMIT_SECONDS", "30"))),
            stt_pause_threshold_seconds=max(0.2, pause_threshold_ms / 1000.0),
            stt_non_speaking_duration_seconds=max(0.1, float(os.getenv("STT_NON_SPEAKING_DURATION_SECONDS", "0.5"))),
            stt_ambient_duration_seconds=max(0.0, float(os.getenv("STT_AMBIENT_DURATION_SECONDS", "0.6"))),
            stt_energy_threshold=max(1, int(os.getenv("STT_ENERGY_THRESHOLD", "300"))),
            stt_dynamic_energy_threshold=parse_bool_env("STT_DYNAMIC_ENERGY_THRESHOLD", True),
            mic_device_index=parse_optional_int_env("MIC_DEVICE_INDEX"),
            speaker_device_index=parse_optional_int_env("SPEAKER_DEVICE_INDEX"),
            mic_sample_rate=parse_optional_int_env("MIC_SAMPLE_RATE"),
            mic_chunk_size=max(256, int(os.getenv("MIC_CHUNK_SIZE", "1024"))),
            mic_input_channels=max(1, int(os.getenv("MIC_INPUT_CHANNELS", "1"))),
            mic_channel_index=max(0, int(os.getenv("MIC_CHANNEL_INDEX", "0"))),
            rag_enabled=parse_bool_env("RAG_ENABLED", True),
            rag_embedding_provider=normalize_rag_embedding_provider(os.getenv("RAG_EMBEDDING_PROVIDER", "local")),
            rag_embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            rag_top_k=max(1, int(os.getenv("RAG_TOP_K", "5"))),
            rag_min_score=float(os.getenv("RAG_MIN_SCORE", "0.2")),
            game_enabled=parse_bool_env("GAME_ENABLED", True),
            game_tick_seconds=max(1.0, float(os.getenv("GAME_TICK_SECONDS", "4"))),
            singing_enabled=parse_bool_env("SINGING_ENABLED", True),
            singing_backend=_normalize_singing_backend(os.getenv("SINGING_BACKEND", "local")),
            singing_fetch_instrumental=parse_bool_env("SINGING_FETCH_INSTRUMENTAL", True),
            rvc_model_path=parse_optional_str_env("RVC_MODEL_PATH"),
            singing_api_url=parse_optional_str_env("SINGING_API_URL"),
            singing_api_key=parse_optional_str_env("SINGING_API_KEY"),
            rvc_chat_enabled=parse_bool_env("RVC_CHAT_ENABLED", False),
            rvc_chat_model_path=parse_optional_str_env("RVC_CHAT_MODEL_PATH"),
            rvc_chat_pitch=float(os.getenv("RVC_CHAT_PITCH", "0")),
            rvc_chat_index_rate=max(0.0, min(1.0, float(os.getenv("RVC_CHAT_INDEX_RATE", "0.75")))),
            rvc_chat_protect=max(0.0, min(0.5, float(os.getenv("RVC_CHAT_PROTECT", "0.33")))),
            thinking_sound_enabled=parse_bool_env("THINKING_SOUND_ENABLED", True),
            thinking_sound_path=parse_optional_str_env("THINKING_SOUND_PATH"),
            thinking_sound_delay_seconds=max(0.0, float(os.getenv("THINKING_SOUND_DELAY_SECONDS", "2.5"))),
            vision_model=parse_optional_str_env("VISION_MODEL"),
            vrchat_osc_host=os.getenv("VRCHAT_OSC_HOST", "127.0.0.1"),
            vrchat_osc_port=int(os.getenv("VRCHAT_OSC_PORT", "9000")),
            vrchat_osc_read_port=int(os.getenv("VRCHAT_OSC_READ_PORT", "9001")),
            vrchat_log_dir=parse_optional_str_env("VRCHAT_LOG_DIR"),
            vrchat_friends_enabled=parse_bool_env("VRCHAT_FRIENDS_ENABLED", False),
            vrchat_username=parse_optional_str_env("VRCHAT_USERNAME"),
            vrchat_password=parse_optional_str_env("VRCHAT_PASSWORD"),
            vrchat_totp_secret=parse_optional_str_env("VRCHAT_TOTP_SECRET"),
            mcp_enabled=parse_bool_env("MCP_ENABLED", True),
            mcp_servers_json=os.getenv("MCP_SERVERS_JSON", "[]"),
            mcp_timeout_seconds=max(1.0, float(os.getenv("MCP_TIMEOUT_SECONDS", "30"))),
            mcp_auto_route=parse_bool_env("MCP_AUTO_ROUTE", True),
            warning_sound_path=parse_optional_str_env("WARNING_SOUND_PATH"),
            danger_sound_path=parse_optional_str_env("DANGER_SOUND_PATH"),
            bridge_ws_url=parse_optional_str_env("BRIDGE_WS_URL"),
            bridge_auth_token=parse_optional_str_env("BRIDGE_AUTH_TOKEN"),
            bridge_user_id=os.getenv("BRIDGE_USER_ID", "nekosuneai").strip() or "nekosuneai",
            bridge_tts_voice=parse_optional_str_env("BRIDGE_TTS_VOICE"),
            emergency_broadcast_tts=parse_bool_env("EMERGENCY_BROADCAST_TTS", True),
            monitor_tts_enabled=parse_bool_env("MONITOR_TTS_ENABLED", True),
            bridge_tts_engine=os.getenv("BRIDGE_TTS_ENGINE", "edge-stream").strip().lower() or "edge-stream",
            bridge_tts_rate=os.getenv("BRIDGE_TTS_RATE", "+10%").strip() or "+10%",
            bridge_stt_timeout_seconds=max(15.0, float(os.getenv("BRIDGE_STT_TIMEOUT_SECONDS", "90"))),
            bluetooth_reconnect_enabled=parse_bool_env("BLUETOOTH_RECONNECT_ENABLED", True),
            bluetooth_speaker_address=parse_optional_str_env("BLUETOOTH_SPEAKER_ADDRESS"),
            bluetooth_reconnect_interval_seconds=max(5.0, float(os.getenv("BLUETOOTH_RECONNECT_INTERVAL_SECONDS", "20"))),
            wake_word_enabled=parse_bool_env("WAKE_WORD_ENABLED", False),
            wake_word_model=os.getenv("WAKE_WORD_MODEL", "hey_jarvis"),
            wake_word_framework=os.getenv("WAKE_WORD_FRAMEWORK", "onnx"),
            wake_word_threshold=float(os.getenv("WAKE_WORD_THRESHOLD", "0.55")),
            wake_word_confirmation_frames=max(1, int(os.getenv("WAKE_WORD_CONFIRMATION_FRAMES", "2"))),
            wake_word_cooldown_seconds=max(0.0, float(os.getenv("WAKE_WORD_COOLDOWN_SECONDS", "2"))),
            wake_word_sound_enabled=parse_bool_env("WAKE_WORD_SOUND_ENABLED", True),
            wake_word_sound_path=parse_optional_str_env("WAKE_WORD_SOUND_PATH"),
            home_assistant_mqtt_host=parse_optional_str_env("HOME_ASSISTANT_MQTT_HOST"),
            home_assistant_mqtt_port=int(os.getenv("HOME_ASSISTANT_MQTT_PORT", "1883")),
            home_assistant_mqtt_username=parse_optional_str_env("HOME_ASSISTANT_MQTT_USERNAME"),
            home_assistant_mqtt_password=parse_optional_str_env("HOME_ASSISTANT_MQTT_PASSWORD"),
        )
