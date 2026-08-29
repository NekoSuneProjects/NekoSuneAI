#!/bin/sh
set -eu

# ---------------------------------------------------------------------------
# yt-dlp nightly updater
# ---------------------------------------------------------------------------
# Mirror the working NekosDownloaderFork/yt-dlp-node behaviour: prefer the
# nightly channel, refresh on every container start, and never prevent the
# assistant from starting if the updater itself cannot reach GitHub/PyPI.
ytdlp_auto="$(printf '%s' "${YTDLP_AUTO_UPDATE:-true}" | tr '[:upper:]' '[:lower:]')"
ytdlp_channel="$(printf '%s' "${YTDLP_CHANNEL:-nightly}" | tr '[:upper:]' '[:lower:]')"
if [ "$ytdlp_auto" != "false" ] && [ "$ytdlp_auto" != "0" ] && [ "$ytdlp_auto" != "no" ]; then
    if command -v yt-dlp >/dev/null 2>&1; then
        if [ "$ytdlp_channel" = "nightly" ] || [ "$ytdlp_channel" = "nightlies" ]; then
            echo "[startup] Checking yt-dlp nightly update..."
            yt-dlp --update-to nightly >/tmp/nekosuneai-ytdlp-update.log 2>&1 || {
                echo "[startup] yt-dlp nightly self-update skipped; trying pip pre-release refresh..."
                python -m pip install --pre --upgrade "yt-dlp[default,curl-cffi]" >/tmp/nekosuneai-ytdlp-pip.log 2>&1 || true
            }
        else
            echo "[startup] Checking yt-dlp update..."
            yt-dlp -U >/tmp/nekosuneai-ytdlp-update.log 2>&1 || true
        fi
    else
        echo "[startup] yt-dlp missing; installing nightly-capable build..."
        python -m pip install --pre --upgrade "yt-dlp[default,curl-cffi]" >/tmp/nekosuneai-ytdlp-pip.log 2>&1 || true
    fi
fi

# ---------------------------------------------------------------------------
# Host audio auto-detection
# ---------------------------------------------------------------------------
auto_audio="$(printf '%s' "${NEKOSUNEAI_AUTO_AUDIO:-true}" | tr '[:upper:]' '[:lower:]')"
selected_audio_uid=""
selected_audio_gid=""
selected_audio_runtime=""
selected_audio_backend=""

run_as_ids() {
    target_uid="$1"
    target_gid="$2"
    shift 2
    if [ "$(id -u)" = "0" ] && [ "$target_uid" != "0" ] && command -v setpriv >/dev/null 2>&1; then
        setpriv --reuid "$target_uid" --regid "$target_gid" --clear-groups "$@"
    else
        "$@"
    fi
}

probe_pulse_runtime() {
    candidate_runtime="$1"
    candidate_socket="$candidate_runtime/pulse/native"
    [ -S "$candidate_socket" ] || return 1
    candidate_uid="$(stat -c '%u' "$candidate_runtime" 2>/dev/null || true)"
    candidate_gid="$(stat -c '%g' "$candidate_runtime" 2>/dev/null || true)"
    [ -n "$candidate_uid" ] || return 1
    [ -n "$candidate_gid" ] || return 1
    if [ -n "${PUID:-}" ] && [ "$candidate_uid" != "$PUID" ]; then return 1; fi
    if XDG_RUNTIME_DIR="$candidate_runtime" PULSE_SERVER="unix:$candidate_socket" run_as_ids "$candidate_uid" "$candidate_gid" pactl info >/tmp/nekosuneai-pactl-info.txt 2>/tmp/nekosuneai-pactl-error.txt; then
        selected_audio_uid="$candidate_uid"
        selected_audio_gid="${PGID:-$candidate_gid}"
        selected_audio_runtime="$candidate_runtime"
        selected_audio_backend="pulse"
        return 0
    fi
    return 1
}

probe_pipewire_runtime() {
    candidate_runtime="$1"
    candidate_remote="${PIPEWIRE_REMOTE:-pipewire-0}"
    candidate_socket="$candidate_runtime/$candidate_remote"
    [ -S "$candidate_socket" ] || return 1
    candidate_uid="$(stat -c '%u' "$candidate_runtime" 2>/dev/null || true)"
    candidate_gid="$(stat -c '%g' "$candidate_runtime" 2>/dev/null || true)"
    [ -n "$candidate_uid" ] || return 1
    [ -n "$candidate_gid" ] || return 1
    if [ -n "${PUID:-}" ] && [ "$candidate_uid" != "$PUID" ]; then return 1; fi
    selected_audio_uid="$candidate_uid"
    selected_audio_gid="${PGID:-$candidate_gid}"
    selected_audio_runtime="$candidate_runtime"
    selected_audio_backend="pipewire"
    return 0
}

