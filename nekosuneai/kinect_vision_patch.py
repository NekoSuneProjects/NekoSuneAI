from __future__ import annotations

import ctypes
import ctypes.util
import threading
import time
from typing import Any

_INSTALLED = False
_SERVICE = None


def _saved() -> dict[str, Any]:
    try:
        from .settings_dashboard_patch import _read_saved_app_settings
        return _read_saved_app_settings()
    except Exception:
        return {}


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class KinectVisionService:
    """Local Xbox 360 Kinect RGB vision using libfreenect's synchronous API.

    Frames are kept in memory only. The small local affect detector receives a
    face crop; the configured vision model can add visible posture/gesture
    context. Both outputs are explicitly tentative visual cues.
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lib = None
        self._core = None
        self._last_context = ""
        self._last_error = ""
        self._last_frame_at = 0.0
        self._running = False
        self._affect = None
        self._consecutive_failures = 0

    def _settings(self) -> dict[str, Any]:
        s = _saved()
        return {
            "enabled": _bool(s.get("kinect_vision_enabled"), True),
            "interval": max(1.0, float(s.get("kinect_vision_interval_seconds", 4.0) or 4.0)),
            "device": max(0, int(s.get("kinect_device_index", 0) or 0)),
            "describe": _bool(s.get("kinect_vision_describe"), True),
            "emotion": _bool(s.get("kinect_face_emotion"), True),
        }

    def _load_lib(self):
        if self._lib is not None:
            return self._lib
        names = [ctypes.util.find_library("freenect_sync"), "libfreenect_sync.so.0.5", "libfreenect_sync.so"]
        last = None
        for name in names:
            if not name:
                continue
            try:
                lib = ctypes.CDLL(name)
                lib.freenect_sync_get_video.argtypes = [
                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32), ctypes.c_int, ctypes.c_int
                ]
                lib.freenect_sync_get_video.restype = ctypes.c_int
                self._lib = lib
                return lib
            except OSError as exc:
                last = exc
        raise RuntimeError(f"libfreenect sync library is unavailable: {last or 'not found'}")

    def _load_core(self):
        if self._core is not None:
            return self._core
        names = [ctypes.util.find_library("freenect"), "libfreenect.so.0.5", "libfreenect.so"]
        last = None
        for name in names:
            if not name:
                continue
            try:
                lib = ctypes.CDLL(name)
                lib.freenect_init.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
                lib.freenect_init.restype = ctypes.c_int
                lib.freenect_num_devices.argtypes = [ctypes.c_void_p]
                lib.freenect_num_devices.restype = ctypes.c_int
                lib.freenect_shutdown.argtypes = [ctypes.c_void_p]
                lib.freenect_shutdown.restype = ctypes.c_int
                self._core = lib
                return lib
            except OSError as exc:
                last = exc
        raise RuntimeError(f"libfreenect core library is unavailable: {last or 'not found'}")

    def _device_count(self) -> int:
        """Count usable Kinect devices before opening the sync camera.

        This prevents libfreenect from repeatedly printing noisy
        `Invalid index [0]` / `Could not open camera: -1` errors when Docker
        cannot see the Kinect USB device yet.
        """
        core = self._load_core()
        ctx = ctypes.c_void_p()
        rc = core.freenect_init(ctypes.byref(ctx), None)
        if rc < 0 or not ctx.value:
            raise RuntimeError(
                "Kinect USB initialization failed. Ensure /dev/bus/usb is mounted into Docker and USB device cgroup access is enabled."
            )
        try:
            count = int(core.freenect_num_devices(ctx))
            return max(0, count)
        finally:
            core.freenect_shutdown(ctx)

    def _capture_jpeg(self, device: int) -> bytes:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        count = self._device_count()
        if count <= 0:
            raise RuntimeError(
                "No Xbox 360 Kinect camera is visible inside Docker. Check the Kinect power/USB adapter, /dev/bus/usb mount, and Docker USB permissions."
            )
        if device >= count:
            raise RuntimeError(
                f"Kinect device index {device} is invalid; Docker currently sees {count} Kinect device(s). Use index 0 through {count - 1}."
            )

        lib = self._load_lib()
        data = ctypes.c_void_p()
        timestamp = ctypes.c_uint32()
        # FREENECT_VIDEO_RGB = 0, 640x480 RGB24.
        rc = lib.freenect_sync_get_video(ctypes.byref(data), ctypes.byref(timestamp), device, 0)
        if rc != 0 or not data.value:
            raise RuntimeError(
                f"Kinect RGB camera could not be opened (libfreenect code {rc}). The device exists, but Docker may not have permission to access its USB camera subdevice."
            )
        size = 640 * 480 * 3
        raw = ctypes.string_at(data, size)
        rgb = np.frombuffer(raw, dtype=np.uint8).reshape((480, 640, 3))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            raise RuntimeError("Could not encode Kinect frame")
        return encoded.tobytes()

    def _analyse(self, jpeg: bytes, settings: dict[str, Any]) -> str:
        parts: list[str] = []
        if settings["emotion"]:
            try:
                if self._affect is None:
                    from .local_affect import LocalAffectDetector
                    self._affect = LocalAffectDetector()
                cue = self._affect.detect(jpeg)
                if cue:
                    parts.append(cue.conversational_text())
            except Exception as exc:
                self._last_error = f"local face cue: {exc}"
        if settings["describe"]:
            try:
                from .config import Config
                from .vision import describe_image
                cfg = Config.from_env()
                text = describe_image(
                    cfg,
                    jpeg,
                    "Describe only clearly visible expression, head direction, posture, hand/body gesture, and activity. "
                    "Do not identify the person or infer sensitive traits. Treat expression as a tentative visual cue, not proof of emotion.",
                )
                if text:
                    parts.append("Kinect camera currently sees: " + text[:700])
            except Exception as exc:
                self._last_error = f"vision model: {exc}"
        return " ".join(parts)[:1200]

    def _loop(self) -> None:
        self._running = True
        try:
            while not self._stop.is_set():
                settings = self._settings()
                if not settings["enabled"]:
                    self._stop.wait(2.0)
                    continue
                try:
                    jpeg = self._capture_jpeg(settings["device"])
                    self._last_frame_at = time.time()
                    context = self._analyse(jpeg, settings)
                    if context:
                        self._last_context = context
                    self._last_error = ""
                    self._consecutive_failures = 0
                    wait_for = settings["interval"]
                except Exception as exc:
                    self._last_error = str(exc)
                    self._consecutive_failures += 1
                    # Do not hammer libusb/libfreenect every four seconds when
                    # the Kinect is unplugged or Docker permissions are wrong.
                    wait_for = min(60.0, max(10.0, self._consecutive_failures * 10.0))
                self._stop.wait(wait_for)
        finally:
            self._running = False
            try:
                if self._lib and hasattr(self._lib, "freenect_sync_stop"):
                    self._lib.freenect_sync_stop()
            except Exception:
                pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="kinect-vision")
        self._thread.start()

    def context(self) -> str:
        if not self._last_context or time.time() - self._last_frame_at > 20:
            return ""
        return self._last_context

    def status(self) -> dict[str, Any]:
        s = self._settings()
        try:
            visible_devices = self._device_count() if s["enabled"] else 0
        except Exception:
            visible_devices = 0
        return {
            "enabled": s["enabled"],
            "running": self._running,
            "device_index": s["device"],
            "visible_devices": visible_devices,
            "last_frame_age_seconds": None if not self._last_frame_at else round(time.time()-self._last_frame_at, 1),
            "has_context": bool(self.context()),
            "error": self._last_error,
        }


def install_kinect_vision_patch() -> None:
    global _INSTALLED, _SERVICE
    if _INSTALLED:
        return
    from . import webgui, webserver

    # Add live-editable settings to the existing Vision section.
    vision = webgui.APP_SETTINGS_SCHEMA.setdefault("vision", {"label": "Vision & Scene Understanding", "fields": []})
    keys = {f.get("key") for f in vision.get("fields", [])}
    fields = [
        {"key": "kinect_vision_enabled", "label": "Enable Xbox 360 Kinect local vision", "type": "bool"},
        {"key": "kinect_device_index", "label": "Kinect device index", "type": "int"},
        {"key": "kinect_vision_interval_seconds", "label": "Kinect analysis interval (seconds)", "type": "float"},
        {"key": "kinect_face_emotion", "label": "Detect tentative facial-expression cues locally", "type": "bool"},
        {"key": "kinect_vision_describe", "label": "Use vision model for posture, gestures and scene context", "type": "bool"},
    ]
    for field in fields:
        if field["key"] not in keys:
            vision["fields"].append(field)
            webgui._APP_FIELD_TYPES[field["key"]] = field["type"]
    vision["description"] = "Phone and Xbox 360 Kinect vision. Kinect RGB frames stay local/in memory and can provide tentative facial-expression, posture and gesture cues."

    _SERVICE = KinectVisionService()
    _SERVICE.start()

    original_summary = webserver.summary_for_prompt
    def summary_with_kinect() -> str:
        base = original_summary()
        extra = _SERVICE.context() if _SERVICE else ""
        return "\n".join(x for x in (base, extra) if x)
    webserver.summary_for_prompt = summary_with_kinect

    def kinect_vision_status(self):
        return _SERVICE.status() if _SERVICE else {"enabled": False, "running": False}
    webgui.Api.kinect_vision_status = kinect_vision_status

    _INSTALLED = True
