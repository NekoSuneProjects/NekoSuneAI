"""Small, dependency-free Streamable HTTP MCP client.

Supports bearer/API-key authentication and OAuth access-token refresh.  It is
kept on ``requests`` so it remains inexpensive on Raspberry Pi systems.
"""
from __future__ import annotations

import json
import base64
import hashlib
import secrets
import threading
from urllib.parse import urlencode, urlsplit
from dataclasses import dataclass, field
from typing import Any

import requests

from .config import Config


@dataclass
class McpServerConfig:
    name: str
    url: str
    auth: str = "api_key"  # none | api_key | oauth
    bearer_token: str | None = None
    api_key: str | None = None
    api_key_header: str = "X-API-Key"
    oauth_access_token: str | None = None
    oauth_refresh_token: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_token_url: str | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "McpServerConfig":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})


def load_servers(config: Config) -> list[McpServerConfig]:
    try:
        raw = json.loads(config.mcp_servers_json or "[]")
    except ValueError as exc:
        raise RuntimeError("MCP server settings are not valid JSON.") from exc
    if isinstance(raw, dict):
        raw = raw.get("servers", [])
    if not isinstance(raw, list):
        raise RuntimeError("MCP_SERVERS_JSON must be a list or {\"servers\": [...]}.")
    return [McpServerConfig.from_dict(item) for item in raw if isinstance(item, dict)]


