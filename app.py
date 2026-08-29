from nekosuneai.avatar_http_patch import install_avatar_http_patch
from nekosuneai.mcp_oauth_recovery import install_mcp_oauth_recovery
from nekosuneai.settings_dashboard_patch import install_settings_dashboard_patch

install_avatar_http_patch()
install_mcp_oauth_recovery()
install_settings_dashboard_patch()

from nekosuneai.launcher import main


if __name__ == "__main__":
    main()
