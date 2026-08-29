from __future__ import annotations

import os
import threading
import time

_INSTALLED = False


def install_ytdlp_nightly_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from .youtube_music import YouTubeMusicPlayer

    if getattr(YouTubeMusicPlayer, "_neko_ytdlp_nightly_refresh", False):
        _INSTALLED = True
        return

    original_init = YouTubeMusicPlayer.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        def updater() -> None:
            # Check immediately, then keep checking for fresh nightly builds.
            # Minimum 15 minutes mirrors the downloader node's safety floor;
            # Docker defaults to every 6 hours unless overridden.
            try:
                interval_min = max(15, int(float(os.getenv("YTDLP_AUTO_UPDATE_INTERVAL_MIN", "360"))))
            except (TypeError, ValueError):
                interval_min = 360
            while True:
                try:
                    self._update_nightly()
                except Exception:
                    pass
                time.sleep(interval_min * 60)

        threading.Thread(target=updater, daemon=True, name="yt-dlp-nightly-updater").start()

    YouTubeMusicPlayer.__init__ = patched_init
    YouTubeMusicPlayer._neko_ytdlp_nightly_refresh = True
    _INSTALLED = True
