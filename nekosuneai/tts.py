"""Speech synthesis and playback.

Covers the whole outbound audio path: choosing an output device that will
actually accept the stream, rendering text with XTTS or gTTS, streaming XTTS
chunks as they are generated, resampling when the device insists on its own
rate, and playing the result back with an amplitude signal for avatar lip sync.

Every heavyweight dependency is optional. The module imports on a machine with
no speakers and no ML stack; the functions that genuinely need them raise a
readable error instead.
"""

from __future__ import annotations

import ctypes
import os
import queue
import re
import threading
import time
import wave
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

# XTTS-v2 is licensed under Coqui's CPML (non-commercial) and coqui-tts
# normally asks an interactive "do you agree to CPML?" [y/n] the first time
# the model is downloaded. That has no stdin to answer into from the desktop
# GUI (no console at all) or the headless setup preload (bootstrap.py) -
# it just crashes with "You must agree to the terms of service to use this
# model." Pre-agreeing here (the documented non-interactive bypass) mirrors
# what enabling the voice profile already opts a user into.
os.environ["COQUI_TOS_AGREED"] = "1"

# sounddevice (PortAudio), torch and coqui-tts (TTS) are optional voice extras.
# Guard them so this module imports text-only (CLI / headless web) on machines
# without speakers or the heavy ML stack (e.g. a headless Raspberry Pi). The
# functions that actually synthesize/play audio call the _require_* helpers.
try:
    import sounddevice as sd
except (ImportError, OSError):  # OSError: PortAudio shared lib missing
    sd = None  # type: ignore[assignment]
try:
    import torch
except (ImportError, OSError) as exc:
    torch = None  # type: ignore[assignment]
    _torch_import_error: BaseException | None = exc
else:
    _torch_import_error = None
try:
    from TTS.api import TTS
except (ImportError, OSError) as exc:
    TTS = None  # type: ignore[assignment]
    _tts_import_error: BaseException | None = exc
else:
    _tts_import_error = None

from .audio_input import (
    VOICE_EXTRAS_HINT,
    _require_audio,
    get_hostapi_names,
    normalize_audio_device_name,
)
from .config import Config
from .models import SessionState
from .paths import AUDIO_DIR, ROOT_DIR, XTTS_STREAM_END
from .utils import console_safe_text

_DEFAULT_XTTS_SAMPLE_RATE = 24000
_MIN_SAMPLE_RATE = 8000
_COMMON_FALLBACK_RATES = (48000, 44100)

_DEVICE_KEY_MAX_CHARS = 28
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")

# Amplitude reported for lip sync is RMS scaled into roughly 0..1; speech RMS
# is small, so it needs a sizeable multiplier to read as mouth-open.
_AMPLITUDE_GAIN = 6.0
_ENVELOPE_FRAME_SECONDS = 0.04  # ~25 fps
_BLOCK_SECONDS = 0.05  # ~50 ms playback frames
_MIN_BLOCK_FRAMES = 256
_STREAM_BLOCKSIZE = 2048

_MCI_ALIAS = "ai_companion_audio"
_MCI_ERROR_BUFFER_CHARS = 255

# Host APIs that open the device exclusively, locking other apps out.
_EXCLUSIVE_HOSTAPIS = {
    "Windows WASAPI",
    "Windows WDM-KS",
    "WDM-KS",
    "JACK Audio Connection Kit",
    "JACK",
}

# Preference when the same physical speaker is reachable through several host
# APIs: shared-mode APIs first, so playback does not seize the device.
_PLAYBACK_HOSTAPI_PRIORITY = {
    # Windows
    "Windows DirectSound": 0,
    "MME": 1,
    "Windows WASAPI": 2,
    "Windows WDM-KS": 3,
    "WDM-KS": 3,
    "ASIO": 4,
    # Linux
    "ALSA": 0,
    "PulseAudio": 1,
    "PipeWire": 1,
    "JACK Audio Connection Kit": 2,
    "JACK": 2,
    # macOS
    "Core Audio": 0,
}

# Near-identical to the table above, but tuned for what to *show* in a picker:
# ASIO and WDM-KS are demoted together rather than ranked apart.
_LISTING_HOSTAPI_PRIORITY = {
    # Windows - favor shared-mode APIs first for compatibility.
    "Windows DirectSound": 0,
    "MME": 1,
    "Windows WASAPI": 2,
    "WDM-KS": 3,
    "ASIO": 3,
    "Windows WDM-KS": 4,
    # Linux
    "ALSA": 0,
    "PulseAudio": 1,
    "PipeWire": 1,
    "JACK Audio Connection Kit": 2,
    "JACK": 2,
    # macOS
    "Core Audio": 0,
}
_UNRANKED_HOSTAPI = 9

_IGNORED_OUTPUT_NAMES = {
    "primary sound driver",
    "microsoft sound mapper - output",
}


def _require_xtts() -> None:
    """Raise a friendly error if the local XTTS stack (coqui-tts + torch) is absent."""
    if TTS is not None and torch is not None:
        return

    import_error = _tts_import_error or _torch_import_error
    if import_error is None:
        raise RuntimeError(VOICE_EXTRAS_HINT)
    raise RuntimeError(
        f"{VOICE_EXTRAS_HINT}\n\nImport error: {import_error}"
    ) from import_error


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def normalize_gtts_language(language: str) -> str:
    normalized = language.strip().replace("_", "-")
    if not normalized:
        return "en"
    return normalized.split("-", 1)[0].lower()


