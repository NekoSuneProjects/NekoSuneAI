# syntax=docker/dockerfile:1.7
FROM python:3.10-slim-bookworm
ARG APP_VERSION=1.2.1
LABEL org.opencontainers.image.title="NekoSuneAI" org.opencontainers.image.version="${APP_VERSION}" org.opencontainers.image.source="https://github.com/NekoSuneProjects/NekoSuneAI"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 AUTO_UPDATE_CHECK=false AUTO_UPDATE_INSTALL=false AUTO_TUNE_PERFORMANCE=true XTTS_USE_GPU=false STT_USE_GPU=false YTDLP_CHANNEL=nightly YTDLP_AUTO_UPDATE=true YTDLP_AUTO_UPDATE_INTERVAL_MIN=360 YTDLP_JS_RUNTIMES=node YTDLP_REMOTE_COMPONENTS=ejs:github BRIDGE_TTS_ENGINE=edge-stream BRIDGE_TTS_VOICE=en-US-EmmaMultilingualNeural
RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils bluez ca-certificates curl ffmpeg libasound2-plugins libatomic1 libportaudio2 \
    libfreenect0.5 nodejs npm pipewire-bin pulseaudio-utils usbutils util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && printf '%s\n' \
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
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m pip install "opencv-python-headless>=4.10,<5" \
    && python -m pip install --pre --upgrade "yt-dlp[default,curl-cffi]" \
    && python -m yt_dlp --update-to nightly || true \
    && python -c "import vosk; print('Vosk native library OK')"
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY requirements-wakeword.txt ./
RUN python -m pip install -r requirements-wakeword.txt \
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
