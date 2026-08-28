#!/bin/sh
set -eu

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
