from __future__ import annotations

from urllib.parse import urlsplit


def install_mcp_oauth_recovery() -> None:
    """Patch the lightweight MCP client with clearer, RFC-friendly refresh handling.

    The bridge rotates refresh tokens. A failed refresh used to bubble up as a raw
    requests `400 Client Error`, which made scheduled monitors noisy and gave no clue
    whether the saved grant had expired/revoked. This keeps refresh-token rotation
    persisted and returns a useful reconnect message for invalid grants.
    """
    from . import mcp_client

    if getattr(mcp_client.McpClient, "_neko_refresh_patch", False):
        return

    def _refresh_oauth(self) -> bool:
        s = self.server
        if not (s.oauth_refresh_token and s.oauth_client_id and s.oauth_token_url):
            return False

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": s.oauth_refresh_token,
            "client_id": s.oauth_client_id,
        }
        # RFC 8707 resource indicators are harmless for servers that ignore them,
        # and keep the refresh bound to the MCP resource for bridges that validate it.
        if s.url:
            payload["resource"] = s.url
        if s.oauth_client_secret:
            payload["client_secret"] = s.oauth_client_secret

        response = self.session.post(s.oauth_token_url, data=payload, timeout=self.timeout)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            code = str(body.get("error") or "oauth_refresh_failed")
            detail = str(body.get("error_description") or body.get("error") or response.text or "OAuth refresh failed").strip()
            if code == "invalid_grant":
                raise RuntimeError(
                    f"OAuth connection for '{s.name}' expired or was revoked. "
                    "Open Settings > Remote MCP & NekoAI Bridge and connect OAuth again."
                )
            raise RuntimeError(f"OAuth refresh for '{s.name}' failed (HTTP {response.status_code}): {detail[:400]}")

        body = response.json()
        access = body.get("access_token")
        if not access:
            raise RuntimeError(f"OAuth refresh for '{s.name}' returned no access_token.")
        s.oauth_access_token = str(access)
        # nekoai-bridge rotates refresh tokens: always persist the newest one.
        s.oauth_refresh_token = str(body.get("refresh_token") or s.oauth_refresh_token)
        if self.credentials_changed:
            self.credentials_changed(s)
        return True

    mcp_client.McpClient._refresh_oauth = _refresh_oauth
    mcp_client.McpClient._neko_refresh_patch = True
