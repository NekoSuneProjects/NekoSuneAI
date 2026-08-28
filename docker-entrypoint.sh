#!/bin/sh
set -eu

# Docker runs as the desktop-session UID so it can connect to the host user's
# PipeWire/PulseAudio sockets. Derive the conventional runtime directory when
# it was not explicitly supplied and report the backend before NekoSuneAI starts.
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export XDG_RUNTIME_DIR

pulse_socket="$XDG_RUNTIME_DIR/pulse/native"
pipewire_socket="$XDG_RUNTIME_DIR/${PIPEWIRE_REMOTE:-pipewire-0}"

if [ -z "${PULSE_SERVER:-}" ] && [ -S "$pulse_socket" ]; then
    PULSE_SERVER="unix:$pulse_socket"
    export PULSE_SERVER
fi

host_audio_ready=false
if [ -S "$pulse_socket" ] && command -v pactl >/dev/null 2>&1; then
    if pactl info >/tmp/nekosuneai-pactl-info.txt 2>/tmp/nekosuneai-pactl-error.txt; then
        host_audio_ready=true
        SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pulseaudio}"
        export SDL_AUDIODRIVER
        default_sink="$(sed -n 's/^Default Sink: //p' /tmp/nekosuneai-pactl-info.txt | head -n 1)"
        echo "[startup] Host PulseAudio/PipeWire audio connected${default_sink:+; default sink: $default_sink}"
    else
        pulse_error="$(tr '\n' ' ' </tmp/nekosuneai-pactl-error.txt | sed 's/[[:space:]]\+/ /g')"
        echo "[startup] WARNING: pulse socket exists but pactl cannot connect: ${pulse_error:-unknown error}"
    fi
fi

if [ "$host_audio_ready" = "false" ] && [ -S "$pipewire_socket" ]; then
    host_audio_ready=true
    PIPEWIRE_REMOTE="${PIPEWIRE_REMOTE:-pipewire-0}"
    SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pipewire}"
    export PIPEWIRE_REMOTE SDL_AUDIODRIVER
    echo "[startup] Host native PipeWire socket connected: $pipewire_socket"
fi

if [ "$host_audio_ready" = "false" ]; then
    echo "[startup] WARNING: no usable host audio session socket was found."
    echo "[startup]          XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
    echo "[startup]          Expected $pulse_socket or $pipewire_socket"
    echo "[startup]          Check PUID/PGID and rebuild/recreate the Compose container."
fi

rm -f /tmp/nekosuneai-pactl-info.txt /tmp/nekosuneai-pactl-error.txt

VOSK_MODEL_PATH="${VOSK_MODEL_PATH:-/app/models/vosk-model-small-en-us-0.15}"
VOSK_MODEL_URL="${VOSK_MODEL_URL:-https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip}"
STT_PROVIDER_NORMALIZED="$(printf '%s' "${STT_PROVIDER:-vosk}" | tr '[:upper:]' '[:lower:]')"

needs_vosk=false
case "$STT_PROVIDER_NORMALIZED" in
    vosk|local-lite|local_light|pi)
        needs_vosk=true
        ;;
esac

if [ "$needs_vosk" = "true" ]; then
    if [ -f "$VOSK_MODEL_PATH/am/final.mdl" ]; then
        echo "[startup] Vosk model ready: $VOSK_MODEL_PATH"
    else
        echo "[startup] Vosk model missing; downloading lightweight model..."
        echo "[startup] Source: $VOSK_MODEL_URL"

        model_parent="$(dirname "$VOSK_MODEL_PATH")"
        mkdir -p "$model_parent"
        tmp_dir="$(mktemp -d)"
        trap 'rm -rf "$tmp_dir"' EXIT INT TERM

        curl -fL --retry 5 --retry-delay 2 \
            --connect-timeout 20 \
            -o "$tmp_dir/vosk-model.zip" \
            "$VOSK_MODEL_URL"

        python - "$tmp_dir/vosk-model.zip" "$tmp_dir/extracted" "$VOSK_MODEL_PATH" <<'PY'
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

archive = Path(sys.argv[1])
extract_dir = Path(sys.argv[2])
target = Path(sys.argv[3])

extract_dir.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as zf:
    zf.extractall(extract_dir)

entries = list(extract_dir.iterdir())
source = entries[0] if len(entries) == 1 and entries[0].is_dir() else extract_dir

if target.exists():
    shutil.rmtree(target)
target.parent.mkdir(parents=True, exist_ok=True)
shutil.move(str(source), str(target))

required = target / "am" / "final.mdl"
if not required.is_file():
    raise SystemExit(f"Downloaded archive did not contain a valid Vosk model: missing {required}")
PY

        rm -rf "$tmp_dir"
        trap - EXIT INT TERM
        echo "[startup] Vosk model installed: $VOSK_MODEL_PATH"
    fi
else
    echo "[startup] STT provider '$STT_PROVIDER_NORMALIZED' does not use Vosk; skipping model download."
fi

exec python app.py "$@"
