"""Song rendering.

Takes lyrics - optionally alongside a melody or vocal reference - and produces
a sung clip on disk. Playback then goes through the ordinary audio path, which
means the avatar's amplitude-driven lip sync picks it up with no extra work.

Three backends sit behind one Protocol:

``CloudSingingEngine``
    Posts to a hosted singing endpoint. The dependable default, and the only
    sensible option on a machine without much GPU to spare.
``RvcSingingEngine``
    Local RVC voice conversion applied to a reference vocal. Heavy, and its
    dependencies are optional and imported lazily.
``LocalSingingEngine``
    Timed talk-singing: pull synced lyrics, perform them on the song's own
    timing with the regular XTTS voice, optionally over a backing track.

``make_singing_engine`` picks one, degrading to cloud whenever local RVC is
not actually viable on this host.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

import requests

from .config import Config
from .paths import AUDIO_DIR, SONGS_DIR


class SingingError(RuntimeError):
    pass


# YouTube backing tracks arrive as webm/opus/m4a and even a gTTS render is mp3.
# torchaudio cannot open any of those without a backend, whereas ffmpeg decodes
# (and resamples) all of them the same way, so it is the path we rely on.
FFMPEG_HINT = (
    "Install ffmpeg so NekoSuneAI can read YouTube/compressed audio and merge it with "
    "the voice. Easiest: `pip install imageio-ffmpeg` (bundles a binary, no system "
    "install). Or install ffmpeg and put it on PATH / set FFMPEG_PATH."
)

_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")
_URL_PREFIX = re.compile(r"https?://", re.IGNORECASE)
_SLUG_MAX_LEN = 80
_FALLBACK_SLUG = "song"

# Extensions a cached download may already be sitting under.
_CACHED_AUDIO_SUFFIXES = (".m4a", ".webm", ".mp3", ".opus", ".wav")

_MIX_SAMPLE_RATE = 44100
_BACKING_GAIN = 0.5
_VOCAL_GAIN = 0.95
_MIN_RVC_VRAM_GB = 4.0


def _slugify(text: str) -> str:
    """A safe, stable filename for a song query (so we can cache + replay)."""
    collapsed = _SLUG_SEPARATORS.sub("_", (text or "").lower()).strip("_")
    return (collapsed or _FALLBACK_SLUG)[:_SLUG_MAX_LEN]


def _is_url(ref: str) -> bool:
    return _URL_PREFIX.match((ref or "").strip()) is not None


# --------------------------------------------------------------------------
# ffmpeg discovery
# --------------------------------------------------------------------------


def _ffmpeg_from_env() -> str | None:
    candidate = os.getenv("FFMPEG_PATH") or os.getenv("FFMPEG_BINARY")
    return candidate if candidate and Path(candidate).exists() else None


def _ffmpeg_from_path() -> str | None:
    return shutil.which("ffmpeg")


def _ffmpeg_from_imageio() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


_FFMPEG_RESOLVERS: tuple[Callable[[], str | None], ...] = (
    _ffmpeg_from_env,
    _ffmpeg_from_path,
    _ffmpeg_from_imageio,
)


def ffmpeg_exe() -> str | None:
    """Locate an ffmpeg binary: FFMPEG_PATH env, PATH, or the imageio-ffmpeg one."""
    for resolve in _FFMPEG_RESOLVERS:
        found = resolve()
        if found:
            return found
    return None


def _ydl_to_wav(opts: dict) -> dict:
    """Ask yt-dlp to transcode to wav when ffmpeg exists.

    Doing it at download time means a replay can decode the cached file with no
    ffmpeg present at all.
    """
    binary = ffmpeg_exe()
    if binary:
        opts["ffmpeg_location"] = binary
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav"}
        ]
    return opts


# --------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------


def _resample(mono, src_sr: int, dst_sr: int):
    import numpy as np

    if src_sr == dst_sr or len(mono) == 0:
        return mono
    target_len = int(len(mono) * dst_sr / src_sr)
    positions = np.linspace(0, len(mono) - 1, target_len)
    return np.interp(positions, np.arange(len(mono)), mono).astype(np.float32)


def _decode_via_ffmpeg(path: Path, target_sr: int):
    """Most robust route: ffmpeg handles every container and resamples in one pass."""
    import numpy as np

    binary = ffmpeg_exe()
    if not binary:
        return None

    try:
        result = subprocess.run(
            [binary, "-v", "error", "-i", str(path), "-ac", "1",
             "-ar", str(target_sr), "-f", "f32le", "-"],
            capture_output=True,
        )
    except Exception:
        return None

    if result.returncode != 0 or not result.stdout:
        return None
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


# Sample width in bytes -> (numpy dtype, zero offset, full-scale divisor).
_WAV_PCM_FORMATS: dict[int, tuple[Any, float, float]] = {}


def _wav_pcm_formats() -> dict[int, tuple[Any, float, float]]:
    import numpy as np

    if not _WAV_PCM_FORMATS:
        _WAV_PCM_FORMATS.update(
            {
                1: (np.uint8, 128.0, 128.0),
                4: (np.int32, 0.0, 2147483648.0),
                2: (np.int16, 0.0, 32768.0),
            }
        )
    return _WAV_PCM_FORMATS


def _decode_via_wave(path: Path, target_sr: int):
    """Stdlib WAV reader, so user-supplied .wav works with no ffmpeg at all."""
    if path.suffix.lower() != ".wav":
        return None

    import wave

    import numpy as np

    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            frame_rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())

        dtype, offset, divisor = _wav_pcm_formats().get(
            sample_width, _wav_pcm_formats()[2]
        )
        samples = (np.frombuffer(raw, dtype).astype(np.float32) - offset) / divisor
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        return _resample(samples, frame_rate, target_sr)
    except Exception:
        return None


def _decode_via_torchaudio(path: Path, target_sr: int):
    """Last resort, and only works when torchaudio found a usable backend."""
    import numpy as np

    try:
        import torchaudio

        waveform, source_sr = torchaudio.load(str(path))
        mono = waveform.mean(dim=0).numpy().astype(np.float32)
        return _resample(mono, source_sr, target_sr)
    except Exception:
        return None


_DECODERS: tuple[Callable[[Path, int], Any], ...] = (
    _decode_via_ffmpeg,
    _decode_via_wave,
    _decode_via_torchaudio,
)


def decode_audio_mono(path: str | Path, target_sr: int):
    """Decode any audio file to a mono float32 array at ``target_sr``.

    Each decoder is tried in turn and the first one to produce samples wins.
    Raises :class:`SingingError` when none of them can read the file.
    """
    source = Path(path)
    if not source.exists():
        raise SingingError(f"Audio file not found: {source}")

    for decode in _DECODERS:
        samples = decode(source, target_sr)
        if samples is not None:
            return samples

    raise SingingError(f"Couldn't decode '{source.name}'. {FFMPEG_HINT}")


# --------------------------------------------------------------------------
# Backing-track acquisition
# --------------------------------------------------------------------------


def _backing_cache_dir() -> Path:
    cache = SONGS_DIR / "backing"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _cached_download(base: Path) -> Path | None:
    for suffix in _CACHED_AUDIO_SUFFIXES:
        candidate = base.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def _yt_dlp_fetch(
    target: str,
    stem: str,
    timeout: int,
    extra_opts: dict | None = None,
) -> Path | None:
    """Download ``target`` into the backing cache under ``stem``.

    Shared by the pasted-URL and instrumental-search paths, which differ only in
    what they hand yt-dlp. Returns the cached file, or None when yt-dlp is
    missing or the download failed - callers treat that as best-effort.
    """
    try:
        import yt_dlp  # type: ignore
    except Exception:
        return None

    cache = _backing_cache_dir()
    base = cache / stem

    already = _cached_download(base)
    if already is not None:
        return already

    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(base) + ".%(ext)s",
        "socket_timeout": timeout,
    }
    if extra_opts:
        opts.update(extra_opts)
    _ydl_to_wav(opts)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([target])
    except Exception:
        return None

    for produced in cache.glob(stem + ".*"):
        return produced
    return None


def download_audio_url(url: str, timeout: int = 120) -> Path | None:
    """Cache the audio behind a URL the user pasted as their own backing track."""
    return _yt_dlp_fetch(url, _slugify(url) + "_url", timeout)


def fetch_instrumental(query: str, timeout: int = 90) -> Path | None:
    """Search YouTube for an instrumental of ``query`` and cache it.

    Entirely optional: singing still works when nothing is found.
    """
    return _yt_dlp_fetch(
        f"{query} Instrumental Version",
        _slugify(query) + "_instrumental",
        timeout,
        {"default_search": "ytsearch1"},
    )


# --------------------------------------------------------------------------
# Engines
# --------------------------------------------------------------------------


class SingingEngine(Protocol):
    def sing(self, lyrics: str, melody_ref: str | None = None) -> Path:
        ...


def _vram_gb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return 0.0
        return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception:
        return None


def _song_output_path() -> Path:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    return AUDIO_DIR / "song.wav"


class CloudSingingEngine:
    """Delegates the whole render to a hosted singing API."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.singing_api_key:
            headers["Authorization"] = f"Bearer {self.config.singing_api_key}"
        return headers

    def sing(self, lyrics: str, melody_ref: str | None = None) -> Path:
        url = self.config.singing_api_url
        if not url:
            raise SingingError(
                "No singing API configured. Set SINGING_API_URL (and SINGING_API_KEY) in .env."
            )

        payload: dict[str, str] = {"lyrics": lyrics}
        if melody_ref:
            payload["melody_ref"] = melody_ref

        try:
            response = requests.post(
                url, json=payload, headers=self._headers(), timeout=120
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SingingError(f"Singing API request failed: {exc}") from exc

        output = _song_output_path()
        if "application/json" in response.headers.get("Content-Type", ""):
            output.write_bytes(self._follow_audio_url(response.json()))
        else:
            output.write_bytes(response.content)
        return output

    def _follow_audio_url(self, body: dict) -> bytes:
        """A JSON reply points at the rendered audio rather than inlining it."""
        audio_url = body.get("url") or body.get("audio_url")
        if not audio_url:
            raise SingingError("Singing API returned JSON without an audio URL.")
        audio = requests.get(audio_url, timeout=120)
        audio.raise_for_status()
        return audio.content


class RvcSingingEngine:
    """Local RVC voice-conversion. Requires a melody/vocal reference to convert."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def _resolve_reference(self, melody_ref: str | None) -> Path:
        if not melody_ref:
            raise SingingError(
                "Local RVC singing needs a melody/vocal reference (a .wav of the song's "
                "vocals or an acapella) to convert into NekoSuneAI's voice. Provide melody_ref, "
                "or switch SINGING_BACKEND=cloud."
            )

        reference = Path(melody_ref)
        if not reference.is_absolute():
            from .paths import ROOT_DIR

            reference = ROOT_DIR / melody_ref
        if not reference.exists():
            raise SingingError(f"Melody reference not found: {reference}")
        return reference

    def sing(self, lyrics: str, melody_ref: str | None = None) -> Path:
        reference = self._resolve_reference(melody_ref)
        if not self.config.rvc_model_path:
            raise SingingError(
                "Set RVC_MODEL_PATH in .env to your trained RVC model (.pth)."
            )

        try:
            # Lazy import - RVC packaging is platform-sensitive and optional.
            from rvc_python.infer import RVCInference  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dep
            raise SingingError(
                "RVC is not installed. Install an RVC inference package (e.g. rvc-python) "
                "or use SINGING_BACKEND=cloud."
            ) from exc

        output = _song_output_path()
        try:
            RVCInference(model_path=self.config.rvc_model_path).infer_file(
                str(reference), str(output)
            )
        except Exception as exc:
            raise SingingError(f"RVC inference failed: {exc}") from exc
        return output


class LocalSingingEngine:
    """Fully local sing-along, with no cloud call and no trained model.

    Synced lyrics come from LRCLIB and the ordinary XTTS voice performs them on
    the song's own timing, optionally mixed under a backing track. XTTS is not
    pitched, so the result is expressive on-beat talk-singing rather than true
    melodic singing - but it runs on a modest GPU.
    """

    LRC_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)")

    def __init__(self, config: Config) -> None:
        self.config = config

    # -- lyrics ------------------------------------------------------------

    def _fetch_synced_lyrics(self, query: str) -> list[tuple[float, str]] | None:
        try:
            response = requests.get(
                "https://lrclib.net/api/search",
                params={"q": query},
                headers={"User-Agent": "NekoSuneAI"},
                timeout=15,
            )
            response.raise_for_status()
            for entry in response.json():
                synced = entry.get("syncedLyrics")
                if synced:
                    return self._parse_lrc(synced)
        except Exception:
            return None
        return None

    def _parse_lrc(self, lrc: str) -> list[tuple[float, str]]:
        cues: list[tuple[float, str]] = []
        for line in lrc.splitlines():
            match = self.LRC_RE.match(line.strip())
            if not match:
                continue
            text = match.group(3).strip()
            if not text:
                continue
            seconds = int(match.group(1)) * 60 + float(match.group(2))
            cues.append((seconds, text))
        return cues

    # -- rendering ---------------------------------------------------------

    def _render_line(self, text, model, state, sample_rate):
        import wave

        import numpy as np

        from .tts import synthesize_xtts_to_file

        scratch = AUDIO_DIR / "_sing_line.wav"
        synthesize_xtts_to_file(text, self.config, state, model, scratch)
        with wave.open(str(scratch), "rb") as handle:
            pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0

    def _lay_out_timed_lines(self, rendered: Iterable[tuple[float, Any]], sr: int):
        """Place each rendered line at its cue time on one continuous track."""
        import numpy as np

        rendered = list(rendered)
        last_start, last_audio = rendered[-1]
        total_samples = int((last_start + len(last_audio) / sr + 1.0) * sr)
        track = np.zeros(max(total_samples, 1), dtype=np.float32)

        for start_seconds, audio in rendered:
            start = int(start_seconds * sr)
            end = min(start + len(audio), len(track))
            track[start:end] += audio[: end - start]
        return track

    # -- backing -----------------------------------------------------------

    def _resolve_backing(
        self, melody_ref: str | None, query: str
    ) -> tuple[str | None, bool]:
        """Pick the backing track, and say whether the user asked for it by name.

        The boolean is True when a path or URL was supplied explicitly. Those
        failing to decode is worth raising; an auto-discovered instrumental
        failing is not, and quietly becomes an a cappella render.
        """
        if melody_ref and melody_ref.strip():
            reference = melody_ref.strip()
            if not _is_url(reference):
                return reference, True  # local path; decoding validates it

            downloaded = download_audio_url(reference)
            if not downloaded:
                raise SingingError(
                    f"Couldn't download that backing track from YouTube. "
                    f"Make sure yt-dlp is installed (pip install yt-dlp). {FFMPEG_HINT}"
                )
            return str(downloaded), True

        if self.config.singing_fetch_instrumental:
            found = fetch_instrumental(query)
            if found:
                return str(found), False
        return None, False

    def _mix_backing(self, vocal, sr, melody_ref, explicit: bool = False):
        import numpy as np

        if not melody_ref:
            return vocal

        path = Path(melody_ref)
        if not path.is_absolute():
            from .paths import ROOT_DIR

            path = ROOT_DIR / melody_ref
        if not path.exists():
            if explicit:
                raise SingingError(f"Backing track not found: {path}")
            return vocal

        try:
            backing = decode_audio_mono(path, sr)
        except SingingError:
            if explicit:
                raise  # the user chose this track, so tell them why it failed
            return vocal  # auto-found instrumental: fall back to a cappella

        mixed = np.zeros(max(len(vocal), len(backing)), dtype=np.float32)
        mixed[: len(backing)] += backing * _BACKING_GAIN
        mixed[: len(vocal)] += vocal * _VOCAL_GAIN
        return mixed

    def _finalise(self, track, sr: int, destination: Path) -> Path:
        import numpy as np

        from .tts import write_wav_audio

        np.clip(track, -1.0, 1.0, out=track)
        return write_wav_audio(destination, [track], sr)

    def _mix_files(
        self, vocal_path: Path, backing_path: str, out_base: Path, explicit: bool
    ) -> Path | None:
        """Decode a rendered vocal file plus a backing track into one mixed wav."""
        try:
            vocal = decode_audio_mono(vocal_path, _MIX_SAMPLE_RATE)
        except SingingError:
            if explicit:
                raise
            return None

        track = self._mix_backing(vocal, _MIX_SAMPLE_RATE, backing_path, explicit)
        return self._finalise(track, _MIX_SAMPLE_RATE, out_base.with_suffix(".wav"))

    # -- backends ----------------------------------------------------------

    def _sing_gtts(
        self, lyrics: str, out_base: Path, melody_ref: str | None = None
    ) -> Path:
        """Render lyrics to mp3 via gTTS, then mix in a backing track if there is one."""
        from .tts import synthesize_gtts_to_file

        timed = self._fetch_synced_lyrics(lyrics)
        text = " \n".join(line for _cue, line in timed) if timed else lyrics

        vocal_mp3 = out_base.with_suffix(".mp3")
        synthesize_gtts_to_file(text, self.config, vocal_mp3)

        backing, explicit = self._resolve_backing(melody_ref, lyrics)
        if not backing:
            return vocal_mp3
        return self._mix_files(vocal_mp3, backing, out_base, explicit) or vocal_mp3

    def _cached_render(self, out_base: Path) -> Path | None:
        """gTTS leaves a mixed .wav when there was a backing track, else a bare .mp3."""
        for suffix in (".wav", ".mp3"):
            candidate = out_base.with_suffix(suffix)
            if candidate.exists():
                return candidate
        return None

    def sing(self, lyrics: str, melody_ref: str | None = None) -> Path:
        from .models import SessionState
        from .tts import ensure_xtts_model, get_xtts_output_sample_rate

        # Renders are cached under the query slug so a repeat replays instantly.
        out_base = SONGS_DIR / _slugify(lyrics)

        if self.config.tts_provider == "gtts":
            cached = self._cached_render(out_base)
            return cached or self._sing_gtts(lyrics, out_base, melody_ref)

        destination = out_base.with_suffix(".wav")
        if destination.exists():
            return destination

        timed = self._fetch_synced_lyrics(lyrics)
        state = SessionState(voice_enabled=True, input_mode="text")
        try:
            model = ensure_xtts_model(self.config, state)
        except Exception as exc:
            raise SingingError(f"Couldn't load the XTTS voice: {exc}") from exc
        sr = get_xtts_output_sample_rate(model)

        if timed:
            track = self._lay_out_timed_lines(
                ((cue, self._render_line(line, model, state, sr)) for cue, line in timed),
                sr,
            )
        else:
            # Nothing synced turned up, so perform the text straight through.
            track = self._render_line(lyrics, model, state, sr)

        # Backing is an explicit path, a URL the user pasted, or an auto-found
        # instrumental; all three end up merged into this single output file.
        backing, explicit = self._resolve_backing(melody_ref, lyrics)
        track = self._mix_backing(track, sr, backing, explicit)
        return self._finalise(track, sr, destination)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

_DIRECT_BACKENDS: dict[str, Callable[[Config], Any]] = {
    "local": LocalSingingEngine,
    "cloud": CloudSingingEngine,
}


def _rvc_is_viable(config: Config) -> bool:
    """RVC needs both a trained model and a card big enough to run it."""
    if not config.rvc_model_path:
        return False
    vram = _vram_gb()
    return not (vram is not None and 0 < vram < _MIN_RVC_VRAM_GB)


def make_singing_engine(config: Config) -> SingingEngine:
    """Choose a backend, falling back to cloud when local RVC isn't viable."""
    direct = _DIRECT_BACKENDS.get(config.singing_backend)
    if direct is not None:
        return direct(config)

    # backend == "rvc": only honour it when the host can actually deliver.
    if not _rvc_is_viable(config) and config.singing_api_url:
        return CloudSingingEngine(config)
    return RvcSingingEngine(config)