def should_play_audio_after_synthesis(config: Config) -> bool:
    """Whether this host should play what it just synthesised."""
    # Audio synthesised for a peripheral node belongs on that node's speaker.
    # Playing it here means a VPS talking to an empty room -- and on a
    # container with no audio device, a stream of ALSA/PulseAudio failures.
    if getattr(config, "node_tts_no_playback", False):
        return False

    if config.tts_provider == "bridge":
        try:
            from .bridge_voice import stream_was_played

            if stream_was_played():
                return False
        except Exception:
            pass

    # Chat RVC needs the fully-synthesized file to convert before anything is
    # played, so it forces the non-streaming path (see _speak_text_inner) -
    # meaning playback always happens afterward, same as gTTS/non-streaming XTTS.
    if config.rvc_chat_enabled:
        return True

    return not (config.tts_provider == "xtts" and config.xtts_stream_output)


def resolve_optional_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    candidate = Path(path_value)
    return candidate if candidate.is_absolute() else ROOT_DIR / candidate


def get_xtts_device(config: Config) -> str:
    cuda_ready = torch is not None and torch.cuda.is_available()
    return "cuda" if (config.xtts_use_gpu and cuda_ready) else "cpu"


# --------------------------------------------------------------------------
# Output device discovery
# --------------------------------------------------------------------------


def get_default_output_device_index() -> int | None:
    if sd is None:
        return None

    configured = sd.default.device
    if isinstance(configured, (list, tuple)):
        if len(configured) < 2:
            return None
        candidate = configured[1]
    else:
        # A scalar default names an input device only; there is no output half.
        candidate = None

    if candidate is None:
        return None

    try:
        index = int(candidate)
    except (TypeError, ValueError):
        return None

    return index if index >= 0 else None


def resolve_output_device_info(device_index: int | None) -> dict[str, Any]:
    try:
        if device_index is None:
            device = sd.query_devices(kind="output")
            resolved_index = get_default_output_device_index()
        else:
            device = sd.query_devices(device_index, "output")
            resolved_index = device_index
    except Exception as exc:
        label = (
            "the default speaker"
            if device_index is None
            else f"speaker #{device_index}"
        )
        raise RuntimeError(
            f"I couldn't access {label}. Refresh devices and try another option."
        ) from exc

    device_name = str(device.get("name", "Output device"))
    reported_rate = device.get("default_samplerate")
    if not isinstance(reported_rate, (int, float)) or reported_rate <= 0:
        raise RuntimeError(
            f"The speaker '{device_name}' did not report a valid sample rate."
        )

    return {
        "index": resolved_index,
        "name": normalize_audio_device_name(device_name),
        "default_sample_rate": int(reported_rate),
    }


def output_device_name_key(device_name: str) -> str:
    """A loose identity for a speaker, so the same box seen through several
    host APIs collapses to one entry."""
    normalized = normalize_audio_device_name(device_name).lower()
    simplified = _NON_ALNUM.sub("", normalized)
    return simplified[:_DEVICE_KEY_MAX_CHARS] if simplified else normalized


def resolve_output_hostapi_name(
    device: dict[str, Any],
    hostapi_names: list[str],
) -> str:
    hostapi_index = device.get("hostapi")
    if isinstance(hostapi_index, int) and 0 <= hostapi_index < len(hostapi_names):
        return hostapi_names[hostapi_index]
    return ""


def _output_channel_count(device: Any) -> int:
    count = device.get("max_output_channels", 0)
    return int(count) if isinstance(count, (int, float)) else 0


def _hostapi_rank(hostapi_name: str, table: dict[str, int]) -> int:
    return table.get(hostapi_name, _UNRANKED_HOSTAPI)


def choose_compatible_output_device_index(
    output_device_index: int | None,
) -> int | None:
    """Swap an exclusive-mode device for a shared-mode view of the same speaker."""
    if output_device_index is None:
        return None

    try:
        all_devices = sd.query_devices()
        selected_device = sd.query_devices(output_device_index, "output")
    except Exception:
        return output_device_index

    hostapi_names = get_hostapi_names()
    selected_hostapi = resolve_output_hostapi_name(selected_device, hostapi_names)
    if selected_hostapi not in _EXCLUSIVE_HOSTAPIS:
        return output_device_index

    selected_key = output_device_name_key(str(selected_device.get("name", "")))
    if not selected_key:
        return output_device_index

    best_index = output_device_index
    best_score = (
        _hostapi_rank(selected_hostapi, _PLAYBACK_HOSTAPI_PRIORITY),
        output_device_index,
    )

    for index, device in enumerate(all_devices):
        if _output_channel_count(device) <= 0:
            continue
        if output_device_name_key(str(device.get("name", ""))) != selected_key:
            continue

        hostapi_name = resolve_output_hostapi_name(device, hostapi_names)
        score = (_hostapi_rank(hostapi_name, _PLAYBACK_HOSTAPI_PRIORITY), index)
        if score < best_score:
            best_score = score
            best_index = index

    return best_index


