"""Read-only hardware video encoder capability probe.

An encoder being listed by FFmpeg does not guarantee GPU initialization.
For screenshot OCR/YOLO use ONNX providers instead; this probe is for future
video transport selection and does not open a camera or perform encoding.
"""
from __future__ import annotations
import shutil
import subprocess

CANDIDATES = ("h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv",
              "h264_amf", "hevc_amf")

def probe_encoders(ffmpeg=None):
    executable = ffmpeg or shutil.which("ffmpeg")
    if not executable:
        return {"available": [], "preferred": None,
                "reason": "FFmpeg not installed"}
    try:
        output = subprocess.run(
            [executable, "-hide_banner", "-encoders"],
            text=True, capture_output=True, timeout=5, check=False)
        if output.returncode:
            return {"available": [], "preferred": None,
                    "reason": "FFmpeg encoder listing failed"}
        available = [codec for codec in CANDIDATES
                     if any(line.split()[-1] == codec
                            for line in output.stdout.splitlines()
                            if len(line.split()) == 2)]
        return {"available": available,
                "preferred": available[0] if available else None,
                "reason": "An advertised encoder still requires runtime initialization"}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": [], "preferred": None,
                "reason": "FFmpeg probe unavailable"}
