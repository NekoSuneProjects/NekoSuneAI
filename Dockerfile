# syntax=docker/dockerfile:1.7
FROM python:3.10-slim-bookworm
ARG APP_VERSION=1.2.1
LABEL org.opencontainers.image.title="NekoSuneAI" org.opencontainers.image.version="${APP_VERSION}" org.opencontainers.image.source="https://github.com/NekoSuneProjects/NekoSuneAI"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 AUTO_UPDATE_CHECK=false AUTO_UPDATE_INSTALL=false AUTO_TUNE_PERFORMANCE=true XTTS_USE_GPU=false STT_USE_GPU=false
RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils bluez ca-certificates curl ffmpeg libasound2-plugins libportaudio2 \
    pulseaudio-utils usbutils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt
COPY requirements-wakeword.txt ./
RUN python -m pip install -r requirements-wakeword.txt \
    && python -m pip install "numpy>=1.24,<2" \
    && python -c "import numpy; assert int(numpy.__version__.split('.')[0]) == 1, numpy.__version__" \
    && python -c "import openwakeword.utils; openwakeword.utils.download_models(model_names=['hey_jarvis'])"
COPY . .
RUN mkdir -p /app/data /app/audio && touch /app/.setup-complete
VOLUME ["/app/data", "/app/audio"]
EXPOSE 8788
ENTRYPOINT ["python", "app.py"]
CMD ["--web"]