if [ "$auto_audio" != "false" ] && [ "$auto_audio" != "0" ] && [ "$auto_audio" != "no" ]; then
    if [ -n "${XDG_RUNTIME_DIR:-}" ]; then probe_pulse_runtime "$XDG_RUNTIME_DIR" || true; fi
    detect_attempt=1
    while [ -z "$selected_audio_runtime" ] && [ "$detect_attempt" -le 6 ]; do
        for audio_runtime in /run/user/*; do
            [ -d "$audio_runtime" ] || continue
            if probe_pulse_runtime "$audio_runtime"; then break; fi
        done
        if [ -z "$selected_audio_runtime" ]; then
            for audio_runtime in /run/user/*; do
                [ -d "$audio_runtime" ] || continue
                if probe_pipewire_runtime "$audio_runtime"; then break; fi
            done
        fi
        if [ -z "$selected_audio_runtime" ] && [ "$detect_attempt" -lt 6 ]; then sleep 2; fi
        detect_attempt=$((detect_attempt + 1))
    done
fi

if [ -n "$selected_audio_runtime" ]; then
    XDG_RUNTIME_DIR="$selected_audio_runtime"; export XDG_RUNTIME_DIR
    if [ "$selected_audio_backend" = "pulse" ]; then
        PULSE_SERVER="unix:$selected_audio_runtime/pulse/native"
        SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pulseaudio}"
        export PULSE_SERVER SDL_AUDIODRIVER
        default_sink="$(sed -n 's/^Default Sink: //p' /tmp/nekosuneai-pactl-info.txt 2>/dev/null | head -n 1)"
        if [ -z "$default_sink" ]; then default_sink="$(XDG_RUNTIME_DIR="$selected_audio_runtime" PULSE_SERVER="$PULSE_SERVER" run_as_ids "$selected_audio_uid" "$selected_audio_gid" pactl get-default-sink 2>/dev/null || true)"; fi
        echo "[startup] Auto-detected host audio: PulseAudio/PipeWire session UID $selected_audio_uid${default_sink:+; default sink: $default_sink}"
    else
        PIPEWIRE_REMOTE="${PIPEWIRE_REMOTE:-pipewire-0}"
        SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pipewire}"
        export PIPEWIRE_REMOTE SDL_AUDIODRIVER
        echo "[startup] Auto-detected host audio: native PipeWire session UID $selected_audio_uid"
    fi
else
    echo "[startup] WARNING: no active host PulseAudio/PipeWire session was found automatically."
    echo "[startup]          NekoSuneAI will still start; audio can appear after the host session is restored and the container is recreated."
fi

# ---------------------------------------------------------------------------
# Paired Bluetooth speaker auto-connect
# ---------------------------------------------------------------------------
bluetooth_auto="$(printf '%s' "${BLUETOOTH_RECONNECT_ENABLED:-true}" | tr '[:upper:]' '[:lower:]')"
if [ -n "$selected_audio_runtime" ] \
   && [ "$bluetooth_auto" != "false" ] \
   && [ "$bluetooth_auto" != "0" ] \
   && [ "$bluetooth_auto" != "no" ] \
   && command -v bluetoothctl >/dev/null 2>&1 \
   && [ -S /run/dbus/system_bus_socket ]; then
    echo "[startup] Looking for a paired Bluetooth audio speaker (Alexa/Echo preferred)..."
    if XDG_RUNTIME_DIR="$selected_audio_runtime" \
       PULSE_SERVER="${PULSE_SERVER:-}" \
       PIPEWIRE_REMOTE="${PIPEWIRE_REMOTE:-pipewire-0}" \
       BLUETOOTH_SPEAKER_ADDRESS="${BLUETOOTH_SPEAKER_ADDRESS:-}" \
       run_as_ids "$selected_audio_uid" "$selected_audio_gid" \
       python - <<'PY'
import os
from types import SimpleNamespace
from nekosuneai.bluetooth_watchdog import BluetoothSpeakerWatchdog
config = SimpleNamespace(
    bluetooth_reconnect_enabled=True,
    bluetooth_speaker_address=(os.getenv("BLUETOOTH_SPEAKER_ADDRESS") or "").strip() or None,
    bluetooth_reconnect_interval_seconds=10.0,
)
watchdog = BluetoothSpeakerWatchdog(config, print)
ok, message = watchdog.reconnect_now()
print(f"[startup] {message}")
raise SystemExit(0 if ok else 1)
PY
    then :; else
        echo "[startup] Bluetooth speaker was not ready at boot; the background watchdog will keep trying."
    fi
fi

rm -f /tmp/nekosuneai-pactl-info.txt /tmp/nekosuneai-pactl-error.txt

# ---------------------------------------------------------------------------
# Vosk model bootstrap
# ---------------------------------------------------------------------------
VOSK_MODEL_PATH="${VOSK_MODEL_PATH:-/app/models/vosk-model-small-en-us-0.15}"
VOSK_MODEL_URL="${VOSK_MODEL_URL:-https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip}"
STT_PROVIDER_NORMALIZED="$(printf '%s' "${STT_PROVIDER:-vosk}" | tr '[:upper:]' '[:lower:]')"
needs_vosk=false
case "$STT_PROVIDER_NORMALIZED" in vosk|local-lite|local_light|pi) needs_vosk=true ;; esac
if [ "$needs_vosk" = "true" ]; then
    if [ -f "$VOSK_MODEL_PATH/am/final.mdl" ]; then
        echo "[startup] Vosk model ready: $VOSK_MODEL_PATH"
    else
        echo "[startup] Vosk model missing; downloading lightweight model..."
        echo "[startup] Source: $VOSK_MODEL_URL"
        model_parent="$(dirname "$VOSK_MODEL_PATH")"; mkdir -p "$model_parent"
        tmp_dir="$(mktemp -d)"; trap 'rm -rf "$tmp_dir"' EXIT INT TERM
        curl -fL --retry 5 --retry-delay 2 --connect-timeout 20 -o "$tmp_dir/vosk-model.zip" "$VOSK_MODEL_URL"
        python - "$tmp_dir/vosk-model.zip" "$tmp_dir/extracted" "$VOSK_MODEL_PATH" <<'PY'
from __future__ import annotations
import shutil, sys, zipfile
from pathlib import Path
archive=Path(sys.argv[1]); extract_dir=Path(sys.argv[2]); target=Path(sys.argv[3])
extract_dir.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as zf: zf.extractall(extract_dir)
entries=list(extract_dir.iterdir()); source=entries[0] if len(entries)==1 and entries[0].is_dir() else extract_dir
if target.exists(): shutil.rmtree(target)
target.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(source), str(target))
required=target/'am'/'final.mdl'
if not required.is_file(): raise SystemExit(f"Downloaded archive did not contain a valid Vosk model: missing {required}")
PY
        rm -rf "$tmp_dir"; trap - EXIT INT TERM
        echo "[startup] Vosk model installed: $VOSK_MODEL_PATH"
    fi
else
    echo "[startup] STT provider '$STT_PROVIDER_NORMALIZED' does not use Vosk; skipping model download."
fi

# ---------------------------------------------------------------------------
# Drop from root to the detected desktop-session owner
# ---------------------------------------------------------------------------
if [ "$(id -u)" = "0" ] && [ -n "$selected_audio_uid" ] && [ "$selected_audio_uid" != "0" ]; then
    app_home="/app/data/.home"
    mkdir -p "$app_home" /app/audio /app/data
    chown -R "$selected_audio_uid:$selected_audio_gid" /app/data /app/audio 2>/dev/null || true
    group_list="$selected_audio_gid"
    add_group_id() {
        extra_gid="$1"; [ -n "$extra_gid" ] || return 0; [ "$extra_gid" != "0" ] || return 0
        case ",$group_list," in *,$extra_gid,*) ;; *) group_list="$group_list,$extra_gid" ;; esac
    }
    for device_path in /dev/snd/*; do [ -e "$device_path" ] || continue; add_group_id "$(stat -c '%g' "$device_path" 2>/dev/null || true)"; done
    for device_path in /dev/bus/usb/*/*; do [ -e "$device_path" ] || continue; add_group_id "$(stat -c '%g' "$device_path" 2>/dev/null || true)"; done
    add_group_id "${AUDIO_GID:-}"; add_group_id "${VIDEO_GID:-}"; add_group_id "${BLUETOOTH_GID:-}"
    echo "[startup] Running NekoSuneAI as detected host audio UID:GID $selected_audio_uid:$selected_audio_gid (groups: $group_list)"
    exec setpriv --reuid "$selected_audio_uid" --regid "$selected_audio_gid" --groups "$group_list" \
        env HOME="$app_home" USER=nekosuneai LOGNAME=nekosuneai python app.py "$@"
fi

exec python app.py "$@"
