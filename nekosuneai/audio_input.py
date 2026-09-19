"""Microphone capture and speech-to-text for the companion runtime.

The voice stack is an optional extra. Every hard dependency below (PortAudio
via sounddevice, SpeechRecognition, torch) is imported defensively so a
text-only deployment - a headless container, a CLI session, a Pi with no
capture hardware - still imports this module and fails only at the point
where audio is genuinely required.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple, TYPE_CHECKING

import numpy as np

_OPTIONAL_IMPORT_ERRORS = (ImportError, OSError)

try:
    import sounddevice as sd
except _OPTIONAL_IMPORT_ERRORS:  # OSError covers a missing PortAudio shared object
    sd = None  # type: ignore[assignment]
try:
    import speech_recognition as sr
except _OPTIONAL_IMPORT_ERRORS:
    sr = None  # type: ignore[assignment]
try:
    import torch
except _OPTIONAL_IMPORT_ERRORS:
    torch = None  # type: ignore[assignment]

from .config import Config
from .models import SessionState, SpeechCapture, UserTurn
from .utils import console_safe_text

if TYPE_CHECKING:
    import speech_recognition as sr  # noqa: F811


VOICE_EXTRAS_HINT = (
    "Voice support is not installed. Install the optional extras with:\n"
    "    pip install -r requirements-voice.txt"
)

_PCM_DTYPE = "int16"
_PCM_SAMPLE_WIDTH = 2
_RESAMPLE_RATE = 16000


def _require_audio() -> None:
    """Raise a friendly error if the optional voice/mic stack is unavailable."""
    absent = [
        label
        for label, module in (("sounddevice", sd), ("SpeechRecognition", sr))
        if module is None
    ]
    if absent:
        raise RuntimeError(VOICE_EXTRAS_HINT)


# --------------------------------------------------------------------------
# Capture plumbing
# --------------------------------------------------------------------------


def _build_channel_extractor(
    channels: int, channel_index: int
) -> Callable[[bytes], bytes] | None:
    """Return a de-interleaver for multi-channel capture, or None for mono.

    Resolving this once at stream-open time keeps the per-read path free of
    channel-layout branching, which matters on hardware like the Kinect array
    where reads happen continuously.
    """
    if channels <= 1:
        return None

    def extract(raw: bytes) -> bytes:
        interleaved = np.frombuffer(raw, dtype=np.int16)
        usable = interleaved.size - (interleaved.size % channels)
        if usable <= 0:
            return b""
        picked = interleaved[:usable].reshape(-1, channels)[:, channel_index]
        return np.ascontiguousarray(picked).tobytes()

    return extract


class SoundDeviceStream:
    """File-like shim presenting a PortAudio stream the way SpeechRecognition wants."""

    def __init__(
        self,
        raw_stream: "sd.RawInputStream",
        channels: int = 1,
        channel_index: int = 0,
    ):
        self.raw_stream = raw_stream
        self.channels = channels
        self.channel_index = channel_index
        self._extract = _build_channel_extractor(channels, channel_index)

    def read(self, size: int) -> bytes:
        block, _overflowed = self.raw_stream.read(size)
        raw = bytes(block)
        return raw if self._extract is None else self._extract(raw)

    def close(self) -> None:
        try:
            self.raw_stream.stop()
        except Exception:
            pass
        self.raw_stream.close()


# Bind the base class at import time. With the voice extras present this is a
# real sr.AudioSource; without them it degrades to object so the module still
# imports, and construction raises the friendly hint instead.
_AudioSourceBase = sr.AudioSource if sr is not None else object


def _preferred_channel_count(device_name: str, max_channels: int) -> int:
    """Kinect arrays are worth opening wide; everything else defaults to mono."""
    lowered = device_name.lower()
    if "kinect" in lowered and max_channels >= 4:
        return 4
    return 1


class SoundDeviceMicrophone(_AudioSourceBase):
    """A SpeechRecognition audio source backed directly by PortAudio."""

    def __init__(
        self,
        device_index: int | None = None,
        sample_rate: int | None = None,
        chunk_size: int = 1024,
        input_channels: int = 0,
        channel_index: int = 0,
    ):
        _require_audio()
        if device_index is not None and not isinstance(device_index, int):
            raise TypeError("device_index must be an int or None")
        if sample_rate is not None and not (
            isinstance(sample_rate, int) and sample_rate > 0
        ):
            raise ValueError("sample_rate must be a positive int or None")
        if not (isinstance(chunk_size, int) and chunk_size > 0):
            raise ValueError("chunk_size must be a positive int")

        info = resolve_input_device_info(device_index)
        self.device_index = info["index"]
        self.device_name = info["name"]

        ceiling = info["max_input_channels"]
        requested = input_channels or _preferred_channel_count(self.device_name, ceiling)
        self.input_channels = max(1, min(requested, ceiling))
        self.channel_index = max(0, min(channel_index, self.input_channels - 1))

        self.SAMPLE_WIDTH = _PCM_SAMPLE_WIDTH
        self.SAMPLE_RATE = sample_rate or info["default_sample_rate"]
        self.CHUNK = chunk_size

        self.stream: SoundDeviceStream | None = None
        self._raw_stream: Any = None

    def __enter__(self) -> "SoundDeviceMicrophone":
        if self.stream is not None:
            raise RuntimeError("This audio source is already inside a context manager")

        try:
            raw_stream = sd.RawInputStream(
                samplerate=self.SAMPLE_RATE,
                blocksize=self.CHUNK,
                device=self.device_index,
                channels=self.input_channels,
                dtype=_PCM_DTYPE,
            )
            raw_stream.start()
        except Exception as exc:
            raise RuntimeError(
                f"Could not open microphone '{self.device_name}'. {exc}"
            ) from exc

        self._raw_stream = raw_stream
        self.stream = SoundDeviceStream(
            raw_stream, self.input_channels, self.channel_index
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.stream is not None:
            self.stream.close()
        self.stream = None
        self._raw_stream = None


def _open_configured_microphone(config: Config) -> SoundDeviceMicrophone:
    """Build a microphone source from the mic_* block of the config."""
    return SoundDeviceMicrophone(
        device_index=config.mic_device_index,
        sample_rate=config.mic_sample_rate,
        chunk_size=config.mic_chunk_size,
        input_channels=config.mic_input_channels,
        channel_index=config.mic_channel_index,
    )


# --------------------------------------------------------------------------
# Device discovery
# --------------------------------------------------------------------------


def get_stt_device(config: Config) -> str:
    cuda_ready = torch is not None and torch.cuda.is_available()
    return "cuda" if (config.stt_use_gpu and cuda_ready) else "cpu"


def get_stt_compute_type(config: Config) -> str:
    explicit = config.stt_compute_type
    if explicit and explicit not in {"auto", "default"}:
        return explicit
    return "float16" if get_stt_device(config) == "cuda" else "int8"


def get_default_input_device_index() -> int | None:
    """PortAudio's current default capture index, or None when there isn't one."""
    if sd is None:
        return None

    configured = sd.default.device
    if isinstance(configured, (list, tuple)):
        configured = configured[0] if configured else None
    if configured is None:
        return None

    try:
        index = int(configured)
    except (TypeError, ValueError):
        return None

    return index if index >= 0 else None


_HOSTAPI_SUFFIX = re.compile(
    r"\s+\((mme|wasapi|wdm-ks|directsound|asio)\)$", flags=re.IGNORECASE
)
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_audio_device_name(name: str) -> str:
    collapsed = _WHITESPACE_RUN.sub(" ", name).strip()
    return _HOSTAPI_SUFFIX.sub("", collapsed)


def get_hostapi_names() -> list[str]:
    try:
        hostapis = sd.query_hostapis()
    except Exception:
        return []
    return [str(hostapi.get("name", "")) for hostapi in hostapis]


def _input_channel_count(device: Any) -> int:
    count = device.get("max_input_channels", 0)
    return int(count) if isinstance(count, (int, float)) else 0


def _query_devices_or_raise() -> Any:
    try:
        return sd.query_devices()
    except Exception as exc:
        raise RuntimeError(f"I couldn't list microphone devices. {exc}") from exc


def _iter_input_devices() -> Iterator[tuple[int, Any]]:
    """Yield (index, device) for every device that can actually capture."""
    for index, device in enumerate(_query_devices_or_raise()):
        if _input_channel_count(device) > 0:
            yield index, device


def resolve_input_device_info(device_index: int | None) -> dict[str, Any]:
    _require_audio()

    try:
        if device_index is None:
            device = sd.query_devices(kind="input")
            resolved_index = get_default_input_device_index()
        else:
            device = sd.query_devices(device_index, "input")
            resolved_index = device_index
    except Exception as exc:
        label = (
            "the default microphone"
            if device_index is None
            else f"microphone #{device_index}"
        )
        raise RuntimeError(
            f"I couldn't access {label}. Use /mics to list available input devices."
        ) from exc

    device_name = str(device.get("name", "Input device"))
    reported_rate = device.get("default_samplerate")
    if not isinstance(reported_rate, (int, float)) or reported_rate <= 0:
        raise RuntimeError(
            f"The microphone '{device_name}' did not report a valid sample rate."
        )

    return {
        "index": resolved_index,
        "name": normalize_audio_device_name(device_name),
        "default_sample_rate": int(reported_rate),
        "max_input_channels": max(1, int(device.get("max_input_channels", 1))),
    }


def list_input_devices() -> list[dict[str, Any]]:
    if sd is None:
        return []

    default_index = get_default_input_device_index()
    return [
        {
            "index": index,
            "name": str(device.get("name", "Input device")),
            "is_default": index == default_index,
        }
        for index, device in _iter_input_devices()
    ]


# Windows exposes the same physical mic once per host API. Lower is better.
_HOSTAPI_PRIORITY = {
    "Windows WASAPI": 0,
    "Windows DirectSound": 1,
    "WDM-KS": 2,
    "ASIO": 3,
    "MME": 4,
}
_HOSTAPI_PRIORITY_FALLBACK = 9

_SYNTHETIC_DEVICE_NAMES = frozenset(
    {
        "primary sound capture driver",
        "microsoft sound mapper - input",
    }
)


class _MicCandidate(NamedTuple):
    """One enumerated mic plus the tie-break rank used to deduplicate it."""

    rank: tuple[int, int, int]
    index: int
    name: str
    hostapi: str
    is_default: bool

    def as_entry(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "hostapi": self.hostapi,
            "is_default": self.is_default,
        }


def _resolve_hostapi_name(device: Any, hostapi_names: list[str]) -> str:
    hostapi_index = device.get("hostapi")
    if isinstance(hostapi_index, int) and 0 <= hostapi_index < len(hostapi_names):
        return hostapi_names[hostapi_index]
    return ""


def _collect_mic_candidates() -> list[_MicCandidate]:
    default_index = get_default_input_device_index()
    hostapi_names = get_hostapi_names()

    candidates: list[_MicCandidate] = []
    for index, device in _iter_input_devices():
        name = normalize_audio_device_name(str(device.get("name", "Input device")))
        if name.strip().lower() in _SYNTHETIC_DEVICE_NAMES:
            continue

        hostapi = _resolve_hostapi_name(device, hostapi_names)
        is_default = index == default_index
        candidates.append(
            _MicCandidate(
                rank=(
                    0 if is_default else 1,
                    _HOSTAPI_PRIORITY.get(hostapi, _HOSTAPI_PRIORITY_FALLBACK),
                    index,
                ),
                index=index,
                name=name,
                hostapi=hostapi,
                is_default=is_default,
            )
        )
    return candidates


def list_input_devices_compact(max_devices: int = 24) -> list[dict[str, Any]]:
    """One row per physical microphone, best host API chosen, default first."""
    if sd is None:
        return []

    # Rank-sort first, then keep the first sighting of each name: whichever
    # duplicate survives is by construction the best-ranked one.
    best_per_name: dict[str, _MicCandidate] = {}
    for candidate in sorted(_collect_mic_candidates(), key=lambda item: item.rank):
        best_per_name.setdefault(candidate.name.lower(), candidate)

    ordered = sorted(
        best_per_name.values(),
        key=lambda item: (0 if item.is_default else 1, item.name.lower()),
    )
    if max_devices > 0:
        ordered = ordered[:max_devices]
    return [candidate.as_entry() for candidate in ordered]


def describe_selected_microphone(config: Config) -> str:
    requested = config.mic_device_index
    try:
        info = resolve_input_device_info(requested)
    except RuntimeError:
        return "default microphone" if requested is None else f"microphone #{requested}"

    if requested is None or info["index"] is None:
        return f"default microphone ({info['name']})"
    return f"#{info['index']} ({info['name']})"


def print_input_devices() -> None:
    devices = list_input_devices()
    print()
    if not devices:
        print("No microphone input devices were found.")
        print()
        return

    print("Available microphones:")
    for device in devices:
        marker = " (default)" if device["is_default"] else ""
        print(f"{device['index']}: {device['name']}{marker}")
    print()


# --------------------------------------------------------------------------
# Recognizer and model lifecycle
# --------------------------------------------------------------------------

# Config fields that, when changed, invalidate a cached sr.Recognizer.
_RECOGNIZER_FIELDS = (
    "mic_device_index",
    "mic_sample_rate",
    "mic_chunk_size",
    "mic_input_channels",
    "mic_channel_index",
    "stt_energy_threshold",
    "stt_dynamic_energy_threshold",
    "stt_pause_threshold_seconds",
    "stt_non_speaking_duration_seconds",
)

_MIN_ENERGY_THRESHOLD = 50
_MIN_PAUSE_SECONDS = 0.5
_PHRASE_THRESHOLD = 0.2


def get_speech_recognizer_signature(config: Config) -> tuple[Any, ...]:
    return tuple(getattr(config, field) for field in _RECOGNIZER_FIELDS)


def build_speech_recognizer(config: Config) -> "sr.Recognizer":
    _require_audio()
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = max(
        _MIN_ENERGY_THRESHOLD, config.stt_energy_threshold
    )
    recognizer.dynamic_energy_threshold = config.stt_dynamic_energy_threshold
    recognizer.pause_threshold = max(
        _MIN_PAUSE_SECONDS, config.stt_pause_threshold_seconds
    )
    recognizer.non_speaking_duration = min(
        recognizer.pause_threshold,
        max(_MIN_PAUSE_SECONDS, config.stt_non_speaking_duration_seconds),
    )
    recognizer.phrase_threshold = _PHRASE_THRESHOLD
    return recognizer


def ensure_speech_recognizer(config: Config, state: SessionState) -> "sr.Recognizer":
    signature = get_speech_recognizer_signature(config)
    if (
        state.speech_recognizer is not None
        and state.speech_recognizer_signature == signature
    ):
        return state.speech_recognizer

    state.speech_recognizer = build_speech_recognizer(config)
    state.speech_recognizer_signature = signature
    state.mic_calibrated = False
    return state.speech_recognizer


def get_stt_model_signature(config: Config) -> tuple[Any, ...]:
    model_ref = (
        config.vosk_model_path if config.stt_provider == "vosk" else config.stt_model
    )
    return (
        config.stt_provider,
        model_ref,
        get_stt_device(config),
        get_stt_compute_type(config),
    )


def _cached_stt_model(
    state: SessionState,
    signature: tuple[Any, ...],
    build: Callable[[], Any],
) -> Any:
    """Return the cached model when its signature still matches, else rebuild."""
    if state.stt_model_instance is not None and state.stt_model_signature == signature:
        return state.stt_model_instance

    state.stt_model_instance = build()
    state.stt_model_signature = signature
    return state.stt_model_instance


def _load_vosk_model(config: Config) -> Any:
    try:
        from vosk import Model
    except ImportError as exc:
        raise RuntimeError("Vosk local STT is not installed in this image.") from exc

    model_path = Path(config.vosk_model_path).expanduser()
    if not model_path.is_dir():
        raise RuntimeError(
            f"Vosk model was not found at '{model_path}'. Pull the latest Docker image "
            "or set VOSK_MODEL_PATH to the extracted small model folder."
        )
    return Model(str(model_path))


def _load_whisper_model(config: Config) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from exc

    try:
        return WhisperModel(
            config.stt_model,
            device=get_stt_device(config),
            compute_type=get_stt_compute_type(config),
        )
    except Exception as exc:
        raise RuntimeError(
            f"I couldn't load the speech model '{config.stt_model}'. {exc}"
        ) from exc


# Providers that hold a resident model object. Anything absent here (bridge,
# google) is remote and has nothing to preload.
_MODEL_LOADERS: dict[str, Callable[[Config], Any]] = {
    "vosk": _load_vosk_model,
    "faster-whisper": _load_whisper_model,
}


def ensure_stt_model(config: Config, state: SessionState) -> Any:
    loader = _MODEL_LOADERS.get(config.stt_provider)
    if loader is None:
        return None
    return _cached_stt_model(
        state, get_stt_model_signature(config), lambda: loader(config)
    )


def recalibrate_microphone(
    config: Config,
    state: SessionState,
    announce: bool = True,
) -> None:
    recognizer = ensure_speech_recognizer(config, state)

    ambient_seconds = config.stt_ambient_duration_seconds
    if ambient_seconds <= 0:
        state.mic_calibrated = True
        return

    if announce:
        print()
        print(
            f"[Mic] Calibrating {describe_selected_microphone(config)} for "
            f"{ambient_seconds:.1f}s. Stay quiet for a moment."
        )

    with _open_configured_microphone(config) as source:
        recognizer.adjust_for_ambient_noise(source, duration=ambient_seconds)

    state.mic_calibrated = True
    if announce:
        print("[Mic] Calibration complete.")


# --------------------------------------------------------------------------
# Transcription
# --------------------------------------------------------------------------

_STATIC_BACKEND_LABELS = {
    "vosk": "Vosk small (local/offline)",
    "bridge": "NekoAI Bridge Whisper (remote)",
    "google": "google",
}


def describe_stt_backend(config: Config) -> str:
    label = _STATIC_BACKEND_LABELS.get(config.stt_provider)
    if label is not None:
        return label
    return (
        f"faster-whisper ({config.stt_model}, "
        f"{get_stt_device(config)}/{get_stt_compute_type(config)})"
    )


def normalize_stt_language_for_whisper(language: str) -> str | None:
    """Reduce a BCP-47-ish tag to the bare language Whisper expects."""
    tag = language.strip().lower().replace("_", "-")
    if not tag or tag == "auto":
        return None
    return tag.split("-", 1)[0]


def _pcm16(audio: "sr.AudioData") -> bytes:
    return audio.get_raw_data(
        convert_rate=_RESAMPLE_RATE, convert_width=_PCM_SAMPLE_WIDTH
    )


def transcribe_audio_with_faster_whisper(
    audio: "sr.AudioData",
    config: Config,
    state: SessionState,
) -> tuple[str, str]:
    model = ensure_stt_model(config, state)
    language = normalize_stt_language_for_whisper(config.stt_language)

    waveform = np.frombuffer(_pcm16(audio), dtype=np.int16).astype(np.float32) / 32768.0

    segments, info = model.transcribe(
        waveform,
        language=language,
        task="transcribe",
        beam_size=config.stt_beam_size,
        best_of=max(config.stt_beam_size, config.stt_best_of),
        vad_filter=config.stt_vad_filter,
        condition_on_previous_text=False,
        without_timestamps=True,
        temperature=0.0,
    )

    spoken = [segment.text.strip() for segment in segments]
    text = " ".join(part for part in spoken if part).strip()
    detected = getattr(info, "language", None) or language or ""
    return text, str(detected)


def transcribe_audio_with_google(
    recognizer: "sr.Recognizer",
    audio: "sr.AudioData",
    config: Config,
) -> tuple[str, str]:
    try:
        text = recognizer.recognize_google(audio, language=config.stt_language).strip()
    except sr.UnknownValueError:
        return "", config.stt_language
    except sr.RequestError as exc:
        raise RuntimeError(
            "Speech recognition could not reach the recognition service. "
            "Check your internet connection."
        ) from exc

    return text, config.stt_language


_VOSK_FEED_BYTES = 8000


def transcribe_audio_with_vosk(
    audio: "sr.AudioData",
    config: Config,
    state: SessionState,
) -> tuple[str, str]:
    from vosk import KaldiRecognizer, SetLogLevel

    SetLogLevel(-1)
    model = ensure_stt_model(config, state)

    pcm = _pcm16(audio)
    kaldi = KaldiRecognizer(model, _RESAMPLE_RATE)
    kaldi.SetWords(False)
    for offset in range(0, len(pcm), _VOSK_FEED_BYTES):
        kaldi.AcceptWaveform(pcm[offset:offset + _VOSK_FEED_BYTES])

    payload = json.loads(kaldi.FinalResult())
    return str(payload.get("text", "")).strip(), "en"


class _TranscriptionJob(NamedTuple):
    """Everything a provider might need, so all of them share one signature."""

    audio: Any
    recognizer: Any
    config: Config
    state: SessionState


def _via_vosk(job: _TranscriptionJob) -> tuple[str, str]:
    return transcribe_audio_with_vosk(job.audio, job.config, job.state)


def _via_bridge(job: _TranscriptionJob) -> tuple[str, str]:
    from .bridge_voice import transcribe

    return transcribe(job.audio.get_wav_data(), job.config)


def _via_google(job: _TranscriptionJob) -> tuple[str, str]:
    return transcribe_audio_with_google(job.recognizer, job.audio, job.config)


def _via_faster_whisper(job: _TranscriptionJob) -> tuple[str, str]:
    return transcribe_audio_with_faster_whisper(job.audio, job.config, job.state)


_TRANSCRIBERS: dict[str, Callable[[_TranscriptionJob], tuple[str, str]]] = {
    "vosk": _via_vosk,
    "bridge": _via_bridge,
    "google": _via_google,
}


def _run_transcription(job: _TranscriptionJob) -> tuple[str, str]:
    transcribe = _TRANSCRIBERS.get(job.config.stt_provider, _via_faster_whisper)
    try:
        return transcribe(job)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Speech recognition failed. {exc}") from exc


# --------------------------------------------------------------------------
# Public capture entry points
# --------------------------------------------------------------------------


def recognize_speech(
    config: Config,
    state: SessionState,
    announce: bool = True,
) -> SpeechCapture:
    recognizer = ensure_speech_recognizer(config, state)
    if not state.mic_calibrated:
        recalibrate_microphone(config, state, announce=announce)

    with _open_configured_microphone(config) as source:
        device_name = source.device_name
        try:
            audio = recognizer.listen(
                source,
                timeout=config.stt_timeout_seconds,
                phrase_time_limit=config.stt_phrase_time_limit_seconds,
            )
        except sr.WaitTimeoutError:
            return SpeechCapture(
                status="timeout",
                language=config.stt_language,
                device_name=device_name,
            )

    text, detected_language = _run_transcription(
        _TranscriptionJob(
            audio=audio, recognizer=recognizer, config=config, state=state
        )
    )
    language = detected_language or config.stt_language

    if not text:
        return SpeechCapture(
            status="unknown",
            language=language,
            device_name=device_name,
            error="I heard audio, but I couldn't understand the words clearly.",
        )

    return SpeechCapture(
        status="ok",
        text=text,
        language=language,
        device_name=device_name,
    )


def capture_voice_turn(
    config: Config,
    profile: dict[str, Any],
    state: SessionState,
) -> UserTurn | None:
    print()
    print(
        f"[Listening] Speak to {profile['companion_name']} now with "
        f"{describe_selected_microphone(config)}."
    )

    result = recognize_speech(config, state)

    if result.status == "timeout":
        print("[Listening] I didn't hear anything that sounded like speech.")
        return None
    if result.status == "unknown":
        print("[Listening] I heard you, but I couldn't understand the words.")
        return None
    if result.status != "ok":
        raise RuntimeError(
            result.error or "Speech recognition did not return a usable result."
        )

    print(console_safe_text(f"{profile['user_name']}: {result.text}"))
    return UserTurn(text=result.text, from_voice=True)
