#!/usr/bin/env bash
# Auto-detect this host's live PulseAudio/PipeWire-pulse socket and cookie,
# and write PULSE_RUNTIME_DIR/PULSE_COOKIE_FILE into .env -- so
# compose.pi-proxy.yml's audio mounts don't have to guess/hardcode UID 1000.
#
# Run this on the Pi host itself (not inside the container), as a user that
# can read /run/user/*/pulse -- root can usually see the socket files but not
# necessarily connect to someone else's session, so prefer running this as
# the same user who is actually logged in with a working PulseAudio session
# (e.g. `pi`), or via sudo if that fails.
#
# Usage: ./scripts/detect-pulse-audio.sh   (from the PiProxy repo root)
set -euo pipefail

found_uid=""
for sock in /run/user/*/pulse/native; do
    [ -S "$sock" ] || continue
    uid="$(basename "$(dirname "$(dirname "$sock")")")"
    # A socket file existing doesn't mean it's live -- confirm a real client
    # can actually talk to it before trusting this one.
    if PULSE_SERVER="unix:$sock" pactl info >/dev/null 2>&1; then
        found_uid="$uid"
        break
    fi
done

if [ -z "$found_uid" ]; then
    echo "No live PulseAudio/PipeWire-pulse socket found under /run/user/*/pulse/native." >&2
    echo "Make sure someone is actually logged in (or 'sudo loginctl enable-linger <user>')" >&2
    echo "and pipewire-pulse/pulseaudio is running for them -- see docs/RASPBERRY_PI_VOICE_HOME.md." >&2
    exit 1
fi

user_name="$(getent passwd "$found_uid" | cut -d: -f1)"
home_dir="$(getent passwd "$found_uid" | cut -d: -f6)"
runtime_dir="/run/user/${found_uid}/pulse"
cookie_file="${home_dir}/.config/pulse/cookie"

echo "Detected a live audio session: UID ${found_uid} (${user_name:-unknown})"
echo "  PULSE_RUNTIME_DIR=${runtime_dir}"
echo "  PULSE_COOKIE_FILE=${cookie_file}"

if [ ! -f "$cookie_file" ]; then
    echo "Warning: no cookie file found at ${cookie_file} -- pactl may still work" >&2
    echo "without one, but if it doesn't, check where ${user_name}'s pulse cookie actually is." >&2
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
env_file="${repo_root}/.env"
[ -f "$env_file" ] || touch "$env_file"
# Drop any previous auto-detected lines, then append the fresh values.
sed -i "\|^PULSE_RUNTIME_DIR=|d;\|^PULSE_COOKIE_FILE=|d" "$env_file"
{
    echo "PULSE_RUNTIME_DIR=${runtime_dir}"
    echo "PULSE_COOKIE_FILE=${cookie_file}"
} >> "$env_file"
echo "Wrote these to ${env_file}"
