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
    if normalized in {"google", "web"}:
        return "google"
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
    return "searxng"


def normalize_media_region(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in {"UK", "GB", "UNITED KINGDOM", "GREAT BRITAIN"}:
        return "GB"
    if normalized in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return "US"
    if normalized in {"AU", "AUSTRALIA"}:
        return "AU"
    if normalized in {"CA", "CANADA"}:
        return "CA"
    if normalized in {"JP", "JAPAN"}:
        return "JP"
    if normalized in {"DE", "GERMANY"}:
        return "DE"
    if normalized in {"FR", "FRANCE"}:
        return "FR"
    return normalized or "GB"


def normalize_music_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"soundcloud", "sc"}:
        return "soundcloud"
    if normalized in {"radio", "internet-radio", "internet_radio"}:
        return "radio"
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
    media_region: str
    music_provider_default: str
    soundcloud_stream_endpoint: str
    voice_enabled: bool
    input_mode: str
    stt_provider: str
    stt_use_gpu: bool
    stt_model: str
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
    # RAG memory
    rag_enabled: bool
    rag_embedding_provider: str
    rag_embedding_model: str
    rag_top_k: int
    rag_min_score: float
    # Game playing (VRChat only)
    game_enabled: bool
    game_tick_seconds: float
    # Singing
    singing_enabled: bool
    singing_backend: str
    singing_fetch_instrumental: bool
    rvc_model_path: str | None
    singing_api_url: str | None
    singing_api_key: str | None
    # Vision
    vision_model: str | None
    vrchat_osc_host: str
    vrchat_osc_port: int
    vrchat_osc_read_port: int
    vrchat_log_dir: str | None

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
                    str(
                        legacy_xtts_max_chars
                        if legacy_xtts_max_chars > 240
                        else 5000
                    ),
                )
            ),
        )
        auto_tune_performance = parse_bool_env("AUTO_TUNE_PERFORMANCE", True)
        auto_tune_goal = normalize_auto_tune_goal(
            os.getenv("AUTO_TUNE_GOAL", "balanced")
        )
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
        # Context window sent to Ollama. 0 = leave it to Ollama's default.
        # Set this (e.g. 4096) when a backend GPU is small: long-context models
        # like dolphin3/llama3.2 advertise a 128K window, and Ollama sizes its
        # memory estimate for the *full* window, which makes it refuse to load
        # on modest GPUs ("requires NN GiB"). Capping num_ctx fixes that.
        llm_num_ctx = max(
            0,
            int(
                os.getenv("OLLAMA_NUM_CTX", os.getenv("LLM_NUM_CTX", "0"))
            ),
        )
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
        # Keep voice pace consistent across machines.
        # Auto-tune should optimize latency and reliability, not alter speaking speed.
        xtts_speed = max(0.8, float(os.getenv("XTTS_SPEED", "1.0")))
        request_timeout = (
            performance_profile.request_timeout
            if performance_profile is not None
            else int(os.getenv("REQUEST_TIMEOUT", "300"))
        )
        stt_use_gpu = (
            performance_profile.stt_use_gpu
            if performance_profile is not None
            else parse_bool_env("STT_USE_GPU", True)
        )
        stt_model = (
            performance_profile.stt_model
            if performance_profile is not None
            else os.getenv("STT_MODEL", "small.en")
        )
        stt_compute_type = (
            performance_profile.stt_compute_type
            if performance_profile is not None
            else os.getenv("STT_COMPUTE_TYPE", "").strip().lower()
        )
        stt_beam_size = (
            performance_profile.stt_beam_size
            if performance_profile is not None
            else max(1, int(os.getenv("STT_BEAM_SIZE", "5")))
        )
        stt_best_of = (
            performance_profile.stt_best_of
            if performance_profile is not None
            else max(1, int(os.getenv("STT_BEST_OF", "5")))
        )
        mic_chunk_size = (
            performance_profile.mic_chunk_size
            if performance_profile is not None
            else int(os.getenv("MIC_CHUNK_SIZE", "1024"))
        )

        llm_provider = normalize_llm_provider(
            os.getenv("LLM_PROVIDER", os.getenv("CHAT_PROVIDER", "ollama"))
        )
        # Pick the right base URL per provider. For Ollama, prefer the local
        # OLLAMA_API_URL so a generic LLM_API_URL (often an OpenAI-compatible proxy
        # like LiteLLM) doesn't hijack local Ollama and cause gateway timeouts.
        if llm_provider == "ollama":
            raw_llm_url = (
                parse_optional_str_env("OLLAMA_API_URL")
                or parse_optional_str_env("LLM_API_URL")
            )
        elif llm_provider == "openai":
            raw_llm_url = (
                parse_optional_str_env("LLM_API_URL")
                or parse_optional_str_env("OPENAI_API_URL")
            )
        else:
            raw_llm_url = None  # CLI providers don't use an HTTP URL
        llm_api_url = resolve_llm_api_url(llm_provider, raw_llm_url)
        web_search_provider = normalize_web_search_provider(
            os.getenv("WEB_SEARCH_PROVIDER", "searxng")
        )
        web_search_url = resolve_web_search_url(
            web_search_provider,
            parse_optional_str_env("WEB_SEARCH_URL")
            or parse_optional_str_env("SEARXNG_URL"),
        )
        media_region = normalize_media_region(
            os.getenv("MEDIA_REGION", "GB")
        )
        music_provider_default = normalize_music_provider(
            os.getenv("MUSIC_PROVIDER_DEFAULT", "soundcloud")
        )
        soundcloud_stream_endpoint = resolve_soundcloud_stream_endpoint(
            parse_optional_str_env("SOUNDCLOUD_STREAM_ENDPOINT")
            or parse_optional_str_env("MEDIA_STREAM_ENDPOINT")
        )
        tts_provider = normalize_tts_provider(os.getenv("TTS_PROVIDER", "xtts"))

        return cls(
            auto_tune_performance=auto_tune_performance,
            auto_tune_goal=auto_tune_goal,
            performance_profile=(
                performance_profile.name if performance_profile is not None else "manual"
            ),
            performance_notes=(
                performance_profile.notes
                if performance_profile is not None
                else (
                    "Auto-tune is off, so manual .env values are in charge.",
                )
            ),
            system_summary=describe_system_capabilities(capabilities),
            llm_provider=llm_provider,
            model=resolve_model_label(
                llm_provider,
                parse_optional_str_env("LLM_MODEL") or parse_optional_str_env("OPENAI_MODEL"),
                os.getenv("OLLAMA_MODEL", "dolphin3"),
                parse_optional_str_env("LLM_CLI_MODEL"),
            ),
            llm_api_url=llm_api_url,
            llm_api_key=(
                parse_optional_str_env("LLM_API_KEY")
                or parse_optional_str_env("OPENAI_API_KEY")
            ),
            llm_keep_alive=(
                parse_optional_str_env("LLM_KEEP_ALIVE")
                or os.getenv("OLLAMA_KEEP_ALIVE", "30m")
            ),
            llm_num_predict=llm_num_predict,
            llm_num_ctx=llm_num_ctx,
            llm_cli_command=parse_optional_str_env("LLM_CLI_COMMAND"),
            claude_cli_path=parse_optional_str_env("CLAUDE_CLI_PATH"),
            codex_cli_path=parse_optional_str_env("CODEX_CLI_PATH"),
            cli_model=parse_optional_str_env("LLM_CLI_MODEL"),
            tts_provider=tts_provider,
            audio_output=normalize_audio_output(
                os.getenv("AUDIO_OUTPUT", os.getenv("TTS_OUTPUT", "speaker"))
            ),
            tts_language=os.getenv("XTTS_LANGUAGE")
            or os.getenv("TTS_LANG")
            or os.getenv("STT_LANGUAGE", "en"),
            tts_auto_language=parse_bool_env("TTS_AUTO_LANGUAGE", False),
            xtts_model_name=os.getenv(
                "XTTS_MODEL_NAME",
                "tts_models/multilingual/multi-dataset/xtts_v2",
            ),
            xtts_speaker=os.getenv("XTTS_SPEAKER", "Ana Florence"),
            xtts_speaker_wav=parse_optional_str_env("XTTS_SPEAKER_WAV"),
            xtts_use_gpu=xtts_use_gpu,
            xtts_stream_output=parse_bool_env("XTTS_STREAM_OUTPUT", True),
            xtts_stream_chunk_size=xtts_stream_chunk_size,
            xtts_stream_buffer_seconds=xtts_stream_buffer_seconds,
            xtts_chunk_max_chars=xtts_chunk_max_chars,
            xtts_max_text_chars=xtts_max_text_chars,
            xtts_speed=xtts_speed,
            history_turns=int(os.getenv("HISTORY_TURNS", "10")),
            temperature=float(
                os.getenv(
                    "LLM_TEMPERATURE",
                    os.getenv("OPENAI_TEMPERATURE", os.getenv("OLLAMA_TEMPERATURE", "0.95")),
                )
            ),
            request_timeout=request_timeout,
            web_browsing_enabled=parse_bool_env("WEB_BROWSING_ENABLED", True),
            web_auto_search=parse_bool_env("WEB_AUTO_SEARCH", False),
            web_search_provider=web_search_provider,
            web_search_url=web_search_url,
            web_max_results=max(1, min(10, int(os.getenv("WEB_MAX_RESULTS", "5")))),
            web_timeout_seconds=max(5, int(os.getenv("WEB_TIMEOUT_SECONDS", "15"))),
            web_region=os.getenv("WEB_REGION", "us-en").strip() or "us-en",
            web_safesearch=normalize_web_safesearch(
                os.getenv("WEB_SAFESEARCH", "moderate")
            ),
            media_region=media_region,
            music_provider_default=music_provider_default,
            soundcloud_stream_endpoint=soundcloud_stream_endpoint,
            voice_enabled=parse_bool_env("VOICE_ENABLED", False),
            input_mode=normalize_input_mode(os.getenv("INPUT_MODE", "voice")),
            stt_provider=normalize_stt_provider(
                os.getenv("STT_PROVIDER", "faster-whisper")
            ),
            stt_use_gpu=stt_use_gpu,
            stt_model=stt_model,
            stt_compute_type=stt_compute_type,
            stt_beam_size=stt_beam_size,
            stt_best_of=stt_best_of,
            stt_vad_filter=parse_bool_env("STT_VAD_FILTER", False),
            stt_language=os.getenv("STT_LANGUAGE")
            or os.getenv("STT_CULTURE", "en-US"),
            stt_timeout_seconds=float(
                os.getenv(
                    "STT_TIMEOUT_SECONDS",
                    os.getenv("STT_INITIAL_SILENCE_TIMEOUT_SECONDS", "15"),
                )
            ),
            stt_phrase_time_limit_seconds=float(
                os.getenv(
                    "STT_PHRASE_TIME_LIMIT_SECONDS",
                    os.getenv("STT_BABBLE_TIMEOUT_SECONDS", "30"),
                )
            ),
            stt_pause_threshold_seconds=float(
                os.getenv(
                    "STT_PAUSE_THRESHOLD_SECONDS",
                    str(max(1.8, pause_threshold_ms / 1000)),
                )
            ),
            stt_non_speaking_duration_seconds=float(
                os.getenv("STT_NON_SPEAKING_DURATION_SECONDS", "1.2")
            ),
            stt_ambient_duration_seconds=float(
                os.getenv("STT_AMBIENT_DURATION_SECONDS", "0.6")
            ),
            stt_energy_threshold=int(os.getenv("STT_ENERGY_THRESHOLD", "300")),
            stt_dynamic_energy_threshold=parse_bool_env(
                "STT_DYNAMIC_ENERGY_THRESHOLD", True
            ),
            mic_device_index=parse_optional_int_env("MIC_DEVICE_INDEX"),
            speaker_device_index=parse_optional_int_env("SPEAKER_DEVICE_INDEX"),
            mic_sample_rate=parse_optional_int_env("MIC_SAMPLE_RATE"),
            mic_chunk_size=mic_chunk_size,
            rag_enabled=parse_bool_env("RAG_ENABLED", True),
            rag_embedding_provider=normalize_rag_embedding_provider(
                os.getenv("RAG_EMBEDDING_PROVIDER", "local")
            ),
            rag_embedding_model=os.getenv(
                "RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            rag_top_k=max(1, min(12, int(os.getenv("RAG_TOP_K", "4")))),
            rag_min_score=float(os.getenv("RAG_MIN_SCORE", "0.25")),
            game_enabled=parse_bool_env("GAME_ENABLED", False),
            game_tick_seconds=max(1.0, float(os.getenv("GAME_TICK_SECONDS", "4"))),
            singing_enabled=parse_bool_env("SINGING_ENABLED", False),
            singing_backend=_normalize_singing_backend(os.getenv("SINGING_BACKEND", "local")),
            singing_fetch_instrumental=parse_bool_env("SINGING_FETCH_INSTRUMENTAL", True),
            rvc_model_path=parse_optional_str_env("RVC_MODEL_PATH"),
            singing_api_url=parse_optional_str_env("SINGING_API_URL"),
            singing_api_key=parse_optional_str_env("SINGING_API_KEY"),
            vision_model=parse_optional_str_env("VISION_MODEL"),
            vrchat_osc_host=os.getenv("VRCHAT_OSC_HOST", "127.0.0.1").strip() or "127.0.0.1",
            vrchat_osc_port=int(os.getenv("VRCHAT_OSC_PORT", "9000")),
            vrchat_osc_read_port=int(os.getenv("VRCHAT_OSC_READ_PORT", "9001")),
            vrchat_log_dir=parse_optional_str_env("VRCHAT_LOG_DIR"),
        )
