# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the release-pipeline desktop bundle (Windows .exe /
Linux binary), voice/TTS/RVC stack included.

Unlike the older CI-only bundles documented in BUILD.md (base+GUI only, voice
excluded), this spec is meant for the packaged installers (Inno Setup on
Windows, .deb/.rpm/.apk via fpm on Linux) and pulls in the full ML stack.
That stack (torch, coqui-tts, faster-whisper, sentence-transformers) has
well-documented PyInstaller gaps — importlib.metadata version lookups that
need copy_metadata(), tokenizer/G2P submodules that aren't auto-detected,
and torch's import tree being deep enough to need a raised recursion limit.
This file's package lists were assembled from those known issues, NOT from a
verified successful build in this environment (no GPU/ML stack available to
test with) — treat the first real CI run as the actual test, and expect to
add to `_HIDDEN_IMPORTS`/`_COLLECT_ALL_PACKAGES` if PyInstaller's runtime
output reports a ModuleNotFoundError for something not listed here.

Usage: `pyinstaller NekoSuneAI.spec` from the repo root (paths below are
relative to this file's own directory via SPECPATH, so it also works if
invoked from elsewhere).
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

# torch's import graph is deep enough to blow the default recursion limit
# during PyInstaller's static analysis — a documented, common workaround.
sys.setrecursionlimit(sys.getrecursionlimit() * 5)

_ROOT = Path(SPECPATH)  # noqa: F821 - SPECPATH is injected by PyInstaller

# Packages that need their whole tree (code + data + native binaries)
# bundled — each has known PyInstaller gaps when left to auto-detection.
_COLLECT_ALL_PACKAGES = [
    "torch",
    "torchaudio",
    "TTS",
    "faster_whisper",
    "webview",
    "sentence_transformers",
    "transformers",
    "librosa",
    "ctranslate2",
]

# importlib.metadata-based version/entry-point lookups — a very common
# PyInstaller gotcha where the package works except for one .dist-info read.
_COPY_METADATA_PACKAGES = [
    "torch",
    "torchaudio",
    "TTS",
    "faster-whisper",
    "transformers",
    "sentence-transformers",
    "tokenizers",
    "ctranslate2",
    "numpy",
]

# coqui-tts's tokenizer/G2P dependencies aren't always picked up by static
# import analysis since they're loaded dynamically per-language/per-model.
_HIDDEN_IMPORTS = [
    "gruut",
    "gruut_lang_en",
    "pycrfsuite",
    "mecab",
    "sentencepiece",
    "anyascii",
]

datas = [(str(_ROOT / "nekosuneai" / "static"), "nekosuneai/static")]
binaries = []
hiddenimports = list(_HIDDEN_IMPORTS)

for _pkg in _COLLECT_ALL_PACKAGES:
    try:
        pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(_pkg)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

for _pkg in _COPY_METADATA_PACKAGES:
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        continue

block_cipher = None

a = Analysis(  # noqa: F821 - PyInstaller injects these names at exec time
    [str(_ROOT / "app.py")],
    pathex=[str(_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

# Windows ships windowed-only (matches the existing --windowed convention in
# BUILD.md/.gitea/workflows/ci.yml — GUI is the primary Windows experience).
# Linux keeps a console so CLI mode (no display / no WebKitGTK) still works.
_is_windows = sys.platform == "win32"

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NekoSuneAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=not _is_windows,
    icon=str(_ROOT / "data" / "logo.ico") if _is_windows else None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="NekoSuneAI",
)
