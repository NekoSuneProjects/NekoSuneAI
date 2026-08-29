#!/bin/sh
set -eu

# ---------------------------------------------------------------------------
# yt-dlp nightly updater
# ---------------------------------------------------------------------------
# Keep the Docker-side YouTube stack on yt-dlp nightly. This mirrors the
# updater behaviour used by NekosDownloaderFork/yt-dlp-node: check at startup,
# prefer the nightly channel, and never stop NekoSuneAI from booting if the
# updater itself cannot reach GitHub.
ytdlp_auto="$(printf '%s' "${YTDLP_AUTO_UPDATE:-true}" | tr '[:upper:]' '[:lower:]')"
ytdlp_channel="$(printf '%s' "${YTDLP_CHANNEL:-nightly}" | tr '[:upper:]' '[:lower:]')"
if [ "$ytdlp_auto" != "false" ] && [ "$ytdlp_auto" != "0" ] && [ "$ytdlp_auto" != "no" ]; then
    if command -v yt-dlp >/dev/null 2>&1; then
        if [ "$ytdlp_channel" = "nightly" ] || [ "$ytdlp_channel" = "nightlies" ]; then
            echo "[startup] Checking yt-dlp nightly update..."
            yt-dlp --update-to nightly >/tmp/nekosuneai-ytdlp-update.log 2>&1 || {
                echo "[startup] yt-dlp nightly self-update skipped; trying pip nightly refresh..."
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
# Compose mounts /run/user read-only. We scan every host desktop session,
# probe PulseAudio/PipeWire compatibility as the socket owner, and then run
# NekoSuneAI as that same UID/GID. This removes the normal need for PUID, PGID,
# XDG_RUNTIME_DIR, PULSE_SERVER, AUDIO_GID, or a hard-coded speaker index.

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

    # Optional legacy override: when PUID/PGID are present, use them only as a
    # preference/filter. Normal installs do not need either setting anymore.
    if [ -n "${PUID:-}" ] && [ "$candidate_uid" != "$PUID" ]; then
        return 1
    fi

    if XDG_RUNTIME_DIR="$candidate_runtime" \
       PULSE_SERVER="unix:$candidate_socket" \
       run_as_ids "$candidate_uid" "$candidate_gid" \
       pactl info >/tmp/nekosuneai-pactl-info.txt 2>/tmp/nekosuneai-pactl-error.txt; then
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

    if [ -n "${PUID:-}" ] && [ "$candidate_uid" != "$PUID" ]; then
        return 1
    fi

    # Native PipeWire is a fallback for hosts without pipewire-pulse. We do not
    # need a server query here; socket ownership is enough for ffplay/PipeWire.
    selected_audio_uid="$candidate_uid"
    selected_audio_gid="${PGID:-$candidate_gid}"
    selected_audio_runtime="$candidate_runtime"
    selected_audio_backend="pipewire"
    return 0
}

if [ "$auto_audio" != "false" ] && [ "$auto_audio" != "0" ] && [ "$auto_audio" != "no" ]; then
    # Try an explicitly configured runtime first for backwards compatibility.
    if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
        probe_pulse_runtime "$XDG_RUNTIME_DIR" || true
    fi

    # Then scan every host desktop session. Retry briefly because PipeWire may
    # start a moment after Docker during boot.
    detect_attempt=1
    while [ -z "$selected_audio_runtime" ] && [ "$detect_attempt" -le 6 ]; do
        for audio_runtime in /run/user/*; do
            [ -d "$audio_runtime" ] || continue
            if probe_pulse_runtime "$audio_runtime"; then
                break
            fi
        done

        if [ -z "$selected_audio_runtime" ]; then
            for audio_runtime in /run/user/*; do
                [ -d "$audio_runtime" ] || continue
                if probe_pipewire_runtime "$audio_runtime"; then
                    break
                fi
            done
        fi

        if [ -z "$selected_audio_runtime" ] && [ "$detect_attempt" -lt 6 ]; then
            sleep 2
        fi
        detect_attempt=$((detect_attempt + 1))
    done
fi

if [ -n "$selected_audio_runtime" ]; then
    XDG_RUNTIME_DIR="$selected_audio_runtime"
    export XDG_RUNTIME_DIR

    if [ "$selected_audio_backend" = "pulse" ]; then
        PULSE_SERVER="unix:$selected_audio_runtime/pulse/native"
        SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pulseaudio}"
        export PULSE_SERVER SDL_AUDIODRIVER

        default_sink="$(sed -n 's/^Default Sink: //p' /tmp/nekosuneai-pactl-info.txt 2>/dev/null | head -n 1)"
        if [ -z "$default_sink" ]; then
            default_sink="$(XDG_RUNTIME_DIR="$selected_audio_runtime" PULSE_SERVER="$PULSE_SERVER" run_as_ids "$selected_audio_uid" "$selected_audio_gid" pactl get-default-sink 2>/dev/null || true)"
        fi
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
# The first audio pass above finds the host session, not necessarily a sleeping
# Bluetooth speaker.  If BlueZ and the host audio session are available, run a
# one-shot discovery as the session owner before the application starts.  The
# in-app watchdog repeats this later, so Alexa can recover after disconnects.
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
