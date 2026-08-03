#!/usr/bin/env bash
# Builds NekoSuneAI's Linux packages (.deb, .rpm, .apk) via fpm, all from the
# same PyInstaller onedir build output (dist/NekoSuneAI, produced by
# `pyinstaller NekoSuneAI.spec` at the repo root) — one packaging step
# repeated three ways, not three separate build systems.
#
# Usage: packaging/linux/build-packages.sh <version>
# Requires: fpm (gem install --no-document fpm), and the PyInstaller output
# already built at dist/NekoSuneAI relative to the repo root.
set -euo pipefail

VERSION="${1:?Usage: build-packages.sh <version>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$REPO_ROOT/dist/NekoSuneAI"
STAGE_DIR="$(mktemp -d)"
OUT_DIR="$REPO_ROOT/dist-packages"

trap 'rm -rf "$STAGE_DIR"' EXIT

if [ ! -d "$DIST_DIR" ]; then
    echo "Expected PyInstaller output at $DIST_DIR - run 'pyinstaller NekoSuneAI.spec' first." >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

# Stage the filesystem layout every format shares: the app under
# /opt/nekosuneai (writable per-user-installed data lives alongside it,
# same convention as the Windows installer — see nekosuneai/paths.py), a
# thin /usr/bin wrapper, a .desktop entry, and an icon.
mkdir -p "$STAGE_DIR/opt/nekosuneai" \
         "$STAGE_DIR/usr/bin" \
         "$STAGE_DIR/usr/share/applications" \
         "$STAGE_DIR/usr/share/pixmaps"

cp -r "$DIST_DIR"/. "$STAGE_DIR/opt/nekosuneai/"
install -m 755 "$SCRIPT_DIR/nekosuneai-wrapper.sh" "$STAGE_DIR/usr/bin/nekosuneai"
install -m 644 "$SCRIPT_DIR/nekosuneai.desktop" "$STAGE_DIR/usr/share/applications/nekosuneai.desktop"
install -m 644 "$REPO_ROOT/assets/branding/nekosuneai-icon-transparent.png" "$STAGE_DIR/usr/share/pixmaps/nekosuneai.png"

# -a native lets fpm pick the right architecture string per output format
# (deb wants "amd64", rpm/apk want "x86_64") instead of hardcoding one.
COMMON_FPM_ARGS=(
    -s dir
    -n nekosuneai
    -v "$VERSION"
    -a native
    --description "Your VRChat-first AI companion"
    --url "https://github.com/NekoSuneProjects/NekoSuneAI"
    --license "GPL-3.0"
    --maintainer "NekoSuneProjects"
    --vendor "NekoSuneProjects"
    -C "$STAGE_DIR"
    opt usr
)

echo "Building .deb..."
fpm -t deb -p "$OUT_DIR/nekosuneai_${VERSION}_amd64.deb" "${COMMON_FPM_ARGS[@]}"

echo "Building .rpm..."
# --rpm-os linux: needed when building rpms on a non-RPM-based host (we build
# on Debian/Ubuntu runners for all three formats).
fpm -t rpm -p "$OUT_DIR/nekosuneai-${VERSION}-1.x86_64.rpm" --rpm-os linux "${COMMON_FPM_ARGS[@]}"

echo "Building .apk..."
# fpm's apk output type is community-maintained and less battle-tested than
# deb/rpm — verify this actually installs cleanly in an alpine container
# before relying on it; degrade gracefully (skip, don't fail the release)
# if it doesn't build, since deb/rpm are the priority formats.
if ! fpm -t apk -p "$OUT_DIR/nekosuneai-${VERSION}-r0.apk" "${COMMON_FPM_ARGS[@]}"; then
    echo "WARNING: apk package build failed (fpm's apk support is less mature than deb/rpm). Continuing without it." >&2
fi

echo "Done. Packages in $OUT_DIR:"
ls -la "$OUT_DIR"
