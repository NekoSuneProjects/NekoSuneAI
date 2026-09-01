# syntax=docker/dockerfile:1.7

# Install the tiny YouTube-search helper on the native build runner instead of
# under QEMU. The dependency tree is JavaScript-only, so the resulting
# node_modules can be shared by amd64 and arm64 runtime images.
FROM --platform=$BUILDPLATFORM node:20-bookworm-slim AS node-deps
WORKDIR /nodeapp
COPY package.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm install --omit=dev --no-audit --no-fund

FROM python:3.10-slim-bookworm
ARG APP_VERSION=1.2.1
ARG TARGETARCH
ARG NODE_VERSION=20.19.5
LABEL org.opencontainers.image.title="NekoSuneAI" org.opencontainers.image.version="${APP_VERSION}" org.opencontainers.image.source="https://github.com/NekoSuneProjects/NekoSuneAI"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 AUTO_UPDATE_CHECK=false AUTO_UPDATE_INSTALL=false AUTO_TUNE_PERFORMANCE=true XTTS_USE_GPU=false STT_USE_GPU=false YTDLP_CHANNEL=nightly YTDLP_AUTO_UPDATE=true YTDLP_AUTO_UPDATE_INTERVAL_MIN=360 YTDLP_JS_RUNTIMES=node YTDLP_REMOTE_COMPONENTS=ejs:github

# Keep the runtime apt set small. Debian's `npm` package pulls in hundreds of
# node-* packages and was the biggest arm64/QEMU build bottleneck. Node itself
# is installed from the official prebuilt archive instead.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      alsa-utils bluez ca-certificates curl ffmpeg libasound2-plugins libatomic1 libportaudio2 \
      libfreenect0.5 pipewire-bin pulseaudio-utils usbutils util-linux xz-utils; \
    case "$TARGETARCH" in \
      amd64) node_arch=x64 ;; \
      arm64) node_arch=arm64 ;; \
      *) echo "Unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --retry 4 --retry-delay 2 \
      "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
      -o /tmp/node.tar.xz; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1; \
    rm -f /tmp/node.tar.xz; \
    node --version; \
    printf '%s\n' \
      'pcm.pulse {' \
      '  type pulse' \
      '}' \
      'ctl.pulse {' \
      '  type pulse' \
      '}' \
      'pcm.!default {' \
      '  type pulse' \
      '}' \
      'ctl.!default {' \
      '  type pulse' \
      '}' \
      > /etc/asound.conf

WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -r requirements.txt \
    && python -m pip install "opencv-python-headless>=4.10,<4.12" \
    && python -c "import vosk; print('Vosk native library OK')"

COPY package.json ./
COPY --from=node-deps /nodeapp/node_modules ./node_modules

COPY requirements-wakeword.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -r requirements-wakeword.txt \
    && python -m pip install "numpy>=1.24,<2" \
    && python -c "import numpy; assert int(numpy.__version__.split('.')[0]) == 1, numpy.__version__" \
    && python -c "import openwakeword.utils; openwakeword.utils.download_models(model_names=['hey_jarvis'])"

COPY . .
COPY docker-entrypoint.sh /usr/local/bin/nekosuneai-entrypoint
RUN chmod +x /usr/local/bin/nekosuneai-entrypoint /app/tools/yt_search.js \
    && mkdir -p /app/data /app/audio /app/models \
    && chmod 0777 /app/models \
    && touch /app/.setup-complete
VOLUME ["/app/data", "/app/audio", "/app/models"]
EXPOSE 8788
ENTRYPOINT ["/usr/local/bin/nekosuneai-entrypoint"]
CMD ["--web"]
