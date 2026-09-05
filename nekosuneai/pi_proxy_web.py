"""Read-only, mobile-friendly local status page for a Pi Proxy node.

Modeled directly on Windows/nekosuneai/web_status_server.py: stdlib
http.server.ThreadingHTTPServer, a single inline HTML+CSS+JS string, a
/api/status JSON endpoint, no external dependencies. It is intentionally
view-only -- there is no control/command path here, only the same read-only
status PiProxyAgent already tracks for itself, so this can't become a second,
less-guarded way to drive audio/Bluetooth. Not authenticated: only run this
on a network you trust, never forward the port to the public internet.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>NekoSuneAI Pi Proxy</title>
<style>
  /* Same "nova" violet/cyan palette as the Docker dashboard's dark theme
     (Docker/nekosuneai/static/index.html), reproduced in plain CSS -- no
     Tailwind CDN here, this page stays dependency-free and view-only, with
     no login/token: unlike the full dashboard, there is nothing to
     authenticate into, only read-only status a phone on the LAN can see. */
  :root {
    color-scheme: dark;
    --bg: #080914; --surface: #111329; --surface2: #181b38; --border: #292d55;
    --text: #f4f2ff; --muted: #8489b8; --muted2: #b3b7dc;
    --accent: #a78bfa; --accent-h: #c4b5fd; --cyan: #67e8f9;
    --ok-bg: rgba(34,197,94,0.12); --ok-fg: #4ade80; --ok-border: rgba(34,197,94,0.35);
    --bad-bg: rgba(248,113,113,0.12); --bad-fg: #f87171; --bad-border: rgba(248,113,113,0.35);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.4 -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 18px 16px 40px;
    background-image:
      radial-gradient(circle at 85% 5%, rgba(124,58,237,.18), transparent 32%),
      radial-gradient(circle at 18% 92%, rgba(34,211,238,.09), transparent 30%);
    background-attachment: fixed;
  }
  h1 { font-size: 19px; font-weight: 800; letter-spacing: -.01em; margin: 0; }
  .brand { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
  .brand-dot {
    width: 10px; height: 10px; border-radius: 50%; background: var(--cyan);
    box-shadow: 0 0 10px var(--cyan); flex-shrink: 0;
  }
  .kicker { color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }
  .muted { color: var(--muted); font-size: 12px; margin: 2px 0 18px; }
  .grid { display: grid; grid-template-columns: 1fr; gap: 12px; max-width: 560px; margin: 0 auto; }
  @media (min-width: 720px) { .grid { grid-template-columns: 1fr 1fr; max-width: 1100px; } }
  .card {
    background: linear-gradient(145deg, rgba(25,28,58,.88), rgba(14,16,36,.94));
    border: 1px solid var(--border); border-radius: 16px; padding: 16px;
    box-shadow: 0 1px 0 rgba(255,255,255,.02) inset, 0 8px 24px -12px rgba(0,0,0,.6);
  }
  .card h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); margin: 0 0 12px; font-weight: 700; }
  .row { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 5px 0; font-size: 13px; border-bottom: 1px solid rgba(120,126,190,.08); }
  .row:last-child { border-bottom: none; }
  .row span:first-child { color: var(--muted); }
  .row.error span:last-child { color: var(--bad-fg); font-size: 12px; text-align: right; }
  .log { white-space: pre-wrap; font-size: 12px; background: #0d0f24; border: 1px solid var(--border); border-radius: 10px; padding: 10px; max-height: 200px; overflow-y: auto; color: var(--muted2); margin-top: 8px; }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; border: 1px solid transparent; }
  .ok { background: var(--ok-bg); color: var(--ok-fg); border-color: var(--ok-border); }
  .bad { background: var(--bad-bg); color: var(--bad-fg); border-color: var(--bad-border); }
  [hidden] { display: none !important; }
</style>
</head>
<body>
  <div class="brand"><span class="brand-dot"></span><h1>NekoSune<span style="color:var(--accent)">AI</span> &mdash; Pi Proxy</h1></div>
  <p class="muted"><span class="kicker" id="updated">Loading&hellip;</span></p>

  <div class="grid">

  <div class="card">
    <h2>Pairing</h2>
    <div class="row"><span>Node</span><span id="node-id"></span></div>
    <div class="row"><span>Paired</span><span id="paired"></span></div>
    <div class="row"><span>Local input</span><span id="input"></span></div>
  </div>

  <div class="card">
    <h2>Bluetooth speaker</h2>
    <div class="row"><span>Link</span><span id="bt-link"></span></div>
    <div class="row"><span>Device</span><span id="bt-name"></span></div>
    <div class="row"><span>Sink ready</span><span id="bt-ready"></span></div>
    <div class="log" id="bt-log">&mdash;</div>
  </div>

  <div class="card">
    <h2>Audio / music</h2>
    <div class="row"><span>Speaking (TTS)</span><span id="speaking"></span></div>
    <div class="row"><span>Music playing</span><span id="music"></span></div>
  </div>

  <div class="card">
    <h2>Recent commands</h2>
    <div class="log" id="commands">&mdash;</div>
  </div>

  <div class="card">
    <h2>Wake word</h2>
    <div class="row"><span>Listening</span><span id="ww-listening"></span></div>
    <div class="row"><span>Model</span><span id="ww-model"></span></div>
    <div class="row"><span>Last transcript</span><span id="ww-transcript"></span></div>
    <div class="row error" id="ww-error-row" hidden><span>Error</span><span id="ww-error"></span></div>
  </div>

  <div class="card">
    <h2>Consoles</h2>
    <div class="row"><span>PlayStation</span><span id="console-ps"></span></div>
    <div class="row"><span>Xbox</span><span id="console-xbox"></span></div>
  </div>

  <div class="card">
    <h2>Kinect camera</h2>
    <div class="row"><span>Vision</span><span id="cam-running"></span></div>
    <div class="row"><span>Last frame</span><span id="cam-frame"></span></div>
    <div class="row"><span>Last cue</span><span id="cam-cue"></span></div>
    <div class="row error" id="cam-error-row" hidden><span>Error</span><span id="cam-error"></span></div>
  </div>

  <div class="card">
    <h2>Backend connection</h2>
    <div class="row"><span>Docker backend</span><span id="backend"></span></div>
  </div>

  </div>

<script>
function setText(id, text) { document.getElementById(id).textContent = text; }
function pill(ok, textOk, textBad) {
  return '<span class="pill ' + (ok ? 'ok' : 'bad') + '">' + (ok ? textOk : textBad) + '</span>';
}
function setError(rowId, textId, message) {
  const row = document.getElementById(rowId);
  if (message) { setText(textId, message); row.hidden = false; } else { row.hidden = true; }
}
async function refresh() {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    const s = await res.json();
    setText('updated', 'Updated ' + new Date(s.epoch * 1000).toLocaleTimeString());
    setText('node-id', s.node_id || 'unknown');
    document.getElementById('paired').innerHTML = pill(!!s.paired, 'paired', 'not paired');
    document.getElementById('input').innerHTML = pill(!s.input_disabled, 'enabled', 'disabled');

    const bt = s.bluetooth || {};
    document.getElementById('bt-link').innerHTML = pill(!!bt.connected, 'connected', 'disconnected');
    setText('bt-name', bt.name || bt.address || 'not detected');
    document.getElementById('bt-ready').innerHTML = pill(!!bt.ready, 'ready', 'not ready');
    setText('bt-log', (s.bluetooth_events || []).slice(-8).join('\\n') || 'No events yet.');

    document.getElementById('speaking').innerHTML = pill(!!s.audio_speaking, 'playing', 'idle');
    document.getElementById('music').innerHTML = pill(!!s.music_playing, 'playing', 'idle');

    setText('commands', (s.recent_commands || []).slice(-10).join('\\n') || 'No commands yet.');

    const ww = s.wake_word || {};
    document.getElementById('ww-listening').innerHTML = pill(!!ww.enabled && !!ww.running, 'listening', ww.enabled ? 'starting…' : 'disabled');
    setText('ww-model', ww.model || 'not configured');
    let wwTranscript = ww.last_transcript || 'No transcript yet.';
    if (ww.last_transcript && ww.last_transcript_at) {
      wwTranscript += ' (' + new Date(ww.last_transcript_at * 1000).toLocaleTimeString() + ')';
    }
    setText('ww-transcript', wwTranscript);
    // If the wake-word thread died (bad mic index, model download failed,
    // device busy, ...), "enabled" stays true but "running" goes false
    // forever and nothing else here explains why -- surface ww.error
    // directly instead of leaving it a silent permanent "starting…".
    setError('ww-error-row', 'ww-error', ww.enabled && !ww.running ? ww.error : '');

    function consoleText(item) {
      if (!item) return 'unknown';
      let text = item.state || (item.online ? 'online' : 'offline');
      if (item.active_title) text += ' — ' + item.active_title;
      return text;
    }
    const consoles = s.console || {};
    setText('console-ps', consoleText(consoles.playstation));
    setText('console-xbox', consoleText(consoles.xbox));

    const cam = s.camera || {};
    document.getElementById('cam-running').innerHTML = pill(!!cam.enabled && !!cam.running, 'watching', cam.enabled ? 'starting…' : 'disabled');
    setText('cam-frame', cam.last_frame_age_seconds != null ? (cam.last_frame_age_seconds + 's ago') : 'no frame yet');
    setText('cam-cue', cam.has_context ? 'has a recent visual cue' : 'none');
    setError('cam-error-row', 'cam-error', cam.enabled && cam.error ? cam.error : '');

    document.getElementById('backend').innerHTML = pill(s.backend_reachable !== false, 'reachable', 'unreachable (offline mode)');
  } catch (err) {
    setText('updated', 'Disconnected — retrying…');
  }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


def _local_ip() -> str:
    """Best-effort LAN IP (no packets actually sent) for a "visit this on
    your phone" address without guessing which NIC."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


class _Handler(BaseHTTPRequestHandler):
    server: "PiProxyWebStatusServer"  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_bytes(_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/status":
            try:
                payload = self.server.owner.status()
            except Exception as exc:
                payload = {"error": str(exc)[:300], "epoch": time.time()}
            self._send_bytes(json.dumps(payload).encode("utf-8"), "application/json")
        else:
            self.send_response(404)
            self.end_headers()


class PiProxyWebStatusServer:
    def __init__(self, agent: Any, host: str = "0.0.0.0", port: int = 8799) -> None:
        self.agent = agent
        self.host = host
        self.port = int(port)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.owner = self.agent  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="pi-proxy-web-status")
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
        self._httpd = None
        self._thread = None

    def is_running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    def local_url(self) -> str:
        return f"http://{_local_ip()}:{self.port}/"
