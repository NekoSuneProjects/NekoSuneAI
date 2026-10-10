"""Opt-in Windows Android and YOLO asset manager; no silent installation."""
from __future__ import annotations
import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
YOLO_URL = "https://huggingface.co/webml/yolov8n/resolve/main/onnx/yolov8n.onnx"
YOLO_SHA256 = "190ba5f1e61411a001683e349d6b2cdb0804c0dc67a5e34cd8ff6fd00ee54b4d"
MAX_ZIP_BYTES = 40 * 1024 * 1024
MAX_MODEL_BYTES = 25 * 1024 * 1024


def find_adb(root: str | Path, configured: str = "") -> str:
    for candidate in (configured, str(Path(root) / "platform-tools" / "adb.exe"),
                      shutil.which("adb") or ""):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return ""


def _download(url: str, output: Path, limit: int) -> str:
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=30) as response, output.open("wb") as stream:
        if response.geturl().split("/", 3)[2].lower() not in (
            "dl.google.com", "huggingface.co", "cas-bridge.xethub.hf.co",
            "cdn-lfs.hf.co", "cas-server.xethub.hf.co"):
            raise ValueError("Download redirected outside trusted hosts")
        size = 0
        while chunk := response.read(256 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError("Download exceeds size limit")
            stream.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def install_platform_tools(root: str | Path) -> str:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        archive = Path(tmp) / "adb.zip"
        _download(PLATFORM_TOOLS_URL, archive, MAX_ZIP_BYTES)
        staging = Path(tmp) / "stage"
        staging.mkdir()
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if not members or sum(x.file_size for x in members) > 100 * 1024 * 1024:
                raise ValueError("Invalid platform-tools archive size")
            for item in members:
                parts = Path(item.filename).parts
                if (not parts or parts[0] != "platform-tools" or ".." in parts
                        or item.filename.startswith(("/", "\\"))):
                    raise ValueError("Unsafe platform-tools archive entry")
            z.extractall(staging)
        extracted = staging / "platform-tools"
        if not (extracted / "adb.exe").is_file():
            raise ValueError("Platform-tools archive does not contain adb.exe")
        dest = root / "platform-tools"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(extracted), str(dest))
    return str((root / "platform-tools" / "adb.exe").resolve())


def install_yolo_model(root: str | Path) -> str:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    model = root / "yolov8n.onnx"
    if model.is_file() and hashlib.sha256(model.read_bytes()).hexdigest() == YOLO_SHA256:
        return str(model.resolve())
    with tempfile.TemporaryDirectory(dir=root) as temp:
        download = Path(temp) / "model.onnx"
        digest = _download(YOLO_URL, download, MAX_MODEL_BYTES)
        if digest != YOLO_SHA256:
            raise ValueError("YOLOv8 ONNX SHA256 mismatch")
        os.replace(download, model)
    return str(model.resolve())


def discover_bluestacks(adb: str, ports=(5555, 5556, 5565, 5575)):
    """Localhost-only ADB probes: never scan the LAN."""
    if not adb or not Path(adb).is_file():
        return []
    found = []
    try:
        existing = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=8)
        for line in existing.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                found.append(parts[0])
    except (OSError, subprocess.TimeoutExpired):
        return []
    for port in ports:
        serial = f"127.0.0.1:{int(port)}"
        if serial in found:
            continue
        try:
            subprocess.run([adb, "connect", serial], capture_output=True, timeout=3)
            probe = subprocess.run([adb, "-s", serial, "get-state"], capture_output=True,
                                   text=True, timeout=3)
            if probe.returncode == 0 and probe.stdout.strip() == "device":
                found.append(serial)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return found