def list_output_devices_compact(max_devices: int = 24) -> list[dict[str, Any]]:
    """One row per physical speaker, best host API chosen, default first."""
    if sd is None:
        return []

    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise RuntimeError(f"I couldn't list speaker devices. {exc}") from exc

    default_index = get_default_output_device_index()
    hostapi_names = get_hostapi_names()

    scored: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for index, device in enumerate(devices):
        if _output_channel_count(device) <= 0:
            continue

        name = normalize_audio_device_name(str(device.get("name", "Output device")))
        if name.strip().lower() in _IGNORED_OUTPUT_NAMES:
            continue

        hostapi_name = resolve_output_hostapi_name(device, hostapi_names)
        is_default = index == default_index
        scored.append(
            (
                (
                    0 if is_default else 1,
                    _hostapi_rank(hostapi_name, _LISTING_HOSTAPI_PRIORITY),
                    # Prefer the longer, more descriptive spelling of a name.
                    -len(name),
                    index,
                ),
                {
                    "index": index,
                    "name": name,
                    "hostapi": hostapi_name,
                    "is_default": is_default,
                },
            )
        )

    # Sort by rank first, then keep the first sighting of each speaker: the
    # survivor is by construction the best-ranked one.
    best_per_key: dict[str, dict[str, Any]] = {}
    for _score, entry in sorted(scored, key=lambda pair: pair[0]):
        best_per_key.setdefault(output_device_name_key(entry["name"]), entry)

    ordered = sorted(
        best_per_key.values(),
        key=lambda item: (0 if item["is_default"] else 1, item["name"].lower()),
    )
    return ordered[:max_devices] if max_devices > 0 else ordered


def describe_selected_speaker(config: Config) -> str:
    requested = config.speaker_device_index
    try:
        info = resolve_output_device_info(requested)
    except RuntimeError:
        return "default speaker" if requested is None else f"speaker #{requested}"

    if requested is None:
        return f"default speaker ({info['name']})"
    return f"#{info['index']} ({info['name']})"


# --------------------------------------------------------------------------
# Sample-rate planning and resampling
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputPlaybackPlan:
    output_device_index: int | None
    sample_rate: int
    requires_resample: bool


