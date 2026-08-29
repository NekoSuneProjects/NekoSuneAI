# NekoSuneAI Android / Raspberry Pi Mobile Dashboard

NekoSuneAI can run its browser dashboard on a Raspberry Pi and be used from an Android phone as an installable PWA. The same web token protects the desktop and mobile RPC endpoints.

## 1. Run NekoSuneAI web mode on the Pi

Docker already uses host networking and configures the dashboard on port `8788`.

```bash
docker compose up -d
```

Or without Docker:

```bash
python app.py --web --web-host 0.0.0.0 --web-port 8788
```

Set a permanent secret in `.env` so the phone URL does not change on every restart:

```env
WEB_DASHBOARD_TOKEN=replace-with-a-long-random-secret
```

Open the mobile UI at:

```text
https://YOUR-PI-HOSTNAME/mobile?token=YOUR_TOKEN
```

The token is copied into the Android browser's `localStorage`, then removed from the visible URL. Future launches can use `/mobile` directly.

## 2. Use HTTPS for Android PWA features

Basic chat works over plain HTTP on a trusted LAN, but Android service workers, installable-PWA behavior, and browser notifications require a secure context. Do **not** expose port 8788 directly to the public Internet.

Recommended choices:

- Tailscale + Tailscale Serve/HTTPS for private phone-to-Pi access.
- A Cloudflare Tunnel protected with Cloudflare Access.
- A normal reverse proxy with TLS if it is already restricted to trusted users.

Keep `WEB_DASHBOARD_TOKEN` enabled even behind another access layer.

## 3. Install on Android

1. Open the HTTPS `/mobile?token=...` URL in Chrome or another PWA-capable Android browser.
2. Use **Add to Home screen** / **Install app**.
3. Open the installed NekoSuneAI app.
4. Press **Enable phone alerts** and grant notification permission.

The mobile page can:

- see NekoSuneAI connection/state/model status;
- start or end a session;
- toggle voice output and microphone state;
- chat with the Pi-hosted NekoSuneAI instance;
- display warning/danger monitor alerts as Android browser notifications while the PWA is active.

## 4. Closed-app Android notifications with ntfy

Browser polling cannot reliably wake a fully closed PWA. NekoSuneAI therefore supports an optional ntfy-compatible push path for important monitor events.

Start the included ntfy service:

```bash
docker compose -f docker-compose.mobile.yml up -d
```

Choose a long random topic and add this to the NekoSuneAI `.env`:

```env
MOBILE_NOTIFY_ENABLED=true
MOBILE_NOTIFY_URL=http://127.0.0.1:2586
MOBILE_NOTIFY_TOPIC=replace-with-a-long-random-topic
MOBILE_NOTIFY_MIN_LEVEL=warning
# MOBILE_NOTIFY_TOKEN=optional-bearer-token
```

Restart NekoSuneAI after changing `.env`.

Install the ntfy Android app and subscribe to the same topic on the reachable ntfy server. If the phone is outside the home network, make the ntfy service reachable only through a private path such as Tailscale, or securely reverse-proxy it with TLS/authentication. Avoid exposing an unauthenticated ntfy server directly to the Internet.

`MOBILE_NOTIFY_MIN_LEVEL=warning` means normal informational updates are ignored. `warning` and `danger` monitor events are pushed; `danger` uses maximum ntfy priority.

## 5. Security notes

- Treat `WEB_DASHBOARD_TOKEN` like a password.
- Use a different long random value for `MOBILE_NOTIFY_TOPIC`.
- Do not commit real tokens into Git.
- Prefer Tailscale or an authenticated HTTPS tunnel rather than router port forwarding.
- The web server intentionally blocks private/underscore RPC methods and `restart_app` from remote callers.
