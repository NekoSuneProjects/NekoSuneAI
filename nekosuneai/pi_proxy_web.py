"""Local dashboard for a Pi Proxy node: status plus owner controls.

Modeled on Windows/nekosuneai/web_status_server.py: stdlib
http.server.ThreadingHTTPServer, one inline HTML+CSS+JS page, a /api/status
JSON endpoint, no external dependencies.

This page used to be strictly read-only, on the reasoning that an
unauthenticated LAN page should not be a second, less-guarded way to drive
audio and Bluetooth. That reasoning still holds, so the control surface added
here is bounded rather than open:

* every control action maps to a capability the node already implements and
  the backend already policy-gates -- this adds no new powers, only a local
  way to reach them;
* `web_control_enabled: false` in the node config returns the page to its
  previous read-only behaviour entirely;
* `web_control_pin` (unset by default) requires a shared PIN on every control
  request, for a network the owner does not fully trust.

Still LAN-only and not a public interface: never forward the port to the
internet, with or without a PIN.
"""
from __future__ import annotations

import json
import secrets
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>NekoSuneAI Pi Proxy</title>
<style>
  /* Same "nova" violet/cyan palette as the Docker dashboard's dark theme,
     reproduced in plain CSS -- no Tailwind CDN, this page stays
     dependency-free so it costs a Pi nothing to serve. */
  :root {
    color-scheme: dark;
    --bg: #080914; --surface: #111329; --surface2: #181b38; --border: #292d55;
    --text: #f4f2ff; --muted: #8489b8; --muted2: #b3b7dc;
    --accent: #a78bfa; --accent-h: #c4b5fd; --cyan: #67e8f9;
    --ok-bg: rgba(34,197,94,.12); --ok-fg: #4ade80; --ok-border: rgba(34,197,94,.35);
    --bad-bg: rgba(248,113,113,.12); --bad-fg: #f87171; --bad-border: rgba(248,113,113,.35);
    --warn-bg: rgba(251,191,36,.12); --warn-fg: #fbbf24; --warn-border: rgba(251,191,36,.35);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 18px 16px 48px;
    background-image:
      radial-gradient(circle at 85% 5%, rgba(124,58,237,.18), transparent 32%),
      radial-gradient(circle at 18% 92%, rgba(34,211,238,.09), transparent 30%);
    background-attachment: fixed;
  }
  .wrap { max-width: 1120px; margin: 0 auto; }
  h1 { font-size: 19px; font-weight: 800; letter-spacing: -.01em; margin: 0; }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 10px var(--cyan); flex-shrink: 0; }
  .kicker { color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }
  .sub { color: var(--muted); font-size: 12px; margin: 3px 0 16px; }

  /* Status strip: the four things that explain almost every failure. */
  .strip { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
  .chip { display: inline-flex; align-items: center; gap: 7px; padding: 7px 13px; border-radius: 999px;
          font-size: 12px; font-weight: 600; background: var(--surface); border: 1px solid var(--border); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex-shrink: 0; }
  .dot.on { background: var(--ok-fg); box-shadow: 0 0 8px var(--ok-fg); }
  .dot.off { background: var(--bad-fg); box-shadow: 0 0 8px var(--bad-fg); }
  .dot.idle { background: var(--muted); }

  .grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
  @media (min-width: 760px) { .grid { grid-template-columns: 1fr 1fr; } .span2 { grid-column: 1 / -1; } }
  .card {
    background: linear-gradient(145deg, rgba(25,28,58,.88), rgba(14,16,36,.94));
    border: 1px solid var(--border); border-radius: 16px; padding: 16px;
    box-shadow: 0 1px 0 rgba(255,255,255,.02) inset, 0 8px 24px -12px rgba(0,0,0,.6);
  }
  .card h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .1em; color: var(--muted);
             margin: 0 0 12px; font-weight: 700; display: flex; justify-content: space-between; gap: 8px; }
  .row { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 6px 0;
         font-size: 13px; border-bottom: 1px solid rgba(120,126,190,.08); }
  .row:last-child { border-bottom: none; }
  .row > span:first-child { color: var(--muted); flex-shrink: 0; }
  .row > span:last-child { text-align: right; overflow-wrap: anywhere; }
  .row.err > span:last-child { color: var(--bad-fg); font-size: 12px; }
  .log { white-space: pre-wrap; font-size: 12px; background: #0d0f24; border: 1px solid var(--border);
         border-radius: 10px; padding: 10px; max-height: 190px; overflow-y: auto; color: var(--muted2);
         margin-top: 8px; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; border: 1px solid transparent; }
  .ok { background: var(--ok-bg); color: var(--ok-fg); border-color: var(--ok-border); }
  .bad { background: var(--bad-bg); color: var(--bad-fg); border-color: var(--bad-border); }
  .warn { background: var(--warn-bg); color: var(--warn-fg); border-color: var(--warn-border); }

  button, input, select { font: inherit; }
  .btn { padding: 9px 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface2);
         color: var(--text); font-size: 13px; font-weight: 600; cursor: pointer; transition: .12s; }
  .btn:hover:not(:disabled) { background: #20244a; border-color: var(--accent); }
  .btn:disabled { opacity: .45; cursor: not-allowed; }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #17092e; }
  .btn.primary:hover:not(:disabled) { background: var(--accent-h); }
  .btn.danger { background: var(--bad-bg); border-color: var(--bad-border); color: var(--bad-fg); }
  .btn.wide { width: 100%; }
  .btns { display: flex; flex-wrap: wrap; gap: 8px; }
  input[type=text], input[type=password], select {
    background: #0d0f24; border: 1px solid var(--border); border-radius: 10px; color: var(--text);
    padding: 9px 12px; font-size: 13px; width: 100%; min-width: 0;
  }
  input:focus, select:focus { outline: none; border-color: var(--accent); }
  .field { display: flex; gap: 8px; margin-bottom: 10px; }
  label.lbl { display: block; font-size: 11px; color: var(--muted); margin-bottom: 5px; font-weight: 600; }

  /* Conversation transcript: the point of the whole node. */
  .talk { max-height: 260px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
  .turn { display: flex; flex-direction: column; gap: 3px; }
  .bubble { padding: 8px 12px; border-radius: 12px; font-size: 13px; max-width: 88%; overflow-wrap: anywhere; }
  .turn .you { align-self: flex-end; background: var(--accent); color: #17092e; border-bottom-right-radius: 4px; }
  .turn .neko { align-self: flex-start; background: var(--surface2); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
  .turn time { font-size: 10px; color: var(--muted); padding: 0 4px; }
  .turn.u { align-items: flex-end; } .turn.a { align-items: flex-start; }
  .empty { color: var(--muted); font-size: 12px; text-align: center; padding: 18px 0; }

  /* Now playing */
  .now { background: #0d0f24; border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; }
  .now-title { font-size: 13px; font-weight: 700; overflow-wrap: anywhere; }
  .now-meta { font-size: 11px; color: var(--muted); margin-top: 2px; }
  input[type=range] { width: 100%; accent-color: var(--accent); background: transparent; margin: 2px 0 0; }

  #toast { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%) translateY(120%);
           background: var(--surface2); border: 1px solid var(--accent); color: var(--text);
           padding: 11px 18px; border-radius: 12px; font-size: 13px; font-weight: 600;
           box-shadow: 0 12px 32px -8px rgba(0,0,0,.8); transition: transform .22s; z-index: 50; max-width: 90vw; }
  #toast.show { transform: translateX(-50%) translateY(0); }
  #toast.bad { border-color: var(--bad-border); color: var(--bad-fg); }
  .ro { background: var(--warn-bg); border: 1px solid var(--warn-border); color: var(--warn-fg);
        padding: 10px 14px; border-radius: 12px; font-size: 12px; margin-bottom: 14px; }
  .ro.bad-note { background: var(--bad-bg); border-color: var(--bad-border); color: var(--bad-fg); font-weight: 600; }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<div class="wrap">
  <div class="brand"><span class="brand-dot"></span><h1>NekoSune<span style="color:var(--accent)">AI</span> &mdash; Pi Proxy</h1></div>
  <p class="sub"><span class="kicker" id="updated">Loading&hellip;</span> <span id="node-name"></span></p>

  <div class="strip">
    <span class="chip"><span class="dot idle" id="d-paired"></span><span id="t-paired">pairing</span></span>
    <span class="chip"><span class="dot idle" id="d-backend"></span><span id="t-backend">backend</span></span>
    <span class="chip"><span class="dot idle" id="d-ws"></span><span id="t-ws">live link</span></span>
    <span class="chip"><span class="dot idle" id="d-bt"></span><span id="t-bt">bluetooth</span></span>
    <span class="chip"><span class="dot idle" id="d-wake"></span><span id="t-wake">wake word</span></span>
  </div>

  <div class="ro bad-note" id="auth-note" hidden></div>

  <div class="card" id="pair-card" hidden style="margin-bottom:12px">
    <h2><span>Pair this node</span><span class="pill warn">not paired</span></h2>
    <p style="font-size:12px;color:var(--muted);margin:0 0 12px">
      On the NekoSuneAI dashboard open <b>Nodes &amp; Routines</b> and create a pairing
      code, then enter it here. No terminal needed.
    </p>
    <label class="lbl" for="pair-server">Server address</label>
    <input type="text" id="pair-server" placeholder="https://your-server.example.com" autocomplete="off">
    <div style="height:8px"></div>
    <div class="field">
      <input type="text" id="pair-id" placeholder="Pairing ID" autocomplete="off">
      <input type="text" id="pair-code" placeholder="Pairing code" autocomplete="off">
    </div>
    <button class="btn primary wide" id="btn-pair">Pair</button>
  </div>
  <div class="ro bad-note" id="audio-note" hidden></div>

  <div class="ro" id="readonly-note" hidden>
    View-only mode &mdash; controls are disabled by <code>web_control_enabled: false</code> in this node's config.
  </div>

  <div class="grid">

    <div class="card span2">
      <h2><span>Talk to Neko</span><span id="talk-state"></span></h2>
      <div class="talk" id="talk"><div class="empty">Nothing said yet. Type below, or press Listen and speak.</div></div>
      <div class="field">
        <input type="text" id="ask" placeholder="Ask Neko something, or say: play lofi hip hop" autocomplete="off">
        <button class="btn primary" id="btn-ask">Send</button>
      </div>
      <div class="btns">
        <button class="btn" id="btn-listen">&#127908; Listen</button>
        <button class="btn" id="btn-stop-all">Stop audio</button>
        <button class="btn" id="btn-enable" hidden>Re-enable audio</button>
      </div>
    </div>

    <div class="card">
      <h2><span>Music</span><span id="music-pill"></span></h2>
      <div class="field">
        <input type="text" id="music-q" placeholder="Song, artist, or YouTube URL" autocomplete="off">
        <button class="btn primary" id="btn-play">Play</button>
      </div>
      <div class="now" id="now" hidden>
        <div class="now-title" id="now-title"></div>
        <div class="now-meta" id="now-meta"></div>
      </div>
      <div class="btns">
        <button class="btn" id="btn-music-pause" title="Pause">&#9208;</button>
        <button class="btn" id="btn-music-prev" title="Previous">&#9198;</button>
        <button class="btn" id="btn-music-skip" title="Next">&#9197;</button>
        <button class="btn" id="btn-music-stop">Stop</button>
      </div>
      <label class="lbl" for="vol" style="margin-top:12px">Volume <span id="vol-label">100%</span></label>
      <input type="range" id="vol" min="0" max="100" step="5" value="100">
      <div class="row" style="margin-top:8px"><span>Speaking (TTS)</span><span id="speaking"></span></div>
      <div class="row"><span>Resolved locally</span><span style="color:var(--muted);font-size:12px">yt-dlp on this Pi</span></div>
    </div>

    <div class="card">
      <h2><span>Microphone</span></h2>
      <label class="lbl" for="mic-sel">Capture device used for commands</label>
      <div class="field">
        <select id="mic-sel"><option value="">(ALSA default)</option></select>
        <button class="btn" id="btn-mic">Use</button>
      </div>
      <div class="row"><span>Wake-word input</span><span id="mic-pa">&mdash;</span></div>
      <div class="row err" id="mic-err-row" hidden><span>Error</span><span id="mic-err"></span></div>
    </div>

    <div class="card">
      <h2><span>Bluetooth speaker</span></h2>
      <div class="row"><span>Link</span><span id="bt-link"></span></div>
      <div class="row"><span>Device</span><span id="bt-name"></span></div>
      <div class="row"><span>Sink</span><span id="bt-sink"></span></div>
      <div class="row"><span>Audio server</span><span id="bt-server"></span></div>
      <div class="row err" id="bt-err-row" hidden><span>A2DP</span><span id="bt-err"></span></div>
      <div class="btns" style="margin-top:10px"><button class="btn" id="btn-bt">Reconnect now</button></div>
      <div class="log" id="bt-log">&mdash;</div>
    </div>

    <div class="card">
      <h2><span>Wake word</span></h2>
      <div class="row"><span>Listening</span><span id="ww-listening"></span></div>
      <div class="row"><span>Model</span><span id="ww-model"></span></div>
      <div class="row"><span>Last score</span><span id="ww-score">&mdash;</span></div>
      <div class="row"><span>Last heard</span><span id="ww-transcript"></span></div>
      <div class="row err" id="ww-err-row" hidden><span>Error</span><span id="ww-err"></span></div>
      <div class="row err" id="snd-err-row" hidden><span>Chime</span><span id="snd-err"></span></div>
    </div>

    <div class="card">
      <h2><span>Consoles &amp; camera</span></h2>
      <div class="row"><span>PlayStation</span><span id="console-ps"></span></div>
      <div class="row"><span>Xbox</span><span id="console-xbox"></span></div>
      <div class="row"><span>Kinect vision</span><span id="cam-running"></span></div>
      <div class="row"><span>Last frame</span><span id="cam-frame"></span></div>
      <div class="row err" id="cam-err-row" hidden><span>Error</span><span id="cam-err"></span></div>
    </div>

    <div class="card span2">
      <h2><span>Activity</span><span class="kicker" id="node-id"></span></h2>
      <div class="log" id="commands">&mdash;</div>
    </div>

  </div>
</div>
<div id="toast"></div>

<script>
'use strict';
var PIN_KEY = 'nekoPiPin';
var controlEnabled = false, busy = false, pin = '';
try { pin = sessionStorage.getItem(PIN_KEY) || ''; } catch (e) { pin = ''; }

function $(id) { return document.getElementById(id); }
function text(id, value) { var el = $(id); if (el) el.textContent = value; }
function html(id, value) { var el = $(id); if (el) el.innerHTML = value; }
function pill(ok, good, bad, cls) {
  return '<span class="pill ' + (ok ? (cls || 'ok') : 'bad') + '">' + (ok ? good : bad) + '</span>';
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function dot(id, state) { var el = $(id); if (el) el.className = 'dot ' + state; }
function errRow(rowId, textId, message) {
  var row = $(rowId); if (!row) return;
  if (message) { text(textId, message); row.hidden = false; } else { row.hidden = true; }
}
// A status field that keeps reporting the same error would otherwise re-toast
// on every 2s poll.
var toastSeen = '';
function toastOnce(key, message, isBad) {
  if (toastSeen === key) return;
  toastSeen = key;
  toast(message, isBad);
}
var toastTimer = null;
function toast(message, isBad) {
  var el = $('toast');
  el.textContent = message;
  el.className = 'show' + (isBad ? ' bad' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { el.className = ''; }, 4200);
}

async function control(action, body, quiet) {
  if (!controlEnabled) { toast('Controls are disabled on this node.', true); return null; }
  if (busy) return null;
  busy = true;
  setBusy(true);
  try {
    var headers = { 'Content-Type': 'application/json' };
    if (pin) headers['X-Neko-Pi-Pin'] = pin;
    var res = await fetch('/api/control', {
      method: 'POST', headers: headers,
      body: JSON.stringify(Object.assign({ action: action }, body || {})),
    });
    var data = await res.json().catch(function () { return {}; });
    if (res.status === 401) {
      // Ask once, keep it for the tab only. A PIN is opt-in; most LAN
      // installs never set one and never see this.
      var supplied = prompt('This node requires a control PIN:');
      if (supplied) {
        pin = supplied;
        try { sessionStorage.setItem(PIN_KEY, pin); } catch (e) {}
        busy = false; setBusy(false);
        return control(action, body, quiet);
      }
      toast('A control PIN is required.', true);
      return null;
    }
    if (!res.ok) { toast(data.error || ('HTTP ' + res.status), true); return null; }
    if (!quiet) toast(data.message || 'Done.');
    refresh();
    return data;
  } catch (err) {
    toast(String(err && err.message || err), true);
    return null;
  } finally {
    busy = false; setBusy(false);
  }
}

function setBusy(on) {
  ['btn-ask', 'btn-listen', 'btn-play', 'btn-music-stop', 'btn-bt', 'btn-mic', 'btn-stop-all', 'btn-enable']
    .forEach(function (id) { var el = $(id); if (el) el.disabled = on || !controlEnabled; });
}

function renderTalk(turns) {
  var box = $('talk');
  if (!turns || !turns.length) {
    box.innerHTML = '<div class="empty">Nothing said yet. Type below, or press Listen and speak.</div>';
    return;
  }
  var atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.innerHTML = turns.map(function (turn) {
    var when = turn.epoch ? new Date(turn.epoch * 1000).toLocaleTimeString() : '';
    var out = '<div class="turn u"><div class="bubble you">' + esc(turn.text) + '</div><time>' + esc(when) + '</time></div>';
    if (turn.reply) out += '<div class="turn a"><div class="bubble neko">' + esc(turn.reply) + '</div></div>';
    return out;
  }).join('');
  if (atBottom) box.scrollTop = box.scrollHeight;
}

var micRendered = '';
function renderMics(mics, selected) {
  var signature = JSON.stringify(mics) + '|' + selected;
  if (signature === micRendered) return;   // never clobber an open <select>
  micRendered = signature;
  var sel = $('mic-sel');
  var options = ['<option value="">(ALSA default)</option>'];
  (mics || []).forEach(function (mic) {
    options.push('<option value="' + esc(mic.alsa_device) + '">' +
      esc(mic.name) + ' — ' + esc(mic.alsa_device) + (mic.is_kinect ? ' ★' : '') + '</option>');
  });
  sel.innerHTML = options.join('');
  sel.value = (mics || []).some(function (m) { return m.alsa_device === selected; }) ? selected : '';
}

async function refresh() {
  try {
    var res = await fetch('/api/status', { cache: 'no-store' });
    var s = await res.json();

    controlEnabled = s.control_enabled !== false;
    $('readonly-note').hidden = controlEnabled;
    if (!busy) setBusy(false);

    text('updated', 'Updated ' + new Date(s.epoch * 1000).toLocaleTimeString());
    text('node-name', s.name ? '· ' + s.name : '');
    text('node-id', s.node_id || '');

    // A stored token is not the same as an accepted one: the node used to
    // show "paired" while the backend refused every request.
    var authBroken = !!s.auth_error;
    // Offer pairing right on the page when this node has no token yet, so a
    // second Pi is set up from its own dashboard rather than a terminal.
    $('pair-card').hidden = !(s.can_pair && (!s.paired || authBroken));
    if (!$('pair-card').hidden && !$('pair-server').value && s.server_url) {
      $('pair-server').value = s.server_url;
    }
    dot('d-paired', authBroken ? 'off' : (s.paired ? 'on' : 'off'));
    text('t-paired', authBroken ? 'pairing rejected' : (s.paired ? 'paired' : 'not paired'));
    $('auth-note').hidden = !authBroken;
    if (authBroken) text('auth-note', s.auth_error);
    dot('d-backend', s.backend_reachable !== false ? 'on' : 'off');
    text('t-backend', s.backend_reachable !== false ? 'backend online' : 'backend unreachable');

    // The live link is what keeps a long turn from being cut off by a proxy.
    // "http fallback" is a working state, not an error -- say so.
    var ws = s.websocket || {};
    dot('d-ws', ws.connected ? 'on' : (ws.enabled === false ? 'idle' : 'off'));
    text('t-ws', ws.connected ? 'live link' : (ws.enabled === false ? 'live link off' : 'http fallback'));

    var bt = s.bluetooth || {};
    // Everything audible goes through this server -- TTS replies, wake chimes
    // and music alike -- so a dead one is not just a Bluetooth problem.
    var audioDead = bt.audio_server_ok === false;
    $('audio-note').hidden = !audioDead;
    if (audioDead) text('audio-note', 'No audio output: ' + (bt.audio_server || 'the audio server is unreachable.'));
    dot('d-bt', bt.ready ? 'on' : (bt.connected ? 'idle' : 'off'));
    text('t-bt', bt.name || bt.address || 'no speaker');
    html('bt-link', pill(!!bt.connected, 'connected', 'disconnected'));
    text('bt-name', bt.name || bt.address || 'not detected');
    text('bt-sink', bt.sink || 'not ready');
    html('bt-server', bt.audio_server_ok == null
      ? '<span class="pill warn">not probed</span>'
      : pill(bt.audio_server_ok, 'reachable', 'unreachable'));
    // "sink is not ready" alone is unactionable; the watchdog now says whether
    // the card is on a headset profile, offers no A2DP at all, or is missing.
    errRow('bt-err-row', 'bt-err', bt.connected && !bt.sink ? bt.profile_error : '');
    text('bt-log', (s.bluetooth_events || []).slice(-8).join('\n') || 'No events yet.');

    var ww = s.wake_word || {};
    var listening = !!ww.enabled && !!ww.running;
    dot('d-wake', listening ? 'on' : (ww.enabled ? 'off' : 'idle'));
    text('t-wake', listening ? 'wake word armed' : (ww.enabled ? 'wake word failed' : 'wake word off'));
    html('ww-listening', pill(listening, 'listening', ww.enabled ? 'stopped' : 'disabled', ww.enabled ? 'bad' : 'warn'));
    text('ww-model', ww.model || 'not configured');
    text('ww-score', ww.last_score != null ? String(ww.last_score) : '—');
    var heard = ww.last_transcript || 'nothing yet';
    if (ww.last_transcript && ww.last_transcript_at) {
      heard += ' (' + new Date(ww.last_transcript_at * 1000).toLocaleTimeString() + ')';
    }
    text('ww-transcript', heard);
    // "enabled but not running" is the wake-word thread having died (bad mic
    // index, model download failed, device busy). Without surfacing ww.error
    // it just reads as a permanent, unexplained "stopped".
    errRow('ww-err-row', 'ww-err', ww.enabled && !ww.running ? ww.error : '');

    var sounds = s.alert_sounds || {};
    errRow('snd-err-row', 'snd-err', sounds.error || '');

    html('speaking', pill(!!s.audio_speaking, 'speaking', 'idle', 'ok'));

    var mus = s.music || {};
    var musState = mus.playing ? 'playing' : (mus.paused ? 'paused' : 'idle');
    html('music-pill', '<span class="pill ' + (mus.playing ? 'ok' : (mus.paused ? 'warn' : 'warn')) + '">' + musState + '</span>');
    $('now').hidden = !mus.title;
    if (mus.title) {
      text('now-title', mus.title);
      var meta = mus.paused ? 'Paused' : 'Playing';
      if (mus.queued) meta += ' · ' + mus.queued + ' queued';
      text('now-meta', meta);
    }
    $('btn-music-pause').innerHTML = mus.paused ? '&#9654;' : '&#9208;';
    $('btn-music-pause').title = mus.paused ? 'Resume' : 'Pause';
    // Don't fight the owner while they are dragging the slider.
    if (mus.volume != null && document.activeElement !== $('vol')) {
      $('vol').value = mus.volume;
      text('vol-label', mus.volume + '%');
    }
    if (mus.error) toastOnce('music-' + mus.error, mus.error, true);
    html('talk-state', s.input_disabled ? '<span class="pill bad">audio disabled</span>' : '');
    $('btn-enable').hidden = !s.input_disabled;

    var mic = s.microphone || {};
    renderMics(s.microphones, mic.alsa_device === '(ALSA default)' ? '' : mic.alsa_device);
    text('mic-pa', mic.portaudio_name || 'not resolved yet');
    errRow('mic-err-row', 'mic-err', mic.error || '');

    function consoleText(item) {
      if (!item) return 'unknown';
      var out = item.state || (item.online ? 'online' : 'offline');
      if (item.active_title) out += ' — ' + item.active_title;
      return out;
    }
    var consoles = s.console || {};
    text('console-ps', consoleText(consoles.playstation));
    text('console-xbox', consoleText(consoles.xbox));

    var cam = s.camera || {};
    html('cam-running', pill(!!cam.enabled && !!cam.running, 'watching', cam.enabled ? 'stopped' : 'disabled', cam.enabled ? 'bad' : 'warn'));
    text('cam-frame', cam.last_frame_age_seconds != null ? (cam.last_frame_age_seconds + 's ago') : 'no frame yet');
    errRow('cam-err-row', 'cam-err', cam.enabled && cam.error ? cam.error : '');

    renderTalk(s.conversation);
    text('commands', (s.recent_commands || []).slice(-12).join('\n') || 'No commands yet.');
  } catch (err) {
    text('updated', 'Disconnected — retrying…');
    dot('d-backend', 'off');
  }
}

function wire(id, handler) { var el = $(id); if (el) el.onclick = handler; }
wire('btn-ask', function () {
  var input = $('ask'), value = input.value.trim();
  if (!value) return;
  input.value = '';
  control('ask', { text: value }, true);
});
$('ask').addEventListener('keydown', function (e) { if (e.key === 'Enter') $('btn-ask').click(); });
wire('btn-listen', function () { toast('Listening…'); control('listen', {}, true); });
wire('btn-play', function () {
  var input = $('music-q'), value = input.value.trim();
  if (!value) return;
  input.value = '';
  control('music_play', { query: value });
});
$('music-q').addEventListener('keydown', function (e) { if (e.key === 'Enter') $('btn-play').click(); });
wire('btn-music-stop', function () { control('music_stop'); });
wire('btn-music-pause', function () { control('music_pause'); });
wire('btn-music-skip', function () { control('music_skip'); });
wire('btn-music-prev', function () { control('music_skip', { previous: true }); });
$('vol').addEventListener('change', function () {
  var level = Number($('vol').value);
  text('vol-label', level + '%');
  control('music_volume', { percent: level }, true);
});
$('vol').addEventListener('input', function () { text('vol-label', $('vol').value + '%'); });
wire('btn-bt', function () { toast('Reconnecting…'); control('bluetooth_reconnect'); });
wire('btn-mic', function () { control('set_microphone', { alsa_device: $('mic-sel').value }); });
wire('btn-stop-all', function () { control('stop_all'); });
wire('btn-enable', function () { control('enable'); });
wire('btn-pair', function () {
  control('pair', {
    server_url: $('pair-server').value.trim(),
    pairing_id: $('pair-id').value.trim(),
    pairing_code: $('pair-code').value.trim(),
  });
});
['pair-server', 'pair-id', 'pair-code'].forEach(function (id) {
  $(id).addEventListener('keydown', function (e) { if (e.key === 'Enter') $('btn-pair').click(); });
});

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


class _ThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without the startup DNS lookup.

    http.server's own server_bind() calls socket.getfqdn() purely to populate
    server_name, which nothing here reads. That is a blocking reverse-DNS
    lookup, and on a headless Pi with a slow or unreachable resolver it stalls
    startup for seconds before the dashboard answers anything.
    """

    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class _Handler(BaseHTTPRequestHandler):
    server: "_ThreadingHTTPServer"  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def _send_json(self, code: int, value: Any) -> None:
        body = json.dumps(value, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
                payload["microphones"] = self.server.owner.microphones()
            except Exception as exc:
                payload = {"error": str(exc)[:300], "epoch": time.time()}
            self._send_json(200, payload)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/api/control":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8000:
                raise ValueError("request too large")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("expected a JSON object")
        except (ValueError, OSError) as exc:
            return self._send_json(400, {"error": str(exc)[:200]})

        server = self.server
        if not server.control_enabled:
            return self._send_json(403, {"error": "controls are disabled on this node"})
        if server.control_pin and not secrets.compare_digest(
            self.headers.get("X-Neko-Pi-Pin", ""), server.control_pin
        ):
            return self._send_json(401, {"error": "a control PIN is required"})

        try:
            return self._send_json(200, server.dispatch(payload))
        except PermissionError as exc:
            return self._send_json(403, {"error": str(exc)[:300]})
        except ValueError as exc:
            return self._send_json(400, {"error": str(exc)[:300]})
        except Exception as exc:
            return self._send_json(500, {"error": str(exc)[:300]})


class PiProxyWebStatusServer:
    def __init__(
        self,
        agent: Any,
        host: str = "0.0.0.0",
        port: int = 8799,
        control_enabled: bool = True,
        control_pin: str = "",
    ) -> None:
        self.agent = agent
        self.host = host
        self.port = int(port)
        self.control_enabled = bool(control_enabled)
        self.control_pin = str(control_pin or "")
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Map a page action onto a capability the agent already implements.

        Every branch here reaches the same code a backend-issued command would;
        this page adds a local way to trigger them, not new abilities.
        """
        action = str(payload.get("action", "")).strip()
        agent = self.agent

        if action == "ask":
            text = str(payload.get("text", "")).strip()
            if not text:
                raise ValueError("ask requires text")
            result = agent.converse(text)
            return {"ok": True, "message": "Sent.", "reply": result.get("reply", "")}

        if action == "listen":
            # Capture runs on the request thread: it is bounded by
            # MAX_LISTEN_SECONDS, and ThreadingHTTPServer keeps the status
            # poll responsive meanwhile.
            result = agent.listen_and_converse()
            if not result.get("ok"):
                return {"ok": False, "message": "I didn't catch that."}
            return {"ok": True, "message": "Heard: " + str(result.get("text", ""))[:120]}

        if action == "music_play":
            query = str(payload.get("query", "")).strip()
            if not query:
                raise ValueError("music_play requires a query")
            agent._dispatch("music.play", {"query": query})
            return {"ok": True, "message": "Playing."}

        if action == "music_stop":
            agent._dispatch("music.stop", {})
            return {"ok": True, "message": "Music stopped."}

        if action == "music_pause":
            # One button for both, driven by what the node is actually doing,
            # so the page cannot get out of step with the player.
            paused = bool(agent.music.status().get("paused"))
            result = agent._dispatch("music.resume" if paused else "music.pause", {})
            if not result.get("ok"):
                return {"ok": False, "message": str(result.get("message", "nothing is playing"))}
            return {"ok": True, "message": "Resumed." if paused else "Paused."}

        if action == "music_skip":
            result = agent._dispatch("music.skip", {"previous": bool(payload.get("previous"))})
            return {"ok": True, "message": str(result.get("message") or result.get("title") or "Skipped.")}

        if action == "music_volume":
            result = agent._dispatch("music.volume", {"percent": int(payload.get("percent", 100))})
            if not result.get("ok"):
                return {"ok": False, "message": str(result.get("message", "could not set the volume"))}
            return {"ok": True, "message": f"Volume {result.get('volume')}%."}

        if action == "bluetooth_reconnect":
            ok, message = agent.bt.reconnect_now()
            return {"ok": bool(ok), "message": message}

        if action == "set_microphone":
            chosen = agent.set_capture_device(str(payload.get("alsa_device", "")))
            return {"ok": True, "message": "Microphone: " + (chosen or "ALSA default")}

        if action == "stop_all":
            agent.stop_all(disable=True)
            return {"ok": True, "message": "Audio stopped and disarmed."}

        if action == "pair":
            # Pairing is the one control that has to work while the node is
            # unpaired, so it is deliberately reachable in that state -- it is
            # also the only one that can do nothing without a valid code from
            # the owner's own backend.
            result = agent.pair_and_save(
                str(payload.get("server_url", "")),
                str(payload.get("pairing_id", "")),
                str(payload.get("pairing_code", "")),
            )
            return {"ok": True, "message": f"Paired with {result['server_url']}.", **result}

        if action == "enable":
            agent.enable()
            return {"ok": True, "message": "Audio re-enabled."}

        raise ValueError(f"unknown action: {action[:40] or '<empty>'}")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._httpd = _ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.owner = self.agent  # type: ignore[attr-defined]
        self._httpd.control_enabled = self.control_enabled  # type: ignore[attr-defined]
        self._httpd.control_pin = self.control_pin  # type: ignore[attr-defined]
        self._httpd.dispatch = self.dispatch  # type: ignore[attr-defined]
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
