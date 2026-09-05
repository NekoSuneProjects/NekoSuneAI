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
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #0b0f14; color: #f4f7fb; font: 15px/1.4 -apple-system, "Segoe UI", Roboto, sans-serif; padding: 14px 14px 40px; }
  h1 { font-size: 18px; margin: 0 0 2px; }
  .muted { color: #93a4b7; font-size: 12px; margin: 0 0 16px; }
  .card { background: #151e28; border: 1px solid #24303d; border-radius: 12px; padding: 14px; margin-bottom: 12px; }
  .card h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #93a4b7; margin: 0 0 10px; }
  .row { display: flex; justify-content: space-between; gap: 10px; padding: 4px 0; font-size: 13px; }
  .row span:first-child { color: #93a4b7; }
  .log { white-space: pre-wrap; font-size: 12px; background: #0f151c; border-radius: 8px; padding: 10px; max-height: 200px; overflow-y: auto; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
  .ok { background: #16352c; color: #2ed69b; }
  .bad { background: #3a1820; color: #ff9aa6; }
</style>
</head>
<body>
  <h1>NekoSuneAI &mdash; Pi Proxy</h1>
  <p class="muted" id="updated">Loading&hellip;</p>

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
  </div>

  <div class="card">
    <h2>Backend connection</h2>
    <div class="row"><span>Docker backend</span><span id="backend"></span></div>
  </div>

<script>
function setText(id, text) { document.getElementById(id).textContent = text; }
function pill(ok, textOk, textBad) {
  return '<span class="pill ' + (ok ? 'ok' : 'bad') + '">' + (ok ? textOk : textBad) + '</span>';
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
    setText('cam-cue', cam.has_context ? 'has a recent visual cue' : (cam.error || 'none'));

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