class McpClient:
    def __init__(self, server: McpServerConfig, timeout: float = 30, credentials_changed=None) -> None:
        self.server = server
        self.timeout = timeout
        self.session = requests.Session()
        self.session_id: str | None = None
        self._request_id = 0
        self._lock = threading.RLock()
        self.credentials_changed = credentials_changed

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        token = self.server.oauth_access_token if self.server.auth == "oauth" else self.server.bearer_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if self.server.auth == "api_key" and self.server.api_key:
            headers[self.server.api_key_header or "X-API-Key"] = self.server.api_key
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    @staticmethod
    def _decode(response: requests.Response) -> dict[str, Any]:
        if not response.content or not response.text.strip():
            return {}
        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" not in content_type:
            value = response.json()
            return value if isinstance(value, dict) else {"result": value}
        for line in reversed(response.text.splitlines()):
            if line.startswith("data:"):
                value = json.loads(line[5:].strip())
                if isinstance(value, dict):
                    return value
        raise RuntimeError("MCP server returned an empty event stream.")

    def _refresh_oauth(self) -> bool:
        s = self.server
        if not (s.oauth_refresh_token and s.oauth_client_id and s.oauth_token_url):
            return False
        payload = {"grant_type": "refresh_token", "refresh_token": s.oauth_refresh_token, "client_id": s.oauth_client_id}
        if s.oauth_client_secret:
            payload["client_secret"] = s.oauth_client_secret
        response = self.session.post(s.oauth_token_url, data=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        s.oauth_access_token = body["access_token"]
        s.oauth_refresh_token = body.get("refresh_token", s.oauth_refresh_token)
        if self.credentials_changed:
            self.credentials_changed(s)
        return True

    def _post(self, payload: dict[str, Any], retry_auth: bool = True) -> dict[str, Any]:
        response = self.session.post(self.server.url, headers=self._headers(), json=payload, timeout=self.timeout)
        if response.status_code == 401 and retry_auth and self.server.auth == "oauth" and self._refresh_oauth():
            return self._post(payload, retry_auth=False)
        if response.status_code >= 400:
            detail = response.text.strip()[:500]
            raise RuntimeError(f"MCP server '{self.server.name}' returned HTTP {response.status_code}: {detail}")
        self.session_id = response.headers.get("Mcp-Session-Id", self.session_id)
        return self._decode(response)

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            self._request_id += 1
            message = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
            if params is not None:
                message["params"] = params
            body = self._post(message)
            if "error" in body:
                raise RuntimeError(str(body["error"].get("message", body["error"])))
            return body.get("result")

    def initialize(self) -> None:
        if self.session_id:
            return
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "NekoSuneAI", "version": "0.1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        result = self._rpc("tools/list", {}) or {}
        return result.get("tools", []) if isinstance(result, dict) else []

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        return result if isinstance(result, dict) else {"content": result}


_CLIENTS: dict[str, McpClient] = {}
_OAUTH_PENDING: dict[str, dict[str, str]] = {}


def _persist_oauth_server(config: Config, updated: McpServerConfig) -> None:
    raw = json.loads(config.mcp_servers_json or "[]")
    servers = raw.get("servers", []) if isinstance(raw, dict) else raw
    for item in servers:
        if isinstance(item, dict) and item.get("name") == updated.name:
            item.update({
                "auth": "oauth",
                "oauth_access_token": updated.oauth_access_token,
                "oauth_refresh_token": updated.oauth_refresh_token,
                "oauth_client_id": updated.oauth_client_id,
                "oauth_client_secret": updated.oauth_client_secret,
                "oauth_token_url": updated.oauth_token_url,
            })
            for key in ("bearer_token", "api_key", "api_key_header"):
                item.pop(key, None)
    config.mcp_servers_json = json.dumps(raw, separators=(",", ":"))
    try:
        from . import database
        store = json.loads(database.get_state("app_settings", "{}") or "{}")
        store["mcp_servers_json"] = config.mcp_servers_json
        database.set_state("app_settings", json.dumps(store))
    except Exception:
        pass


def begin_oauth(config: Config, server_name: str, redirect_uri: str) -> str:
    server = next((s for s in load_servers(config) if s.name == server_name), None)
    if not server:
        raise RuntimeError(f"MCP server '{server_name}' was not found.")
    parts = urlsplit(server.url)
    origin = f"{parts.scheme}://{parts.netloc}"
    metadata = requests.get(f"{origin}/.well-known/oauth-authorization-server", timeout=config.mcp_timeout_seconds)
    metadata.raise_for_status()
    oauth = metadata.json()
    register_url = oauth.get("registration_endpoint")
    if not register_url:
        raise RuntimeError("MCP OAuth server does not advertise dynamic client registration.")
    registration = requests.post(register_url, json={
        "client_name": "NekoSuneAI",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "application_type": "web",
    }, timeout=config.mcp_timeout_seconds)
    registration.raise_for_status()
    client = registration.json()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    _OAUTH_PENDING[state] = {
        "server_name": server.name, "client_id": client["client_id"],
        "verifier": verifier, "redirect_uri": redirect_uri,
        "token_url": oauth["token_endpoint"], "client_secret": client.get("client_secret", ""),
    }
    params = {
        "response_type": "code", "client_id": client["client_id"],
        "redirect_uri": redirect_uri, "scope": "mcp offline_access profile realtime weather aircraft emergency-alerts",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "resource": server.url,
    }
    return f"{oauth['authorization_endpoint']}?{urlencode(params)}"


def complete_oauth(config: Config, state: str, code: str) -> None:
    pending = _OAUTH_PENDING.pop(state, None)
    if not pending:
        raise RuntimeError("OAuth state is invalid or expired. Start Connect OAuth again.")
    payload = {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": pending["redirect_uri"], "client_id": pending["client_id"],
        "code_verifier": pending["verifier"],
    }
    if pending["client_secret"]:
        payload["client_secret"] = pending["client_secret"]
    response = requests.post(pending["token_url"], data=payload, timeout=config.mcp_timeout_seconds)
    response.raise_for_status()
    token = response.json()
    server = McpServerConfig(
        name=pending["server_name"], url="", auth="oauth",
        oauth_access_token=token["access_token"], oauth_refresh_token=token.get("refresh_token"),
        oauth_client_id=pending["client_id"], oauth_client_secret=pending["client_secret"] or None,
        oauth_token_url=pending["token_url"],
    )
    _persist_oauth_server(config, server)
    for client in _CLIENTS.values():
        if client.server.name == server.name:
            client.session_id = None


def get_clients(config: Config) -> list[McpClient]:
    clients: list[McpClient] = []
    for server in load_servers(config):
        if not server.enabled or not server.url:
            continue
        key = f"{server.name}:{server.url}"
        client = _CLIENTS.get(key)
        if client is None:
            client = _CLIENTS[key] = McpClient(server, config.mcp_timeout_seconds, lambda s: _persist_oauth_server(config, s))
        else:
            client.server = server
            client.credentials_changed = lambda s: _persist_oauth_server(config, s)
        clients.append(client)
    return clients


_ROUTES: list[tuple[tuple[str, ...], str]] = [
    (("tornado",), "tornado_tracker"), (("hurricane", "cyclone", "tropical storm"), "hurricane_tracker"),
    (("emergency alert", "emergency warning", "emergency broadcast", "government alert", "government warning"), "emergency_alerts"), (("military aircraft", "military plane"), "military_aircraft_nearby"),
    (("track flight", "track aircraft", "flight radar"), "track_aircraft"), (("aircraft", "plane", "flight nearby"), "aircraft_nearby"),
    (("weather warning", "met office warning"), "weather_warnings"), (("weather radar", "rain radar", "radar"), "weather_radar"),
    (("rain", "weather", "forecast", "lightning", "thunder"), "weather_now"),
]


def route_tool(user_text: str) -> tuple[str, dict[str, Any]] | None:
    text = user_text.strip()
    lowered = text.lower()
    explicit = __import__("re").match(r"^/mcp\s+([\w.-]+)(?:\s+(\{.*\}))?$", text, __import__("re").S)
    if explicit:
        return explicit.group(1), json.loads(explicit.group(2) or "{}")
    for words, tool in _ROUTES:
        if any(word in lowered for word in words):
            args: dict[str, Any] = {}
            # Preserve the requested area instead of silently falling back to
            # the bridge account's home location.
            location_match = __import__("re").search(
                r"\b(?:in|around|near|for)\s+([A-Za-z][A-Za-z .,'-]{2,80}?)(?=\s+(?:every|within|each|and\s+keep|until)\b|[?.!,]|$)",
                text, __import__("re").I,
            )
            if location_match and location_match.group(1).strip().lower() not in {"me", "here", "home"}:
                args["location"] = location_match.group(1).strip()
            if tool == "emergency_alerts":
                region_match = __import__("re").search(r"\b(?:uk|gb|united kingdom|britain|us|usa|united states|australia|finland|global)\b", lowered)
                if region_match:
                    region = region_match.group(0)
                    args["region"] = {"uk":"GB", "united kingdom":"GB", "britain":"GB", "usa":"US", "united states":"US", "australia":"AU", "finland":"FI"}.get(region, region.upper())
                    args["scope"] = "region"
            radius_match = __import__("re").search(r"\b(?:within|radius(?:\s+of)?)\s+(\d+(?:\.\d+)?)\s*(?:nm|nautical miles?|miles?)", lowered)
            if radius_match and "aircraft" in tool:
                args["radius_nm"] = max(1, min(250, float(radius_match.group(1))))
            if tool == "track_aircraft":
                if "radius_nm" in args or ("location" in args and not __import__("re").search(r"\b(?:flight|callsign|registration)\s+[A-Z0-9-]{3,12}\b", text, __import__("re").I)):
                    return "aircraft_nearby", args
                match = __import__("re").search(r"\b(?:track|flight)\s+([A-Z0-9-]{3,12})\b", text, __import__("re").I)
                if match and match.group(1).lower() not in {"aircraft", "planes", "within", "around", "near"}: args["query"] = match.group(1)
                else: return "aircraft_nearby", {}
            return tool, args
    return None


def call_first_available(config: Config, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    for client in get_clients(config):
        try:
            return client.call_tool(tool, arguments)
        except Exception as exc:
            errors.append(f"{client.server.name}: {exc}")
    raise RuntimeError("; ".join(errors) or "No enabled MCP servers are configured.")


def fetch_mcp_context(user_text: str, config: Config) -> tuple[str | None, str]:
    if not config.mcp_enabled or not config.mcp_auto_route:
        return None, "none"
    routed = route_tool(user_text)
    if not routed:
        return None, "none"
    tool, arguments = routed
    errors: list[str] = []
    for client in get_clients(config):
        try:
            result = client.call_tool(tool, arguments)
            serialized = json.dumps(result, ensure_ascii=False, indent=2)
            lowered = serialized.lower()
            danger = any(x in lowered for x in ('"severity": "extreme"', '"severity": "severe"', 'tornado warning', 'immediate threat'))
            warning = danger or any(x in lowered for x in ("warning", "alert", "hazard", "thunderstorm"))
            return f"Remote MCP tool `{tool}` returned this current data. Use it accurately and mention uncertainty/coverage limits:\n{serialized[:12000]}", ("danger" if danger else "warning" if warning else "none")
        except Exception as exc:
            errors.append(f"{client.server.name}: {exc}")
    if errors:
        return "MCP lookup failed: " + "; ".join(errors), "none"
    return None, "none"
