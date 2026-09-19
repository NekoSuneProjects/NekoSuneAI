from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from typing import Callable, Iterator  # noqa: E402

from .audio_input import ensure_stt_model  # noqa: E402
from .config import Config  # noqa: E402
from .models import SessionState  # noqa: E402
from .storage import ensure_runtime_dirs, load_profile  # noqa: E402
from .tts import ensure_xtts_model  # noqa: E402

# A warm-up step is a provider gate plus the loader that materialises the model
# for it. Adding a backend means adding a row, not another branch below.
Warmup = tuple[str, str, Callable[[Config, SessionState], object]]

_WARMUPS: tuple[Warmup, ...] = (
    ("stt_provider", "faster-whisper", ensure_stt_model),
    ("tts_provider", "xtts", ensure_xtts_model),
)


def _pending_warmups(config: Config) -> Iterator[Warmup]:
    for attribute, expected, loader in _WARMUPS:
        if getattr(config, attribute, None) == expected:
            yield attribute, expected, loader


def preload_runtime_assets() -> None:
    """Fetch and cache every model the configured providers will need at runtime."""
    ensure_runtime_dirs()

    # Config.from_env() runs load_dotenv(), which can define the storage paths
    # load_profile() resolves against, so it has to come first.
    config = Config.from_env()
    load_profile()

    state = SessionState(
        voice_enabled=config.voice_enabled,
        input_mode=config.input_mode,
    )

    for _attribute, _expected, loader in _pending_warmups(config):
        loader(config, state)


def main() -> None:
    preload_runtime_assets()


if __name__ == "__main__":
    main()
