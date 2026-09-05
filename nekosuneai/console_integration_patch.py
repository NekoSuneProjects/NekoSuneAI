from __future__ import annotations

from typing import Any

_INSTALLED = False


def install_console_integration_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from .console_control import console_capabilities, console_command, console_status, handle_console_request

    # CLI/browser media path.
    try:
        from . import media
        original_media = media.handle_media_request
        if not getattr(original_media, "_neko_console_control", False):
            def handle_media_with_consoles(user_text, profile, config):
                reply = handle_console_request(user_text)
                if reply is not None:
                    return media.MediaActionResult(handled=True, response=reply)
                return original_media(user_text, profile, config)
            handle_media_with_consoles._neko_console_control = True
            media.handle_media_request = handle_media_with_consoles
    except Exception:
        pass

    # YouTube-music path used by the web dashboard's integrated chat pipeline.
    try:
        from . import youtube_music
        original_music = youtube_music.handle_music_request
        if not getattr(original_music, "_neko_console_control", False):
            def handle_music_with_consoles(text, player):
                reply = handle_console_request(text)
                if reply is not None:
                    return reply
                return original_music(text, player)
            handle_music_with_consoles._neko_console_control = True
            youtube_music.handle_music_request = handle_music_with_consoles
    except Exception:
        pass

    # RPC methods are available to the authenticated dashboard via /api/rpc.
    try:
        from .webgui import Api
        if not hasattr(Api, "get_console_status"):
            def get_console_status(self, platform: str = "all") -> dict[str, Any]:
                return console_status(platform)
            Api.get_console_status = get_console_status  # type: ignore[attr-defined]
        if not hasattr(Api, "get_console_capabilities"):
            def get_console_capabilities(self, platform: str = "all") -> dict[str, Any]:
                return console_capabilities(platform)
            Api.get_console_capabilities = get_console_capabilities  # type: ignore[attr-defined]
        if not hasattr(Api, "send_console_command"):
            def send_console_command(self, platform: str, action: str, value: str = "", confirmed: bool = False) -> dict[str, Any]:
                message = console_command(platform, action, value, confirmed=bool(confirmed))
                return {"ok": True, "message": message, "status": console_status(platform)}
            Api.send_console_command = send_console_command  # type: ignore[attr-defined]
    except Exception:
        pass

    # webserver imports handle_music_request by value, so update that binding too
    # when another patch imported webserver before this installer ran.
    try:
        from . import webserver
        from .youtube_music import handle_music_request as patched_music
        webserver.handle_music_request = patched_music

        original_decorate = webserver._decorate_dashboard
        if not getattr(original_decorate, "_neko_console_link", False):
            def decorate(body):
                rendered = original_decorate(body)
                was_bytes = isinstance(rendered, (bytes, bytearray))
                text = bytes(rendered).decode("utf-8") if was_bytes else str(rendered)
                widget = r'''<a id="neko-consoles-link" href="/consoles.html" class="btn-secondary fixed left-4 bottom-20 z-[90] rounded-xl px-4 py-3 text-[12px] font-bold">Consoles</a>'''
                if "neko-consoles-link" not in text:
                    text = text.replace("</body>", widget + "</body>", 1)
                return text.encode("utf-8") if was_bytes else text
            decorate._neko_console_link = True
            webserver._decorate_dashboard = decorate
    except Exception:
        pass
