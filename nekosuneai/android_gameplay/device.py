from __future__ import annotations
import subprocess
import re
from dataclasses import dataclass

import cv2
import numpy as np


class ADBError(RuntimeError):
    pass


ANDROID_KEYCODES = {
    "ENTER": 66,
    "ESC": 111,
    "ESCAPE": 111,
    "BACK": 4,
    "HOME": 3,
    "UP": 19,
    "DOWN": 20,
    "LEFT": 21,
    "RIGHT": 22,
    "SPACE": 62,
    "TAB": 61,
    "A": 29, "B": 30, "C": 31, "D": 32, "E": 33, "F": 34,
    "G": 35, "H": 36, "I": 37, "J": 38, "K": 39, "L": 40,
    "M": 41, "N": 42, "O": 43, "P": 44, "Q": 45, "R": 46,
    "S": 47, "T": 48, "U": 49, "V": 50, "W": 51, "X": 52,
    "Y": 53, "Z": 54,
}


@dataclass
class AndroidDevice:
    """
    Controls Android directly through ADB.

    It does not move the host Windows/Linux mouse and does not type through the
    physical host keyboard.
    """
    adb_path: str = "adb"
    serial: str = ""
    prefer_touchscreen_source: bool = True

    def _run(self, *args: str, timeout: int = 20, binary: bool = False):
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ADBError(
                f"ADB was not found at '{self.adb_path}'. Install Android platform-tools "
                "or change adb_path in config.json."
            ) from exc

        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise ADBError(error or f"ADB failed with exit code {result.returncode}")

        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace").strip()

    def list_devices(self) -> list[str]:
        out = self._run("devices")
        devices = []
        for line in out.splitlines()[1:]:
            if "\tdevice" in line:
                devices.append(line.split("\t", 1)[0].strip())
        return devices

    def getprop(self, name: str) -> str:
        """Read one Android system property without depending on the host OS."""
        try:
            return self._run("shell", "getprop", name, timeout=10).strip()
        except ADBError:
            return ""

    def device_environment(self) -> dict[str, str]:
        """
        Detect the Android runtime from guest properties.

        This intentionally detects the Android environment rather than the Python
        host OS, so a Windows client connected to a Linux ReDroid server is still
        identified as ReDroid.
        """
        props = {
            "manufacturer": self.getprop("ro.product.manufacturer"),
            "brand": self.getprop("ro.product.brand"),
            "model": self.getprop("ro.product.model"),
            "product": self.getprop("ro.product.name"),
            "device": self.getprop("ro.product.device"),
            "hardware": self.getprop("ro.hardware"),
            "fingerprint": self.getprop("ro.build.fingerprint"),
            "qemu": self.getprop("ro.kernel.qemu"),
            "release": self.getprop("ro.build.version.release"),
            "sdk": self.getprop("ro.build.version.sdk"),
        }
        haystack = " ".join(props.values()).lower()

        if "bluestacks" in haystack or "bstack" in haystack:
            kind = "bluestacks"
        elif "redroid" in haystack:
            kind = "redroid"
        elif props["qemu"] == "1" or any(
            token in haystack for token in ("generic_x86", "generic_x86_64", "sdk_gphone")
        ):
            kind = "android_emulator"
        else:
            kind = "android"

        props["kind"] = kind
        return props

    def environment_name(self) -> str:
        env = self.device_environment()
        labels = {
            "bluestacks": "BlueStacks",
            "redroid": "ReDroid/Linux",
            "android_emulator": "Android Emulator",
            "android": "Android/ADB",
        }
        return labels.get(env["kind"], env["kind"])

    def list_packages(self, third_party_only: bool = True) -> list[str]:
        args = ["shell", "pm", "list", "packages"]
        if third_party_only:
            args.append("-3")
        out = self._run(*args, timeout=30)
        return sorted({
            line.split("package:", 1)[1].strip()
            for line in out.splitlines()
            if line.strip().startswith("package:")
        })

    def foreground_package(self) -> str:
        # Try multiple dumpsys forms because Android/BlueStacks builds vary.
        candidates = [
            ("shell", "dumpsys", "window", "windows"),
            ("shell", "dumpsys", "activity", "activities"),
        ]
        for args in candidates:
            try:
                out = self._run(*args, timeout=20)
            except Exception:
                continue
            for line in out.splitlines():
                if any(k in line for k in ("mCurrentFocus", "mFocusedApp", "mResumedActivity")) and "/" in line:
                    left = line.split("/", 1)[0]
                    token = left.split()[-1].strip("{}")
                    if token:
                        return token
        return ""

    def screenshot(self) -> np.ndarray:
        png = self._run("exec-out", "screencap", "-p", timeout=30, binary=True)
        arr = np.frombuffer(png, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ADBError("Could not decode screenshot returned by ADB.")
        return image

    def tap(self, x: int, y: int):
        x, y = int(x), int(y)
        # Explicit touchscreen source is preferable for games. Fall back to the
        # generic Android input command if this Android build rejects it.
        if self.prefer_touchscreen_source:
            try:
                self._run("shell", "input", "touchscreen", "tap", str(x), str(y))
                return
            except ADBError:
                pass
        self._run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 350):
        args = (
            str(int(x1)), str(int(y1)),
            str(int(x2)), str(int(y2)),
            str(int(duration_ms)),
        )
        if self.prefer_touchscreen_source:
            try:
                self._run("shell", "input", "touchscreen", "swipe", *args)
                return
            except ADBError:
                pass
        self._run("shell", "input", "swipe", *args)

    def long_press(self, x: int, y: int, duration_ms: int = 900):
        self.swipe(x, y, x, y, duration_ms)

    def keyevent(self, key):
        if isinstance(key, str):
            value = ANDROID_KEYCODES.get(key.strip().upper())
            if value is None:
                try:
                    value = int(key)
                except ValueError as exc:
                    raise ADBError(f"Unknown Android key: {key}") from exc
        else:
            value = int(key)
        self._run("shell", "input", "keyevent", str(value))

    def back(self):
        self.keyevent("BACK")

    def home(self):
        self.keyevent("HOME")

    def type_text(self, text: str):
        safe = text.replace("%", "%25").replace(" ", "%s")
        self._run("shell", "input", "text", safe)

    def _launcher_activity(self, package_name: str) -> str:
        """Resolve the package's real MAIN/LAUNCHER activity when Android exposes one."""
        attempts = [
            (
                "shell", "cmd", "package", "resolve-activity", "--brief",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER",
                package_name,
            ),
            (
                "shell", "cmd", "package", "resolve-activity", "--brief", "--user", "0",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER",
                package_name,
            ),
        ]
        for args in attempts:
            try:
                out = self._run(*args, timeout=15).strip()
            except ADBError:
                continue
            for line in reversed(out.splitlines()):
                line = line.strip()
                if "/" in line and "No activity found" not in line:
                    return line
        return ""

    @staticmethod
    def _launch_output_failed(output: str) -> bool:
        text = (output or "").lower()
        return any(token in text for token in (
            "no activities found",
            "no activity found",
            "unable to resolve intent",
            "error: activity",
            "monkey aborted",
            "aborted",
        ))

    def launch_package(self, package_name: str):
        if not package_name:
            return

        if not re.fullmatch(r"[A-Za-z0-9_.]+", package_name):
            raise ADBError(f"Invalid Android package name: {package_name}")

        # Make a missing/partial install explicit instead of letting monkey claim success.
        packages = self.list_packages(third_party_only=False)
        if package_name not in packages:
            raise ADBError(f"Package is not installed on this ADB device: {package_name}")

        env = self.device_environment()
        activity = self._launcher_activity(package_name)

        # Normal Android/ReDroid path: launch the exact resolved activity.
        if activity:
            out = self._run(
                "shell", "am", "start", "-W", "-n", activity,
                timeout=30,
            )
            if self._launch_output_failed(out):
                raise ADBError(
                    f"{self.environment_name()} resolved {activity}, but Android could not start it: {out}"
                )
            return

        # Some emulator builds (notably BlueStacks variants) do not resolve via
        # cmd package consistently. Try an Intent-based launch before monkey.
        try:
            out = self._run(
                "shell", "am", "start", "-W",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER",
                "-p", package_name,
                timeout=30,
            )
            if not self._launch_output_failed(out):
                return
        except ADBError:
            pass

        # Last compatibility fallback. Monkey often returns exit code 0 even when
        # it found no activity, so its stdout MUST be inspected.
        out = self._run(
            "shell", "monkey",
            "-p", package_name,
            "-c", "android.intent.category.LAUNCHER",
            "1",
            timeout=30,
        )
        if self._launch_output_failed(out):
            details = (
                f"environment={env['kind']}, "
                f"model={env.get('model') or 'unknown'}, "
                f"android={env.get('release') or 'unknown'}"
            )
            raise ADBError(
                f"No launchable MAIN/LAUNCHER activity was found for {package_name} "
                f"({details}). The app may be a partial/split install, disabled, "
                f"or incompatible with this Android image.\nMonkey output:\n{out}"
            )

    def force_stop(self, package_name: str):
        if package_name:
            self._run("shell", "am", "force-stop", package_name)

    def package_version(self, package_name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.]+", package_name):
            raise ADBError("Select an Android package before starting training.")
        output = self._run("shell", "dumpsys", "package", package_name)
        code = re.search(r"\bversionCode=(\d+)", output)
        name = re.search(r"\bversionName=([^\s]+)", output)
        if not code:
            raise ADBError(f"Could not read the installed version of {package_name}")
        return f"{name.group(1) if name else 'unknown'}+{code.group(1)}"

    def screen_size(self) -> tuple[int, int]:
        out = self._run("shell", "wm", "size")
        token = out.split(":")[-1].strip()
        w, h = token.split("x")
        return int(w), int(h)

    def input_help(self) -> str:
        """Useful diagnostic: confirms Android exposes the shell input command."""
        return self._run("shell", "input", "-h", timeout=10)
