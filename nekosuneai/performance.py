"""Hardware detection and automatic runtime tuning.

Inspects the host once at start-up, grades it into a coarse tier, and picks the
model sizes, decode budgets and buffer depths that tier can actually sustain,
so the same image behaves sensibly on a Raspberry Pi and on a desktop with a
discrete GPU.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

try:
    import torch
except ImportError:  # torch is an optional voice/GPU extra; absent on minimal installs
    torch = None  # type: ignore[assignment]

_BYTES_PER_GB = 1024**3


@dataclass(frozen=True)
class SystemCapabilities:
    cpu_cores: int
    total_ram_gb: float | None
    has_cuda: bool
    gpu_name: str | None
    gpu_vram_gb: float | None


@dataclass(frozen=True)
class PerformanceProfile:
    goal: str
    tier: str
    ollama_num_predict: int
    xtts_use_gpu: bool
    xtts_stream_chunk_size: int
    xtts_stream_buffer_seconds: float
    stt_use_gpu: bool
    stt_model: str
    stt_compute_type: str
    stt_beam_size: int
    stt_best_of: int
    request_timeout: int
    mic_chunk_size: int
    notes: tuple[str, ...]

    @property
    def name(self) -> str:
        return f"{self.goal}-{self.tier}"


# --------------------------------------------------------------------------
# Goal parsing
# --------------------------------------------------------------------------

_GOAL_ALIASES = {
    "quality": "quality",
    "best": "quality",
    "max": "quality",
    "speed": "speed",
    "fast": "speed",
    "latency": "speed",
}
_DEFAULT_GOAL = "balanced"


def normalize_auto_tune_goal(value: str) -> str:
    return _GOAL_ALIASES.get(value.strip().lower(), _DEFAULT_GOAL)


# --------------------------------------------------------------------------
# Hardware detection
# --------------------------------------------------------------------------


class _Win32MemoryStatusEx(ctypes.Structure):
    """Layout of the Win32 MEMORYSTATUSEX struct."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_total_memory_bytes() -> int | None:
    status = _Win32MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_Win32MemoryStatusEx)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return int(status.ullTotalPhys)
    return None


def _posix_total_memory_bytes() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        return None

    if not (isinstance(pages, int) and isinstance(page_size, int)):
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return pages * page_size


def _get_total_memory_bytes() -> int | None:
    if os.name == "nt":
        return _windows_total_memory_bytes()
    return _posix_total_memory_bytes()


def _as_gb(total_bytes: int | None) -> float | None:
    if total_bytes is None or total_bytes <= 0:
        return None
    return round(total_bytes / _BYTES_PER_GB, 1)


def _get_primary_gpu_info() -> tuple[bool, str | None, float | None]:
    if torch is None or not torch.cuda.is_available():
        return False, None, None

    try:
        props = torch.cuda.get_device_properties(0)
    except Exception:
        return True, "CUDA GPU", None

    total_memory = getattr(props, "total_memory", 0)
    vram_gb = _as_gb(total_memory) if isinstance(total_memory, int) else None
    return True, str(getattr(props, "name", "CUDA GPU")), vram_gb


def detect_system_capabilities() -> SystemCapabilities:
    has_cuda, gpu_name, gpu_vram_gb = _get_primary_gpu_info()
    return SystemCapabilities(
        cpu_cores=max(1, os.cpu_count() or 1),
        total_ram_gb=_as_gb(_get_total_memory_bytes()),
        has_cuda=has_cuda,
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram_gb,
    )


def describe_system_capabilities(capabilities: SystemCapabilities) -> str:
    parts = [f"{capabilities.cpu_cores} CPU threads"]

    if capabilities.total_ram_gb is not None:
        parts.append(f"{capabilities.total_ram_gb:.1f} GB RAM")

    if capabilities.gpu_name:
        gpu = capabilities.gpu_name
        if capabilities.gpu_vram_gb is not None:
            gpu = f"{gpu} ({capabilities.gpu_vram_gb:.1f} GB VRAM)"
        parts.append(gpu)
    else:
        parts.append("no CUDA GPU detected")

    return " | ".join(parts)


