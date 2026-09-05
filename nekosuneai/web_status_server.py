"""Read-only, mobile-friendly local status page for the Windows gaming node.

For a one-monitor setup, the desktop app can't sit on top of a fullscreen
game the way it could on a second screen. This serves the same status a
phone on the same Wi-Fi can just load in a browser: what OCR is currently
reading off the game window, a periodically-refreshed JPEG of the captured
game view, VRChat/world-mapper status, and recent VRChat-friends/Twitch
activity. It is intentionally view-only — there is no control/command path
here, only the existing read-only observation data the agent already
collects for itself, so this can't become a second, less-guarded way to
drive game input. Not authenticated: only run this on a network you trust,
never forward the port to the public internet.
"""
from __future__ import annotations

import base64
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
<title>NekoSuneAI Windows Node</title>
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
  .frame { width: 100%; border-radius: 8px; background: #0f151c; display: block; min-height: 120px; }
  .ocr { white-space: pre-wrap; font-size: 13px; background: #0f151c; border-radius: 8px; padding: 10px; max-height: 200px; overflow-y: auto; }
  .log { white-space: pre-wrap; font-size: 12px; background: #0f151c; border-radius: 8px; padding: 10px; max-height: 160px; overflow-y: auto; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
  .ok { background: #16352c; color: #2ed69b; }
  .bad { background: #3a1820; color: #ff9aa6; }
  .stale { opacity: .5; }
  .blueprint { width: 100%; height: auto; border-radius: 8px; background: #0f151c; display: block; margin-top: 10px; }
  .legend { display: flex; flex-wrap: wrap; gap: 10px; margin: 8px 0 0; font-size: 11px; color: #93a4b7; }
  .legend .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
</style>
</head>
<body>
  <h1>NekoSuneAI &mdash; Windows Gaming Node</h1>
  <p class="muted" id="updated">Loading&hellip;</p>

  <div class="card">
    <h2>Game view</h2>
    <img class="frame" id="frame" alt="Live game capture unavailable">
  </div>

  <div class="card">
    <h2>Status</h2>
    <div class="row"><span>Game</span><span id="game"></span></div>
    <div class="row"><span>Window</span><span id="window"></span></div>
    <div class="row"><span>Input</span><span id="input"></span></div>
    <div class="row"><span>Scene</span><span id="scene"></span></div>
  </div>

  <div class="card">
    <h2>On-screen text (OCR)</h2>
    <div class="ocr" id="ocr">&mdash;</div>
  </div>

  <div class="card" id="vrchat-card" hidden>
    <h2>VRChat</h2>
    <div class="row"><span>OSC</span><span id="vrchat-osc"></span></div>
    <div class="row"><span>World</span><span id="vrchat-world"></span></div>
    <div class="row"><span>Players seen</span><span id="vrchat-players"></span></div>
  </div>

  <div class="card" id="mapper-card" hidden>
    <h2>World mapper</h2>
    <div class="row"><span>State</span><span id="mapper-state"></span></div>
    <div class="row"><span>Floor</span><span id="mapper-floor"></span></div>
    <div class="row"><span>Steps / walls / branches</span><span id="mapper-counts"></span></div>
    <canvas id="mapper-canvas" class="blueprint" width="480" height="360"></canvas>
    <div class="legend" id="mapper-legend"></div>
    <div class="log" id="mapper-log">&mdash;</div>
  </div>

  <div class="card" id="friends-card" hidden>
    <h2>VRChat friends bot</h2>
    <div class="row"><span>State</span><span id="friends-state"></span></div>
    <div class="log" id="friends-log">&mdash;</div>
  </div>

<script>
function setText(id, text) { document.getElementById(id).textContent = text; }
function pill(ok, textOk, textBad) {
  return '<span class="pill ' + (ok ? 'ok' : 'bad') + '">' + (ok ? textOk : textBad) + '</span>';
}

// Kind -> color, kept in sync with FEATURE_PATTERNS in world_mapper.py and
// the same palette tools/world_map_gui.py uses for the desktop canvas, so a
// VIP room (or door/lift/teleporter) reads the same way on a phone as it
// does on the PC.
const LANDMARK_COLORS = {
  vip: '#ff3d81', elevator: '#4da6ff', teleporter: '#a855f7',
  door: '#f4c542', entrance: '#2ed69b', exit: '#ff8c42',
};
let legendDrawn = false;
function drawLegend() {
  if (legendDrawn) return;
  legendDrawn = true;
  const items = [['VIP', LANDMARK_COLORS.vip], ['Elevator', LANDMARK_COLORS.elevator],
    ['Teleporter', LANDMARK_COLORS.teleporter], ['Door', LANDMARK_COLORS.door],
    ['Entrance', LANDMARK_COLORS.entrance], ['Exit', LANDMARK_COLORS.exit], ['Manual tag', '#f4c542']];
  document.getElementById('mapper-legend').innerHTML = items.map(([label, color]) =>
    '<span><span class="dot" style="background:' + color + '"></span>' + label + '</span>').join('');
}
function drawBlueprint(m) {
  drawLegend();
  const canvas = document.getElementById('mapper-canvas');
  const ctx = canvas.getContext('2d');
  const width = canvas.width, height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  const walls = m.walls || [], path = m.path || [], landmarks = m.landmarks || [], position = m.position;
  let points = [];
  walls.forEach(w => { points.push([w.x1, w.y1]); points.push([w.x2, w.y2]); });
  path.forEach(p => points.push([p[0], p[1]]));
  landmarks.forEach(l => points.push([l.x, l.y]));
  if (position && m.running) points.push([position.x, position.y]);
  if (!points.length) {
    ctx.fillStyle = '#93a4b7';
    ctx.font = '13px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No map data yet for the current world.', width / 2, height / 2);
    return;
  }
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1.0), spanY = Math.max(maxY - minY, 1.0);
  const margin = 24;
  const scale = Math.min((width - 2 * margin) / spanX, (height - 2 * margin) / spanY);
  const toCanvas = (x, y) => [margin + (x - minX) * scale, height - (margin + (y - minY) * scale)];
  if (path.length >= 2) {
    ctx.strokeStyle = '#7c5cff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    path.forEach((p, i) => {
      const [cx, cy] = toCanvas(p[0], p[1]);
      if (i === 0) ctx.moveTo(cx, cy); else ctx.lineTo(cx, cy);
    });
    ctx.stroke();
  }
  ctx.strokeStyle = '#ff5d6c';
  ctx.lineWidth = 3;
  walls.forEach(w => {
    const [x1, y1] = toCanvas(w.x1, w.y1), [x2, y2] = toCanvas(w.x2, w.y2);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  });
  landmarks.forEach(l => {
    const [lx, ly] = toCanvas(l.x, l.y);
    const isVip = l.kind === 'vip';
    const color = LANDMARK_COLORS[l.kind] || (l.auto ? '#2ed69b' : '#f4c542');
    const radius = isVip ? 6 : 4;
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(lx, ly, radius, 0, Math.PI * 2); ctx.fill();
    if (isVip) { ctx.strokeStyle = '#0f151c'; ctx.lineWidth = 1; ctx.stroke(); }
    ctx.fillStyle = '#f4f7fb';
    ctx.font = (isVip ? 'bold ' : '') + '11px -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(String(l.label || '').slice(0, 30), lx + radius + 4, ly + 4);
  });
  if (position && m.running) {
    const [px, py] = toCanvas(position.x, position.y);
    ctx.strokeStyle = '#67e8f9';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI * 2); ctx.stroke();
  }
}
async function refresh() {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    const s = await res.json();
    setText('updated', 'Updated ' + new Date(s.epoch * 1000).toLocaleTimeString());
    setText('game', s.display_name || s.game_id || 'unknown');
    setText('window', s.window_title || 'not foreground');
    document.getElementById('input').innerHTML = pill(!s.input_disabled, 'enabled', 'disabled');
    setText('scene', s.transition ? ('transition: ' + s.transition) : (s.scene_changed ? 'just changed' : 'steady'));
    setText('ocr', s.ocr || '(nothing recognized)');

    if (s.vrchat) {
      document.getElementById('vrchat-card').hidden = false;
      document.getElementById('vrchat-osc').innerHTML = pill(s.vrchat.armed, 'armed', 'disarmed');
      const world = s.vrchat.world || {};
      setText('vrchat-world', world.name || world.id || 'unknown');
      setText('vrchat-players', (s.vrchat.players || []).join(', ') || 'none detected');
    }

    if (s.world_mapper) {
      const m = s.world_mapper;
      document.getElementById('mapper-card').hidden = false;
      document.getElementById('mapper-state').innerHTML = pill(m.running, 'mapping', 'idle');
      setText('mapper-floor', 'floor ' + m.floor_index + ' (' + m.floors_mapped + ' so far)');
      setText('mapper-counts', m.steps + ' / ' + m.walls_found + ' / ' + m.frontiers_queued);
      setText('mapper-log', (m.events || []).slice(-8).join('\\n') || 'No events yet.');
      drawBlueprint(m);
    }

    if (s.vrchat_friends) {
      document.getElementById('friends-card').hidden = false;
      document.getElementById('friends-state').innerHTML = pill(s.vrchat_friends.running, 'running', 'stopped');
      setText('friends-log', (s.vrchat_friends.events || []).slice(-8).join('\\n') || 'No events yet.');
    }
  } catch (err) {
    setText('updated', 'Disconnected — retrying…');
  }
}
function refreshFrame() {
  const img = document.getElementById('frame');
  img.classList.add('stale');
  const probe = new Image();
  probe.onload = () => { img.src = probe.src; img.classList.remove('stale'); };
  probe.onerror = () => {};
  probe.src = '/api/frame.jpg?t=' + Date.now();
}
refresh(); refreshFrame();
setInterval(refresh, 2000);
setInterval(refreshFrame, 2500);
</script>
</body>
</html>
"""


def _local_ip() -> str:
    """Best-effort LAN IP (no packets actually sent) so the on-device GUI can
    show a "visit this on your phone" address without guessing which NIC."""
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
    server: "WebStatusServer"  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet the default stderr access log
        pass

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler name
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_bytes(_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/status":
            try:
                payload = self.server.owner.status()
            except Exception as exc:
                payload = {"error": str(exc)[:300], "epoch": time.time()}
            self._send_bytes(json.dumps(payload).encode("utf-8"), "application/json")
        elif path == "/api/frame.jpg":
            frame = self.server.owner.frame_jpeg()
            if frame is None:
                self.send_response(404)
                self.end_headers()
                return
            self._send_bytes(frame, "image/jpeg")
        else:
            self.send_response(404)
            self.end_headers()


class WebStatusServer:
    def __init__(self, agent: Any, host: str = "0.0.0.0", port: int = 8799, frame_interval: float = 2.0) -> None:
        self.agent = agent
        self.host = host
        self.port = int(port)
        self.frame_interval = max(1.0, float(frame_interval))
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._frame_lock = threading.Lock()
        self._frame_jpeg: bytes | None = None
        self._frame_epoch = 0.0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.owner = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="windows-node-web-status")
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

    def frame_jpeg(self) -> bytes | None:
        with self._frame_lock:
            if self._frame_jpeg is None or time.time() - self._frame_epoch > self.frame_interval:
                try:
                    capture = self.agent.vision.capture(detailed=True, image_limit=250_000)
                    encoded = capture.get("screenshot_jpeg_base64")
                    if encoded:
                        self._frame_jpeg = base64.b64decode(encoded)
                        self._frame_epoch = time.time()
                except Exception:
                    pass
            return self._frame_jpeg

    def status(self) -> dict[str, Any]:
        agent = self.agent
        try:
            observation = agent.vision.capture() or {}
        except Exception:
            observation = {}
        data: dict[str, Any] = {
            "epoch": time.time(),
            "game_id": agent.profile.game_id,
            "display_name": agent.profile.display_name,
            "input_disabled": agent.input.disabled.is_set(),
            "window_title": observation.get("window_title", ""),
            "ocr": observation.get("ocr", ""),
            "transition": observation.get("transition", ""),
            "scene_changed": bool(observation.get("scene_changed", False)),
        }
        if agent.vrchat is not None:
            try:
                data["vrchat"] = agent.vrchat.status()
            except Exception:
                pass
        try:
            mapper_state = agent.world_mapper.status()
            if not mapper_state.get("running"):
                # Nothing's actively being mapped right now -- fall back to the
                # last saved map for the current world so the blueprint still
                # has something to draw, same as the desktop GUI's canvas does.
                saved = agent.world_mapper.load_saved()
                if saved and saved.get("floors"):
                    floor = next((f for f in saved["floors"] if f.get("floor_index") == 0), saved["floors"][0])
                    mapper_state["walls"] = floor.get("walls") or []
                    mapper_state["path"] = floor.get("path") or []
                    mapper_state["landmarks"] = floor.get("landmarks") or []
            data["world_mapper"] = mapper_state
        except Exception:
            pass
        friends = getattr(agent, "vrchat_friends", None)
        if friends is not None:
            data["vrchat_friends"] = {
                "running": friends.is_running(),
                "events": list(getattr(agent, "vrchat_friends_log", [])),
            }
        return data