class StreamingLinearResampler:
    """Linear resampler that keeps phase across successive chunks.

    A streaming synth hands over short buffers; resampling each one in
    isolation would restart the interpolation phase every time and click at the
    seams. This carries the fractional read position and the unconsumed tail
    from one call to the next.
    """

    def __init__(self, source_sample_rate: int, target_sample_rate: int) -> None:
        self.source_sample_rate = max(1, int(source_sample_rate))
        self.target_sample_rate = max(1, int(target_sample_rate))
        self._step = float(self.source_sample_rate) / float(self.target_sample_rate)
        self._buffer = np.empty((0, 1), dtype=np.float32)
        self._next_source_position = 0.0

    def process(self, audio: np.ndarray) -> np.ndarray:
        incoming = np.asarray(audio, dtype=np.float32).reshape(-1, 1)
        if incoming.size == 0:
            return np.empty((0,), dtype=np.float32)

        self._buffer = (
            incoming.copy()
            if self._buffer.size == 0
            else np.concatenate([self._buffer, incoming], axis=0)
        )
        return self._flatten(self._consume_available())

    def flush(self) -> np.ndarray:
        """Emit the tail, then reset for reuse."""
        if self._buffer.size == 0:
            return np.empty((0,), dtype=np.float32)

        # Repeat the final frame once so the last interpolation window closes.
        self._buffer = np.concatenate([self._buffer, self._buffer[-1:, :]], axis=0)
        resampled = self._consume_available()

        self._buffer = np.empty((0, 1), dtype=np.float32)
        self._next_source_position = 0.0
        return self._flatten(resampled)

    @staticmethod
    def _flatten(resampled: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(resampled.reshape(-1), dtype=np.float32)

    def _consume_available(self) -> np.ndarray:
        empty = np.empty((0, 1), dtype=np.float32)
        if self._buffer.shape[0] < 2:
            return empty

        outputs: list[np.ndarray] = []
        last_index = self._buffer.shape[0] - 1
        while self._next_source_position <= float(last_index):
            low = int(self._next_source_position)
            high = min(low + 1, last_index)
            blend = self._next_source_position - low
            outputs.append(
                ((1.0 - blend) * self._buffer[low] + blend * self._buffer[high]).astype(
                    np.float32
                )
            )
            self._next_source_position += self._step

        # Drop frames that can no longer be read, keeping one for interpolation.
        consumed = max(0, int(self._next_source_position) - 1)
        if consumed > 0:
            self._buffer = self._buffer[consumed:, :]
            self._next_source_position -= consumed

        return np.stack(outputs, axis=0) if outputs else empty


def can_use_output_sample_rate(
    output_device_index: int | None,
    sample_rate: int,
    channels: int = 1,
) -> bool:
    try:
        sd.check_output_settings(
            device=output_device_index,
            channels=max(1, int(channels)),
            dtype="float32",
            samplerate=max(_MIN_SAMPLE_RATE, int(sample_rate)),
        )
    except Exception:
        return False
    return True


def _device_default_rate(output_device_index: int | None) -> int | None:
    try:
        info = resolve_output_device_info(output_device_index)
    except RuntimeError:
        return None
    return max(_MIN_SAMPLE_RATE, int(info["default_sample_rate"]))


def choose_output_playback_plan(
    output_device_index: int | None,
    source_sample_rate: int,
    channels: int = 1,
) -> OutputPlaybackPlan:
    """Pick a device and rate the stream will actually open at."""
    device_index = choose_compatible_output_device_index(output_device_index)
    source_rate = max(_MIN_SAMPLE_RATE, int(source_sample_rate))
    default_rate = _device_default_rate(device_index)

    def plan(rate: int) -> OutputPlaybackPlan:
        return OutputPlaybackPlan(
            output_device_index=device_index,
            sample_rate=rate,
            requires_resample=rate != source_rate,
        )

    def accepts(rate: int) -> bool:
        return can_use_output_sample_rate(device_index, rate, channels=channels)

    # Prefer the device's native default rate first. A few Windows drivers
    # "accept" uncommon rates but still run the stream at their native mode,
    # which can sound chipmunked; using the default avoids that mismatch.
    if default_rate is not None and accepts(default_rate):
        return plan(default_rate)

    if accepts(source_rate):
        return plan(source_rate)

    candidate_rates: list[int] = []
    if default_rate is not None:
        candidate_rates.append(default_rate)
    candidate_rates.extend(_COMMON_FALLBACK_RATES)

    tried = {source_rate}
    for rate in candidate_rates:
        if rate in tried:
            continue
        tried.add(rate)
        if accepts(rate):
            return plan(rate)

    # Nothing was accepted: take any rate other than the source and resample,
    # which at least has a chance of opening.
    fallback = next((r for r in candidate_rates if r != source_rate), source_rate)
    return plan(fallback)


def resample_audio_for_output(
    audio: np.ndarray,
    source_sample_rate: int,
    target_sample_rate: int,
) -> np.ndarray:
    """Linearly resample a complete buffer, preserving its 1-D/2-D shape."""
    audio_array = np.asarray(audio, dtype=np.float32)
    if audio_array.size == 0 or source_sample_rate == target_sample_rate:
        return np.ascontiguousarray(audio_array, dtype=np.float32)

    squeeze_output = audio_array.ndim == 1
    if squeeze_output:
        audio_array = audio_array.reshape(-1, 1)

    source_length = audio_array.shape[0]
    if source_length == 1:
        # Nothing to interpolate between; hold the single frame instead.
        repeats = max(1, int(round(target_sample_rate / source_sample_rate)))
        repeated = np.repeat(audio_array, repeats, axis=0)
        return repeated.reshape(-1) if squeeze_output else repeated

    target_length = max(
        1,
        int(round(source_length * float(target_sample_rate) / float(source_sample_rate))),
    )
    source_positions = np.arange(source_length, dtype=np.float32)
    target_positions = np.linspace(
        0, source_length - 1, num=target_length, dtype=np.float32
    )

    resampled = np.stack(
        [
            np.interp(
                target_positions, source_positions, audio_array[:, channel]
            ).astype(np.float32)
            for channel in range(audio_array.shape[1])
        ],
        axis=1,
    )
    if squeeze_output:
        return np.ascontiguousarray(resampled.reshape(-1), dtype=np.float32)
    return np.ascontiguousarray(resampled, dtype=np.float32)


# --------------------------------------------------------------------------
# XTTS model lifecycle
# --------------------------------------------------------------------------


def ensure_xtts_model(config: Config, state: SessionState) -> "TTS":
    _require_xtts()
    desired_device = get_xtts_device(config)

    if state.xtts_model is None or state.xtts_device != desired_device:
        model = TTS(config.xtts_model_name, progress_bar=False)
        model.to(desired_device)
        state.xtts_model = model
        state.xtts_device = desired_device
        state.xtts_speakers = list(model.speakers or [])
        # The cached conditioning belongs to the previous model instance.
        state.xtts_cached_voice_key = None
        state.xtts_cached_conditioning = None

    return state.xtts_model


def list_xtts_speakers(config: Config, state: SessionState) -> list[str]:
    model = ensure_xtts_model(config, state)
    speakers = list(model.speakers or [])
    state.xtts_speakers = speakers
    return speakers


def print_xtts_speakers(config: Config, state: SessionState) -> None:
    speakers = list_xtts_speakers(config, state)
    print()
    if not speakers:
        print("No built-in XTTS speakers were reported by the current model.")
        print()
        return

    print("Available XTTS speakers:")
    for speaker in speakers:
        marker = " (current)" if speaker == config.xtts_speaker else ""
        print(console_safe_text(f"- {speaker}{marker}"))
    print()


def describe_tts_voice(config: Config) -> str:
    if config.tts_provider == "gtts":
        return f"gTTS ({normalize_gtts_language(config.tts_language)})"

    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    if speaker_wav is not None:
        return f"reference voice file ({speaker_wav})"
    return config.xtts_speaker


# --------------------------------------------------------------------------
# Text chunking
# --------------------------------------------------------------------------


def _pack_into_chunks(parts: Iterable[str], max_chars: int) -> list[str]:
    """Greedily join space-separated parts without exceeding ``max_chars``."""
    chunks: list[str] = []
    current = ""

    for part in parts:
        if not current:
            current = part
            continue

        candidate = f"{current} {part}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = part

    if current:
        chunks.append(current)
    return chunks


def split_long_text_fragment(text: str, max_chars: int) -> list[str]:
    """Break one over-long run of text on word boundaries."""
    if len(text) <= max_chars:
        return [text]

    words = text.split()
    if not words:
        return []
    return _pack_into_chunks(words, max_chars)


def split_text_for_xtts(text: str, max_chars: int) -> list[str]:
    """Split text into synthesis-sized chunks, preferring sentence breaks."""
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return []

    parts: list[str] = []
    for sentence in _SENTENCE_BOUNDARY.split(normalized_text):
        if sentence:
            parts.extend(split_long_text_fragment(sentence, max_chars))

    return _pack_into_chunks(parts, max_chars) or [normalized_text]


# Separators to back off to when hard-trimming, best first.
_TRIM_BOUNDARIES = (". ", "! ", "? ", ", ", "; ", ": ", " ")


def trim_text_for_tts(text: str, max_chars: int) -> str:
    normalized_text = " ".join(text.split())
    if len(normalized_text) <= max_chars:
        return normalized_text

    trimmed = normalized_text[: max_chars + 1]
    boundary = max(trimmed.rfind(separator) for separator in _TRIM_BOUNDARIES)
    trimmed = trimmed[:boundary] if boundary > 0 else trimmed[:max_chars]
    return trimmed.rstrip(" ,;:")


# --------------------------------------------------------------------------
# Synthesis
# --------------------------------------------------------------------------


def get_xtts_output_sample_rate(model: TTS) -> int:
    sample_rate = getattr(model.synthesizer, "output_sample_rate", None)
    if isinstance(sample_rate, int) and sample_rate > 0:
        return sample_rate

    audio_config = getattr(
        getattr(model.synthesizer.tts_model, "config", None), "audio", None
    )
    configured_rate = getattr(audio_config, "output_sample_rate", None)
    if isinstance(configured_rate, int) and configured_rate > 0:
        return configured_rate

    return _DEFAULT_XTTS_SAMPLE_RATE


def _require_known_speaker(config: Config, state: SessionState, model: TTS) -> None:
    """Fail early on a speaker name the loaded model does not have."""
    available = state.xtts_speakers or list(model.speakers or [])
    if available and config.xtts_speaker not in available:
        raise RuntimeError(
            f"XTTS speaker '{config.xtts_speaker}' was not found. "
            "Run /speakers to list valid voices."
        )


def _require_speaker_wav(speaker_wav: Path) -> None:
    if not speaker_wav.exists():
        raise RuntimeError(
            f"XTTS speaker reference file was not found: {speaker_wav}"
        )


def resolve_xtts_conditioning(
    config: Config,
    state: SessionState,
    model: TTS,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Conditioning latents for streaming, cached per voice source."""
    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    xtts_model = model.synthesizer.tts_model

    if speaker_wav is not None:
        _require_speaker_wav(speaker_wav)

        resolved_path = str(speaker_wav.resolve())
        cache_key = f"speaker_wav:{resolved_path}"
        if (
            state.xtts_cached_voice_key == cache_key
            and state.xtts_cached_conditioning is not None
        ):
            return state.xtts_cached_conditioning

        conditioning = xtts_model.get_conditioning_latents(audio_path=resolved_path)
        state.xtts_cached_voice_key = cache_key
        state.xtts_cached_conditioning = conditioning
        return conditioning

    _require_known_speaker(config, state, model)

    speaker_data = xtts_model.speaker_manager.speakers.get(config.xtts_speaker)
    if not speaker_data:
        raise RuntimeError(
            f"XTTS speaker '{config.xtts_speaker}' did not expose streaming data."
        )
    return speaker_data["gpt_cond_latent"], speaker_data["speaker_embedding"]


def write_wav_audio(
    audio_path: Path,
    audio_chunks: list[np.ndarray],
    sample_rate: int,
) -> Path:
    if not audio_chunks:
        raise RuntimeError("XTTS did not generate any audio.")

    pcm_audio = np.clip(np.concatenate(audio_chunks), -1.0, 1.0)
    pcm_audio = (pcm_audio * 32767.0).astype(np.int16)

    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_audio.tobytes())

    return audio_path


def synthesize_xtts_to_file(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    output_path: Path,
) -> Path:
    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)

    base_kwargs: dict[str, Any] = {
        "language": config.tts_language,
        "speed": config.xtts_speed,
        "split_sentences": False,
    }
    if speaker_wav is not None:
        _require_speaker_wav(speaker_wav)
        base_kwargs["speaker_wav"] = str(speaker_wav)
    else:
        _require_known_speaker(config, state, model)
        base_kwargs["speaker"] = config.xtts_speaker

    clipped_text = trim_text_for_tts(text, config.xtts_max_text_chars)
    audio_chunks = [
        np.asarray(model.tts(text=chunk, **base_kwargs), dtype=np.float32)
        for chunk in split_text_for_xtts(clipped_text, config.xtts_chunk_max_chars)
    ]

    return write_wav_audio(
        output_path, audio_chunks, get_xtts_output_sample_rate(model)
    )


def synthesize_gtts_to_file(
    text: str,
    config: Config,
    output_path: Path,
) -> Path:
    try:
        from gtts import gTTS
    except ImportError as exc:
        raise RuntimeError("gTTS is not installed. Run: pip install gTTS") from exc

    tts = gTTS(
        text=trim_text_for_tts(text, config.xtts_max_text_chars),
        lang=normalize_gtts_language(config.tts_language),
        slow=False,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    tts.write_to_fp(buffer)
    output_path.write_bytes(buffer.getvalue())
    return output_path


# --------------------------------------------------------------------------
# Streaming synthesis
# --------------------------------------------------------------------------


def produce_xtts_stream_chunks(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    chunk_queue: "queue.SimpleQueue[object]",
    producer_errors: list[Exception],
) -> None:
    """Generate audio chunks onto ``chunk_queue``; always posts the end marker."""
    xtts_model = model.synthesizer.tts_model

    try:
        gpt_cond_latent, speaker_embedding = resolve_xtts_conditioning(
            config, state, model
        )
        clipped_text = trim_text_for_tts(text, config.xtts_max_text_chars)

        for text_chunk in split_text_for_xtts(
            clipped_text, config.xtts_chunk_max_chars
        ):
            chunk_generator = xtts_model.inference_stream(
                text=text_chunk,
                language=config.tts_language,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                stream_chunk_size=config.xtts_stream_chunk_size,
                speed=config.xtts_speed,
                enable_text_splitting=False,
            )
            for chunk in chunk_generator:
                audio_chunk = chunk.detach().float().cpu().numpy().reshape(-1)
                if audio_chunk.size:
                    chunk_queue.put(audio_chunk.copy())
    except Exception as exc:
        producer_errors.append(exc)
    finally:
        chunk_queue.put(XTTS_STREAM_END)


def _emit_amplitude(on_amplitude: Any, audio_chunk: np.ndarray) -> None:
    if on_amplitude is None or audio_chunk.size == 0:
        return
    try:
        rms = float(np.sqrt(np.mean(np.square(audio_chunk, dtype=np.float64))))
        on_amplitude(max(0.0, min(1.0, rms * _AMPLITUDE_GAIN)))
    except Exception:
        pass


def _prime_stream_buffer(
    chunk_queue: "queue.SimpleQueue[object]", target_samples: int
) -> tuple[list[np.ndarray], bool]:
    """Collect chunks until the buffer target is met or the producer finishes."""
    buffered: list[np.ndarray] = []
    buffered_samples = 0

    while buffered_samples < target_samples:
        item = chunk_queue.get()
        if item is XTTS_STREAM_END:
            return buffered, True
        assert isinstance(item, np.ndarray)
        buffered.append(item)
        buffered_samples += item.size

    return buffered, False


def stream_xtts_audio(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    output_path: Path,
    on_amplitude: Any = None,
) -> Path:
    """Play XTTS output as it is generated, then save the whole take."""
    sample_rate = get_xtts_output_sample_rate(model)
    playback_plan = choose_output_playback_plan(
        config.speaker_device_index, sample_rate
    )

    chunk_queue: "queue.SimpleQueue[object]" = queue.SimpleQueue()
    producer_errors: list[Exception] = []
    producer_thread = threading.Thread(
        target=produce_xtts_stream_chunks,
        args=(text, config, state, model, chunk_queue, producer_errors),
        daemon=True,
    )
    producer_thread.start()

    # Build a head start before opening the device, so playback does not
    # underrun while the model is still warming up.
    pending_chunks, stream_finished = _prime_stream_buffer(
        chunk_queue, int(sample_rate * config.xtts_stream_buffer_seconds)
    )

    audio_stream = sd.OutputStream(
        samplerate=playback_plan.sample_rate,
        channels=1,
        dtype="float32",
        blocksize=_STREAM_BLOCKSIZE,
        latency="high",
        device=playback_plan.output_device_index,
    )
    resampler = (
        StreamingLinearResampler(sample_rate, playback_plan.sample_rate)
        if playback_plan.requires_resample
        else None
    )

    def write(samples: np.ndarray) -> None:
        if samples.size:
            audio_stream.write(
                np.ascontiguousarray(samples.reshape(-1, 1), dtype=np.float32)
            )

    audio_chunks: list[np.ndarray] = []
    try:
        audio_stream.start()

        while True:
            if pending_chunks:
                audio_chunk = pending_chunks.pop(0)
            elif stream_finished:
                break
            else:
                item = chunk_queue.get()
                if item is XTTS_STREAM_END:
                    break
                assert isinstance(item, np.ndarray)
                audio_chunk = item

            audio_chunks.append(audio_chunk)
            _emit_amplitude(on_amplitude, audio_chunk)
            write(
                resampler.process(audio_chunk)
                if resampler is not None
                else np.ascontiguousarray(audio_chunk, dtype=np.float32)
            )

        if resampler is not None:
            write(resampler.flush())
    finally:
        try:
            audio_stream.stop()
        except Exception:
            pass
        audio_stream.close()
        producer_thread.join()

    if producer_errors:
        raise RuntimeError(f"XTTS streaming failed. {producer_errors[0]}")

    return write_wav_audio(output_path, audio_chunks, sample_rate)


# --------------------------------------------------------------------------
# Speaking
# --------------------------------------------------------------------------


def speak_text(
    text: str,
    config: Config,
    state: SessionState,
    on_amplitude: Any = None,
) -> Path:
    cleaned_text = trim_text_for_tts(text, config.xtts_max_text_chars)

    # Per-language voicing: speak each reply in its own detected language so a
    # Japanese/Russian/etc. line isn't read with English phonetics. This
    # overrides config.tts_language for one synthesis and puts it back after.
    restore_language: str | None = None
    if getattr(config, "tts_auto_language", False):
        from .lang_detect import detect_language

        detected = detect_language(cleaned_text, config.tts_language)
        if detected and detected != config.tts_language:
            restore_language = config.tts_language
            config.tts_language = detected

    try:
        output_path = _speak_text_inner(cleaned_text, config, state, on_amplitude)
    finally:
        if restore_language is not None:
            config.tts_language = restore_language

    if config.rvc_chat_enabled:
        from .rvc import apply_rvc

        try:
            output_path = apply_rvc(output_path, config)
        except RuntimeError as exc:
            print(f"[RVC] Voice conversion skipped, using the plain TTS voice: {exc}")

    return output_path


def _speak_text_inner(
    cleaned_text: str,
    config: Config,
    state: SessionState,
    on_amplitude: Any = None,
) -> Path:
    if config.tts_provider == "bridge":
        from .bridge_voice import synthesize

        return synthesize(cleaned_text, config)

    if config.tts_provider == "gtts":
        return synthesize_gtts_to_file(
            cleaned_text, config, AUDIO_DIR / "latest_reply.mp3"
        )

    output_path = AUDIO_DIR / "latest_reply.wav"
    model = ensure_xtts_model(config, state)

    # Chat RVC needs to convert the whole rendered file before anything plays,
    # which live streaming can't do (it plays each chunk as it's generated) -
    # fall back to full-file synthesis whenever chat RVC is on.
    if config.xtts_stream_output and not config.rvc_chat_enabled:
        return stream_xtts_audio(
            cleaned_text, config, state, model, output_path, on_amplitude=on_amplitude
        )

    return synthesize_xtts_to_file(cleaned_text, config, state, model, output_path)


# --------------------------------------------------------------------------
# Playback
# --------------------------------------------------------------------------


def get_mci_error(error_code: int) -> str:
    buffer = ctypes.create_unicode_buffer(_MCI_ERROR_BUFFER_CHARS)
    ctypes.windll.winmm.mciGetErrorStringW(error_code, buffer, len(buffer))
    return buffer.value or f"MCI error {error_code}"


def _read_wav_as_float32(audio_path: Path) -> tuple[np.ndarray, int, int]:
    """Read a 16-bit PCM WAV into a (frames, channels) float32 array."""
    with wave.open(str(audio_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        raise RuntimeError(
            "Only 16-bit PCM WAV playback is supported for direct device output."
        )

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    shaped = audio.reshape(-1, channels) if channels > 1 else audio.reshape(-1, 1)
    return shaped, sample_rate, channels


def play_wav_with_sounddevice(
    audio_path: Path,
    output_device_index: int | None = None,
    on_amplitude: Any = None,
) -> None:
    audio, sample_rate, channels = _read_wav_as_float32(audio_path)

    playback_plan = choose_output_playback_plan(
        output_device_index, sample_rate, channels=channels
    )
    playback_audio = (
        resample_audio_for_output(audio, sample_rate, playback_plan.sample_rate)
        if playback_plan.requires_resample
        else np.ascontiguousarray(audio, dtype=np.float32)
    )

    try:
        if on_amplitude is not None:
            _play_blocks_with_amplitude(
                playback_audio,
                playback_plan.sample_rate,
                playback_plan.output_device_index,
                on_amplitude,
            )
            return

        sd.play(
            playback_audio,
            samplerate=playback_plan.sample_rate,
            device=playback_plan.output_device_index,
            blocking=True,
        )
    except Exception as exc:
        label = (
            "the default speaker"
            if output_device_index is None
            else f"speaker #{output_device_index}"
        )
        raise RuntimeError(f"Could not play audio on {label}. {exc}") from exc


def _play_blocks_with_amplitude(
    audio: np.ndarray,
    sample_rate: int,
    output_device_index: int | None,
    on_amplitude: Any,
) -> None:
    """Play audio in blocks, emitting an RMS amplitude per block for lip-sync."""
    data = np.ascontiguousarray(audio, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    block = max(_MIN_BLOCK_FRAMES, int(sample_rate * _BLOCK_SECONDS))
    stream = sd.OutputStream(
        samplerate=sample_rate,
        channels=data.shape[1],
        dtype="float32",
        device=output_device_index,
    )

    stream.start()
    try:
        for start in range(0, data.shape[0], block):
            frame = data[start : start + block]
            _emit_amplitude(on_amplitude, frame.reshape(-1))
            stream.write(frame)
    finally:
        try:
            stream.stop()
        except Exception:
            pass
        stream.close()
        try:
            on_amplitude(0.0)  # close the avatar's mouth
        except Exception:
            pass


def _play_with_mci(audio_path: Path) -> None:
    """Play audio via Windows MCI (Media Control Interface)."""
    winmm = ctypes.windll.winmm

    def send(command: str) -> None:
        error_code = winmm.mciSendStringW(command, None, 0, None)
        if error_code:
            raise RuntimeError(get_mci_error(error_code))

    def close_quietly() -> None:
        try:
            send(f"close {_MCI_ALIAS}")
        except RuntimeError:
            pass

    close_quietly()  # clear a handle left behind by an earlier play

    device_type = "waveaudio" if audio_path.suffix.lower() == ".wav" else "mpegvideo"
    try:
        send(f'open "{audio_path}" type {device_type} alias {_MCI_ALIAS}')
        send(f"play {_MCI_ALIAS} wait")
    finally:
        close_quietly()


def _play_with_ffplay(audio_path: Path) -> None:
    """Play audio via ffplay (cross-platform fallback)."""
    import shutil as _shutil
    import subprocess as _subprocess

    ffplay = _shutil.which("ffplay")
    if not ffplay:
        raise RuntimeError(
            "ffplay not found. Install FFmpeg to enable audio playback on Linux."
        )
    _subprocess.run(
        [ffplay, "-nodisp", "-autoexit", "-loglevel", "error", str(audio_path)],
        check=True,
    )


_FFMPEG_DECODE_RATE = 22050


def _decode_wav_mono(audio_path: Path) -> tuple[np.ndarray | None, int]:
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        return audio, sample_rate
    except Exception:
        return None, 0


def _decode_via_ffmpeg_mono(audio_path: Path) -> tuple[np.ndarray | None, int]:
    import shutil as _shutil
    import subprocess as _subprocess

    ffmpeg = _shutil.which("ffmpeg")
    if not ffmpeg:
        return None, 0

    try:
        out = _subprocess.run(
            [ffmpeg, "-v", "quiet", "-i", str(audio_path),
             "-f", "s16le", "-ac", "1", "-ar", str(_FFMPEG_DECODE_RATE), "-"],
            capture_output=True,
            check=True,
        ).stdout
        if not out:
            return None, 0
        samples = np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0
        return samples, _FFMPEG_DECODE_RATE
    except Exception:
        return None, 0


def _decode_audio_mono(audio_path: Path) -> tuple[np.ndarray | None, int]:
    """Decode an audio file to mono float32 samples + sample rate.

    WAV is read directly; other formats (e.g. gTTS .mp3) go through ffmpeg, which
    is already present whenever ffplay is used for fallback playback.
    """
    if audio_path.suffix.lower() == ".wav":
        return _decode_wav_mono(audio_path)
    return _decode_via_ffmpeg_mono(audio_path)


def _emit_amplitude_envelope(audio_path: Path, on_amplitude: Any) -> None:
    """Decode the file and emit its RMS envelope on a wall clock (~25 fps).

    Drives lip-sync when the actual playback happens in an external player
    (ffplay/MCI) that can't report amplitude itself. Runs in its own thread,
    started at the same time as playback so the envelope tracks the audio.
    """
    if on_amplitude is None:
        return

    samples, sample_rate = _decode_audio_mono(audio_path)
    if samples is None or samples.size == 0:
        return

    hop = max(1, int(sample_rate * _ENVELOPE_FRAME_SECONDS))
    block_count = max(1, samples.size // hop)
    started = time.monotonic()

    try:
        for index in range(block_count):
            # Pace against the wall clock so the envelope stays in step.
            wait = started + index * _ENVELOPE_FRAME_SECONDS - time.monotonic()
            if wait > 0:
                time.sleep(wait)

            block = samples[index * hop : (index + 1) * hop]
            if block.size == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
            on_amplitude(max(0.0, min(1.0, rms * _AMPLITUDE_GAIN)))
        on_amplitude(0.0)
    except Exception:
        pass


def play_audio_file(
    audio_path: Path,
    output_device_index: int | None = None,
    on_amplitude: Any = None,
) -> None:
    if audio_path.suffix.lower() == ".wav" and sd is not None:
        play_wav_with_sounddevice(audio_path, output_device_index, on_amplitude)
        return

    # No sounddevice/PortAudio (minimal install), or a non-WAV file (e.g. gTTS
    # .mp3): fall back to a system player. Those players can't report amplitude,
    # so drive lip-sync from a decoded RMS envelope on a parallel thread.
    envelope_thread: threading.Thread | None = None
    if on_amplitude is not None:
        envelope_thread = threading.Thread(
            target=_emit_amplitude_envelope,
            args=(audio_path, on_amplitude),
            daemon=True,
        )
        envelope_thread.start()

    try:
        if os.name == "nt":
            _play_with_mci(audio_path)
        else:
            _play_with_ffplay(audio_path)
    finally:
        if envelope_thread is not None:
            envelope_thread.join(timeout=0.1)


_ALERT_SOUND_ATTRS = {"danger": "danger_sound_path", "warning": "warning_sound_path"}


def play_alert_sound(level: str, config: Config) -> None:
    """Play a configured warning/danger cue; missing files are harmless."""
    attribute = _ALERT_SOUND_ATTRS.get(level)
    raw = getattr(config, attribute) if attribute else None

    path = resolve_optional_path(raw)
    if path and path.is_file():
        play_audio_file(path, config.speaker_device_index)