# --------------------------------------------------------------------------
# Tier classification
# --------------------------------------------------------------------------

# Descending (minimum, points) ladders; the first row a value clears wins.
_CORE_POINTS = ((12, 2.0), (8, 1.5), (4, 1.0))
_RAM_POINTS = ((32, 2.0), (16, 1.5), (8, 1.0))
_VRAM_POINTS = ((10, 2.5), (8, 2.0), (6, 1.5), (4, 1.0))

# Awarded when CUDA is present but VRAM could not be measured, and when a
# measured card is smaller than the smallest VRAM row above.
_CUDA_UNKNOWN_VRAM_POINTS = 1.0
_CUDA_TINY_VRAM_POINTS = 0.5

_TIER_THRESHOLDS = (("high", 5.0), ("medium", 2.75))
_FALLBACK_TIER = "low"


def _ladder_points(
    value: float,
    ladder: tuple[tuple[int, float], ...],
    floor: float = 0.0,
) -> float:
    for minimum, points in ladder:
        if value >= minimum:
            return points
    return floor


def _gpu_points(capabilities: SystemCapabilities) -> float:
    if not capabilities.has_cuda:
        return 0.0
    if capabilities.gpu_vram_gb is None:
        return _CUDA_UNKNOWN_VRAM_POINTS
    return _ladder_points(
        capabilities.gpu_vram_gb, _VRAM_POINTS, floor=_CUDA_TINY_VRAM_POINTS
    )


def classify_hardware_tier(capabilities: SystemCapabilities) -> str:
    score = _ladder_points(capabilities.cpu_cores, _CORE_POINTS)
    if capabilities.total_ram_gb is not None:
        score += _ladder_points(capabilities.total_ram_gb, _RAM_POINTS)
    score += _gpu_points(capabilities)

    for tier, minimum in _TIER_THRESHOLDS:
        if score >= minimum:
            return tier
    return _FALLBACK_TIER


# --------------------------------------------------------------------------
# Tuning presets
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _TuningPreset:
    """The knobs a single (goal, tier) combination settles on."""

    ollama_num_predict: int
    xtts_stream_chunk_size: int
    xtts_stream_buffer_seconds: float
    stt_model: str
    stt_beam_size: int
    stt_best_of: int
    request_timeout: int
    mic_chunk_size: int


# Keyed by (goal, tier). Read down a goal to see how each knob opens up as the
# hardware improves; read across a tier to see what each goal trades away.
_PRESETS: dict[tuple[str, str], _TuningPreset] = {
    ("speed", "low"): _TuningPreset(450, 14, 2.4, "base.en", 2, 2, 240, 2048),
    ("speed", "medium"): _TuningPreset(700, 18, 1.8, "small.en", 3, 3, 300, 1024),
    ("speed", "high"): _TuningPreset(900, 24, 1.2, "small.en", 3, 3, 360, 1024),
    ("balanced", "low"): _TuningPreset(600, 16, 2.3, "base.en", 3, 3, 300, 2048),
    ("balanced", "medium"): _TuningPreset(1000, 20, 1.8, "small.en", 4, 4, 360, 1024),
    ("balanced", "high"): _TuningPreset(1400, 28, 1.2, "medium.en", 5, 5, 420, 1024),
    ("quality", "low"): _TuningPreset(750, 16, 2.4, "small.en", 4, 4, 360, 2048),
    ("quality", "medium"): _TuningPreset(1400, 24, 1.8, "medium.en", 5, 5, 420, 1024),
    ("quality", "high"): _TuningPreset(1800, 30, 1.2, "medium.en", 6, 6, 480, 1024),
}


