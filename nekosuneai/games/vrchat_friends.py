"""VRChat friends system — opt-in, credential-gated.

Ported from the NekoSuneAI reference implementation's Node.js bot
(``Modules/FriendsSystem/Modules/VRChat.js`` at
github.com/NekoSuneAI/nekosuneai-public@1.0.3-potatopcbranch), translated to the
official VRChat web API Python client instead of hand-rolled HTTP calls.

Uses VRChat's **unofficial** web API (login + a live websocket) rather than the
supported OSC API the rest of ``games/`` relies on — this is why it's a fully
separate, opt-in service instead of part of ``VRChatDriver``: it needs your
VRChat username/password (+ TOTP secret for 2FA) and carries real ToS risk (see
TODO.md). It never starts unless ``vrchat_friends_enabled`` is on AND
credentials are set.

What it does, once enabled:
  * Logs in (with TOTP 2FA if configured) and auto-accepts any friend requests
    already waiting.
  * Opens a live websocket to VRChat's pipeline for friend online/offline
    awareness and new friend requests, dispatching each as a short event string
    to the ``on_event`` callback (same "narrate to chat + speak" shape the
    watch/game features already use).
  * Sends a paged "thanks for the friend request" OSC chatbox message when a
    request is accepted (reuses games.vrchat.send_chatbox_message).

Deliberately NOT ported from the reference: its blacklist-scan (hits a
third-party moderation service specific to the original bot's deployment) and
its Discord webhook notifications — neither is part of this app.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

from ..config import Config
from .vrchat import send_chatbox_message

RECONNECT_DELAY_SECONDS = 5.0

VRCHAT_EXTRAS_HINT = (
    "VRChat friends support needs: pip install vrchatapi pyotp websocket-client"
)


class VRChatFriendsService:
    """Background login + websocket + auto-accept loop. One instance per app run."""

    def __init__(self, config: Config, on_event: Callable[[str], None]) -> None:
        self.config = config
        self.on_event = on_event
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ws: Any = None
        self._api_client: Any = None
        self._notifications_api: Any = None
        self._friends_api: Any = None
        self._osc_client: Any = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        if not self.config.vrchat_friends_enabled:
            raise RuntimeError("Set VRCHAT_FRIENDS_ENABLED=true in .env to use this.")
        if not self.config.vrchat_username or not self.config.vrchat_password:
            raise RuntimeError(
                "Set VRCHAT_USERNAME and VRCHAT_PASSWORD in .env (and "
                "VRCHAT_TOTP_SECRET if your account has 2FA)."
            )
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="NekoSuneAIVRChatFriends", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None

    # ── login ────────────────────────────────────────────────────────────────

    def _generate_totp_code(self) -> str:
        if not self.config.vrchat_totp_secret:
            return ""
        import pyotp  # type: ignore

        return pyotp.TOTP(self.config.vrchat_totp_secret).now()

    def _login(self) -> str:
        """Log in (handling 2FA) and return the raw ``auth`` cookie value used
        to authenticate the pipeline websocket."""
        try:
            import vrchatapi  # type: ignore
            from vrchatapi.api import authentication_api, friends_api, notifications_api  # type: ignore
            from vrchatapi.exceptions import UnauthorizedException  # type: ignore
            from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode  # type: ignore
            from vrchatapi.models.two_factor_email_code import TwoFactorEmailCode  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dep
            raise RuntimeError(VRCHAT_EXTRAS_HINT) from exc

        configuration = vrchatapi.Configuration(
            username=self.config.vrchat_username,
            password=self.config.vrchat_password,
        )
        api_client = vrchatapi.ApiClient(configuration)
        api_client.user_agent = "NekoSuneAI/1.0 (github.com/NekoSuneProjects/NekoSuneAI)"
        auth_api = authentication_api.AuthenticationApi(api_client)

        try:
            auth_api.get_current_user()
        except UnauthorizedException as exc:
            if exc.status != 200:
                raise RuntimeError(f"VRChat login failed: {exc}") from exc
            reason = str(getattr(exc, "reason", "") or "")
            if "Email 2 Factor Authentication" in reason:
                raise RuntimeError(
                    "This VRChat account uses email 2FA, which needs an interactive "
                    "code entry this background service can't do. Use an authenticator "
                    "app (TOTP) with VRCHAT_TOTP_SECRET instead."
                ) from exc
            if "2 Factor Authentication" in reason:
                code = self._generate_totp_code()
                if not code:
                    raise RuntimeError(
                        "This VRChat account needs 2FA. Set VRCHAT_TOTP_SECRET in .env."
                    ) from exc
                auth_api.verify2_fa(two_factor_auth_code=TwoFactorAuthCode(code))
                auth_api.get_current_user()
            else:
                raise RuntimeError(f"VRChat login failed: {exc}") from exc

        self._api_client = api_client
        self._notifications_api = notifications_api.NotificationsApi(api_client)
        self._friends_api = friends_api.FriendsApi(api_client)

        cookie_jar = api_client.rest_client.cookie_jar._cookies.get("api.vrchat.cloud", {}).get("/", {})
        auth_cookie = cookie_jar.get("auth")
        if auth_cookie is None:
            raise RuntimeError("VRChat login succeeded but no auth cookie was issued.")
        return auth_cookie.value

    # ── OSC chatbox (independent of VRChatDriver — this service can run without it) ──

    def _osc(self) -> Any:
        if self._osc_client is None:
            from pythonosc.udp_client import SimpleUDPClient  # type: ignore

            self._osc_client = SimpleUDPClient(
                self.config.vrchat_osc_host, self.config.vrchat_osc_port
            )
        return self._osc_client

    def _send_chatbox(self, text: str) -> None:
        try:
            send_chatbox_message(self._osc(), text)
        except Exception as exc:
            self.on_event(f"[VRChat friends] Could not send chatbox message: {exc}")

    # ── friend requests ──────────────────────────────────────────────────────

    def _friend_count(self) -> int | None:
        try:
            return len(self._friends_api.get_friends())
        except Exception:
            return None

    def _accept_friend_request(self, notification_id: str, sender_name: str) -> None:
        try:
            self._notifications_api.accept_friend_request(notification_id)
        except Exception as exc:
            self.on_event(f"[VRChat friends] Could not accept {sender_name}'s request: {exc}")
            return

        count = self._friend_count()
        count_text = f", now over {count} friends" if count is not None else ""
        self.on_event(f"Accepted a friend request from {sender_name}{count_text}.")
        self._send_chatbox(f"Thank you for the friend request, {sender_name}{count_text}!")

    def _accept_pending_friend_requests(self) -> None:
        try:
            notifications = self._notifications_api.get_notifications(type="friendRequest")
        except Exception as exc:
            self.on_event(f"[VRChat friends] Could not check pending friend requests: {exc}")
            return

        pending = list(notifications or [])
        if not pending:
            return
        for notification in pending:
            sender_name = getattr(notification, "sender_username", "someone")
            self._accept_friend_request(notification.id, sender_name)
        self.on_event(f"Caught up on {len(pending)} pending friend request(s).")

    # ── websocket ────────────────────────────────────────────────────────────

    def _handle_ws_message(self, raw: str) -> None:
        try:
            envelope = json.loads(raw)
            content = json.loads(envelope.get("content", "{}"))
        except (ValueError, TypeError):
            return

        message_type = envelope.get("type")
        if message_type == "friend-online":
            name = content.get("user", {}).get("displayName", "A friend")
            self.on_event(f"{name} just came online in VRChat.")
        elif message_type == "friend-offline":
            name = content.get("user", {}).get("displayName", "A friend")
            self.on_event(f"{name} went offline.")
        elif message_type == "notification" and content.get("type") == "friendRequest":
            sender_name = content.get("senderUsername", "someone")
            self._accept_friend_request(content.get("id"), sender_name)

    def _connect_and_listen(self, auth_token: str) -> None:
        try:
            import websocket  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dep
            raise RuntimeError(VRCHAT_EXTRAS_HINT) from exc

        def on_message(_ws: Any, message: str) -> None:
            self._handle_ws_message(message)

        def on_open(_ws: Any) -> None:
            self.on_event("Connected to VRChat — watching for friend activity.")

        self._ws = websocket.WebSocketApp(
            f"wss://pipeline.vrchat.cloud/?authToken={auth_token}",
            on_message=on_message,
            on_open=on_open,
        )
        self._ws.run_forever()  # blocks until closed (stop() or connection drop)

    def _run_loop(self) -> None:
        try:
            auth_token = self._login()
        except RuntimeError as exc:
            self.on_event(f"[VRChat friends] {exc}")
            return

        self._accept_pending_friend_requests()

        while not self._stop_event.is_set():
            try:
                self._connect_and_listen(auth_token)
            except RuntimeError as exc:
                self.on_event(f"[VRChat friends] {exc}")
                return
            except Exception as exc:
                self.on_event(f"[VRChat friends] Connection error: {exc}")
            if self._stop_event.is_set():
                break
            time.sleep(RECONNECT_DELAY_SECONDS)
