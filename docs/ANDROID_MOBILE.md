# NekoSuneAI Android / Raspberry Pi Companion

NekoSuneAI has two mobile options:

- the native Android companion APK;
- the browser/PWA mobile dashboard at `/mobile`.

The native APK can now discover a Docker/Pi instance on the same local network and pair without manually typing the Pi URL or `WEB_DASHBOARD_TOKEN`.

## Native Android automatic pairing

Docker already uses host networking and exposes the NekoSuneAI dashboard on port `8788`:

```bash
docker compose up -d
```

When the web server starts it advertises an mDNS/DNS-SD service named:

```text
_nekosuneai._tcp.local.
```

The visible instance name defaults to:

```text
NekoSuneAI - <hostname>
```

If you have more than one NekoSuneAI server on the same LAN, give them clearer names with:

```env
NEKOSUNEAI_INSTANCE_NAME=Pi Bedroom
```

or, on another server:

```env
NEKOSUNEAI_INSTANCE_NAME=Pi Studio
```

This is optional; the hostname is used automatically when the variable is not set.

### Pair the APK

1. Put the Android phone and Pi/server on the same local network.
2. Open **NekoSuneAI Companion**.
3. Tap **Find NekoSuneAI servers**.
4. Choose the server you want from the discovered list.
5. Tap **Request pairing**.
6. Open that NekoSuneAI Docker dashboard.
7. A **Device pairing request** card appears automatically.
8. Check the phone name/IP and press **Approve** or **Reject**.
9. After approval, the APK receives a separate device token and connects automatically.

The APK does **not** need the full dashboard/admin token for normal automatic pairing. The device token is restricted to Android companion, camera/voice and avatar endpoints; it cannot use the normal admin RPC endpoint.

Manual Pi URL + `WEB_DASHBOARD_TOKEN` entry remains under **Advanced manual connection** as a recovery/fallback option.

### Pairing security

By default:

- pairing requests are accepted only from private, loopback or link-local addresses;
- requests expire after 5 minutes;
- every pairing must be explicitly approved from the authenticated dashboard;
- approved devices receive their own random token;
- only a SHA-256 hash of the device token is persisted on the Pi;
- persistent pairings are stored inside `data/device_pairings.json`, and the normal Docker `./data:/app/data` mount keeps them across container recreates.

Optional environment values:

```env
# Default: 300 seconds
DEVICE_PAIRING_TTL_SECONDS=300

# Normally leave this false. Enabling it permits pairing requests from
# non-private addresses, which is not recommended for normal installs.
DEVICE_PAIRING_ALLOW_REMOTE=false

# Optional custom file location.
DEVICE_PAIRING_FILE=/app/data/device_pairings.json
```

mDNS is local-network discovery. It does not replace Tailscale/VPN or HTTPS when the phone is away from home. Some Wi-Fi guest/client-isolation modes and firewalls block multicast UDP 5353; use the Advanced manual connection fallback on networks where discovery is intentionally blocked.

## Native Android features

After pairing the APK can:

- chat with the Pi-hosted NekoSuneAI assistant;
- use Android speech recognition for push-to-talk;
- speak replies with Android TTS;
- load the same Pi-configured VRM avatar;
- drive avatar expressions, gestures and text-derived visemes;
- send opt-in foreground CameraX frames for vision;
- forward allowed Android notifications;
- report lightweight phone telemetry;
- receive Find My Phone / stop-ringing commands.

The native UI uses the same NekoSuneAI Studio visual language as the Docker dashboard: `#080914` background, navy/violet surfaces, violet/cyan accents, rounded cards and compact status sections. It also uses the branded launcher icon and Android splash screen with a short exit animation.

## PWA / browser mobile dashboard

The PWA still uses the normal web dashboard token.

Run web mode on the Pi:

```bash
python app.py --web --web-host 0.0.0.0 --web-port 8788
```

For a stable browser URL, set:

```env
WEB_DASHBOARD_TOKEN=replace-with-a-long-random-secret
```

Open:

```text
https://YOUR-PI-HOSTNAME/mobile?token=YOUR_TOKEN
```

The token is copied into the browser's `localStorage`, then removed from the visible URL. Future launches can use `/mobile` directly.

## HTTPS for browser/PWA features

Basic native APK pairing/chat can work over plain HTTP on a trusted LAN because the APK explicitly permits local cleartext traffic. Browser service workers, installable-PWA behavior and browser notifications require a secure context.

Do **not** expose port `8788` directly to the public Internet. Recommended remote-access choices are:

- Tailscale + Tailscale Serve/HTTPS;
- a Cloudflare Tunnel protected with Cloudflare Access;
- a normal TLS reverse proxy that is restricted to trusted users.

Keep `WEB_DASHBOARD_TOKEN` enabled even behind another access layer.

## Closed-app Android notifications with ntfy

Browser polling cannot reliably wake a fully closed PWA. NekoSuneAI therefore also supports an optional ntfy-compatible push path for important monitor events.

Start the included ntfy service:

```bash
docker compose -f docker-compose.mobile.yml up -d
```

Choose a long random topic and add this to `.env`:

```env
MOBILE_NOTIFY_ENABLED=true
MOBILE_NOTIFY_URL=http://127.0.0.1:2586
MOBILE_NOTIFY_TOPIC=replace-with-a-long-random-topic
MOBILE_NOTIFY_MIN_LEVEL=warning
# MOBILE_NOTIFY_TOKEN=optional-bearer-token
```

Restart NekoSuneAI after changing `.env`.

Install the ntfy Android app and subscribe to the same topic on the reachable ntfy server. If the phone is outside the home network, keep ntfy behind a private route such as Tailscale or a secure authenticated reverse proxy.

## Security notes

- Treat `WEB_DASHBOARD_TOKEN` like an administrator password.
- Do not copy it into the APK when automatic pairing works; use the per-device token instead.
- Do not commit real tokens into Git.
- Prefer Tailscale/VPN or authenticated HTTPS rather than router port forwarding for remote access.
- The web server blocks private/underscore RPC methods and `restart_app` from remote RPC callers.