def _profile_defaults(goal: str, tier: str) -> dict[str, float | int | str]:
    """The preset for a (goal, tier) pair, as a plain mapping."""
    preset = _PRESETS[(goal, tier)]
    return {
        "ollama_num_predict": preset.ollama_num_predict,
        "xtts_stream_chunk_size": preset.xtts_stream_chunk_size,
        "xtts_stream_buffer_seconds": preset.xtts_stream_buffer_seconds,
        "stt_model": preset.stt_model,
        "stt_beam_size": preset.stt_beam_size,
        "stt_best_of": preset.stt_best_of,
        "request_timeout": preset.request_timeout,
        "mic_chunk_size": preset.mic_chunk_size,
    }


# --------------------------------------------------------------------------
# Profile assembly
# --------------------------------------------------------------------------

_MIN_VRAM_GB_FOR_STT = 6.0
_MIN_RAM_GB_FOR_MEDIUM_ON_CPU = 24
_MIN_RAM_GB_FOR_SMALL_ON_CPU = 10


def _stt_can_use_gpu(capabilities: SystemCapabilities) -> bool:
    if not capabilities.has_cuda:
        return False
    vram = capabilities.gpu_vram_gb
    return vram is None or vram >= _MIN_VRAM_GB_FOR_STT


def _downgrade_stt_model_for_cpu(
    model: str, capabilities: SystemCapabilities
) -> str:
    """Step the Whisper model down when it would not fit in host RAM."""
    ram = capabilities.total_ram_gb

    if model == "medium.en" and (ram is None or ram < _MIN_RAM_GB_FOR_MEDIUM_ON_CPU):
        model = "small.en"
    if model == "small.en" and ram is not None and ram < _MIN_RAM_GB_FOR_SMALL_ON_CPU:
        model = "base.en"
    return model


def _build_notes(
    preset: _TuningPreset,
    stt_model: str,
    stt_use_gpu: bool,
    stt_compute_type: str,
    xtts_use_gpu: bool,
) -> tuple[str, ...]:
    stt_device = "cuda" if stt_use_gpu else "cpu"
    xtts_device = "cuda" if xtts_use_gpu else "cpu"
    return (
        f"Ollama reply budget set to {preset.ollama_num_predict} tokens.",
        f"Speech recognition uses {stt_model} on "
        f"{stt_device}/{stt_compute_type}.",
        f"XTTS runs on {xtts_device} with "
        f"chunk size {preset.xtts_stream_chunk_size} "
        f"and a {preset.xtts_stream_buffer_seconds:.1f}s buffer.",
        f"Microphone chunk size set to {preset.mic_chunk_size}.",
    )


def choose_performance_profile(
    capabilities: SystemCapabilities,
    goal: str,
) -> PerformanceProfile:
    normalized_goal = normalize_auto_tune_goal(goal)
    tier = classify_hardware_tier(capabilities)
    preset = _PRESETS[(normalized_goal, tier)]

    xtts_use_gpu = capabilities.has_cuda
    stt_use_gpu = _stt_can_use_gpu(capabilities)

    stt_model = preset.stt_model
    if not stt_use_gpu:
        stt_model = _downgrade_stt_model_for_cpu(stt_model, capabilities)
    stt_compute_type = "float16" if stt_use_gpu else "int8"

    return PerformanceProfile(
        goal=normalized_goal,
        tier=tier,
        ollama_num_predict=preset.ollama_num_predict,
        xtts_use_gpu=xtts_use_gpu,
        xtts_stream_chunk_size=preset.xtts_stream_chunk_size,
        xtts_stream_buffer_seconds=preset.xtts_stream_buffer_seconds,
        stt_use_gpu=stt_use_gpu,
        stt_model=stt_model,
        stt_compute_type=stt_compute_type,
        stt_beam_size=preset.stt_beam_size,
        stt_best_of=preset.stt_best_of,
        request_timeout=preset.request_timeout,
        mic_chunk_size=preset.mic_chunk_size,
        notes=_build_notes(
            preset, stt_model, stt_use_gpu, stt_compute_type, xtts_use_gpu
        ),
    )
