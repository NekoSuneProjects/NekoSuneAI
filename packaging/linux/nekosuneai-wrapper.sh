#!/bin/sh
# Thin wrapper so `nekosuneai` is on PATH — the actual PyInstaller-frozen app
# (with all its bundled Python/ML dependencies) lives under /opt/nekosuneai,
# matching where the .deb/.rpm/.apk packages install it.
exec /opt/nekosuneai/NekoSuneAI "$@"
