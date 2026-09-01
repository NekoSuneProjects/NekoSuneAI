import http.server

from nekosuneai.avatar_http_patch import install_avatar_http_patch
from nekosuneai.scam_call_patch import install_scam_call_patch
from nekosuneai.call_sync_patch import install_call_sync_patch
from nekosuneai.mcp_oauth_recovery import install_mcp_oauth_recovery
from nekosuneai.settings_dashboard_patch import install_settings_dashboard_patch
from nekosuneai.settings_backend_patch import install_settings_backend_patch
from nekosuneai.settings_dashboard_compat import install_settings_dashboard_compat
from nekosuneai.music_resource_guard_patch import install_music_resource_guard_patch
from nekosuneai.music_dashboard_patch import install_music_dashboard_patch
from nekosuneai.ytdlp_nightly_patch import install_ytdlp_nightly_patch
from nekosuneai.dashboard_runtime_fix_patch import install_dashboard_runtime_fix_patch
from nekosuneai.tts_busy_guard_patch import install_tts_busy_guard_patch
from nekosuneai.bridge_edge_voice_patch import install_bridge_edge_voice_patch
from nekosuneai.kinect_vision_patch import install_kinect_vision_patch
from nekosuneai.dashboard_tts_config_patch import install_dashboard_tts_config_patch
from nekosuneai.media_youtube_provider_patch import install_media_youtube_provider_patch
from nekosuneai.vosk_model_auto_patch import install_vosk_model_auto_patch

# Vosk profile selection runs before launcher/config import so Raspberry Pi 5
# systems with enough RAM can use the more accurate lgraph model automatically.
install_vosk_model_auto_patch()

# HTTP route wrappers must be installed before webserver.py is imported by the
# dashboard patches below. Avatar wraps first, scam routes next, then the caller
# sync wrapper takes ownership of the Android caller-ID endpoint and logs every
# delivered call (important, unknown, or scam) for visibility/debugging.
install_avatar_http_patch()
install_scam_call_patch()
install_call_sync_patch()

# scam_call_patch imports webserver while installing its own HTTP wrapper. That
# leaves webserver's local ThreadingHTTPServer name pointing at that older
# wrapper even after call_sync_patch replaces http.server.ThreadingHTTPServer.
# Rebind it to the final wrapper so /api/call-events and the caller-sync POST
# route do not fall through to BaseHTTPRequestHandler's HTML 404 response.
from nekosuneai import webserver as _webserver
_webserver.ThreadingHTTPServer = http.server.ThreadingHTTPServer

install_mcp_oauth_recovery()
install_settings_dashboard_patch()
install_settings_backend_patch()
install_settings_dashboard_compat()
install_music_resource_guard_patch()
install_music_dashboard_patch()
install_ytdlp_nightly_patch()
install_dashboard_runtime_fix_patch()
install_tts_busy_guard_patch()
install_bridge_edge_voice_patch()
install_kinect_vision_patch()
install_dashboard_tts_config_patch()
install_media_youtube_provider_patch()

from nekosuneai.launcher import main


if __name__ == "__main__":
    main()
