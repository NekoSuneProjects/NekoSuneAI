from __future__ import annotations

import html
import http.server
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .scam_call_patch import lookup_number

CALL_EVENTS_FILE = Path(os.getenv("NEKOSUNEAI_CALL_EVENTS_FILE", "/app/data/call_events.json"))
IMPORTANT_NUMBERS_FILE = Path(os.getenv("NEKOSUNEAI_IMPORTANT_NUMBERS_FILE", "/app/data/important_numbers.json"))
_LOCK = threading.RLock()
_INSTALLED = False


def _read_json(path: Path, fallback):
    try:
        value = json.loads(path.read_text("utf-8"))
        return value
    except Exception:
        return fallback


def _write_events(items: list[dict]) -> None:
    with _LOCK:
        CALL_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CALL_EVENTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[-500:], ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(CALL_EVENTS_FILE)


def _read_events() -> list[dict]:
    value = _read_json(CALL_EVENTS_FILE, [])
    return value if isinstance(value, list) else []


def _important_match(result: dict) -> dict | None:
    rows = _read_json(IMPORTANT_NUMBERS_FILE, [])
    if isinstance(rows, dict):
        rows = rows.get("numbers", [])
    if not isinstance(rows, list):
        return None
    number = str(result.get("number") or "").strip()
    display = str(result.get("display_number") or "").strip()
    for row in rows:
        if not isinstance(row, dict):
            continue
        configured = str(row.get("number") or "").strip()
        if configured and configured in {number, display}:
            return row
    return None


def classify_and_remember(number: str, region: str, payload: dict) -> dict:
    result = lookup_number(number, region)
    trusted = _important_match(result)
    if result.get("flagged"):
        state = "scam"
    elif trusted:
        state = "important"
    else:
        state = "unknown"

    result["identity_status"] = state
    result["important"] = bool(trusted)
    result["verified"] = bool(trusted)
    result["organisation"] = str((trusted or {}).get("name") or "")[:180]
    result["verification_source"] = str((trusted or {}).get("source") or "")[:500]
    if trusted and (trusted or {}).get("provider"):
        result["reported_provider"] = str((trusted or {}).get("provider") or "")[:180]
    if state == "important":
        result["summary"] = f"Trusted caller record matched{': ' + result['organisation'] if result['organisation'] else ''}."
    elif state == "unknown":
        result["summary"] = "Unknown caller: not currently trusted/important and no strong scam reports were found."

    event = dict(result)
    event["received_at"] = int(time.time())
    event["device_id"] = str(payload.get("device_id") or "")[:180]
    event["device_name"] = str(payload.get("device_name") or "")[:180]
    event["source"] = str(payload.get("source") or "android-call-screening")[:120]
    event["app_version"] = str(payload.get("app_version") or "")[:40]
    items = _read_events()
    items.append(event)
    _write_events(items)
    return result


def _json(handler, code: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _export_html(items: list[dict]) -> bytes:
    rows = []
    for item in reversed(items):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('display_number') or item.get('number') or ''))}</td>"
            f"<td>{html.escape(str(item.get('identity_status') or 'unknown'))}</td>"
            f"<td>{html.escape(str(item.get('organisation') or ''))}</td>"
            f"<td>{html.escape(str(item.get('carrier') or ''))}</td>"
            f"<td>{html.escape(str(item.get('location') or ''))}</td>"
            f"<td>{html.escape(str(item.get('summary') or ''))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><meta charset='utf-8'><title>NekoSuneAI caller ID checks</title>"
        "<style>body{font:14px system-ui;background:#080914;color:#f4f2ff;padding:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #343961;padding:8px;text-align:left}th{background:#181b38}</style>"
        "<h1>Incoming caller ID checks</h1><table><thead><tr><th>Number</th><th>Status</th><th>Organisation</th><th>Provider</th><th>Location</th><th>Result</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    ).encode("utf-8")


CALL_SYNC_UI = r'''
<style id="neko-call-sync-css">
#page-callid .call-row{border:1px solid rgba(120,126,190,.2);background:rgba(13,15,36,.78);border-radius:13px;padding:12px}
#page-callid .state-scam{color:#fda4af}.state-important{color:#a7f3d0}.state-unknown{color:#fcd34d}
</style>
<script id="neko-call-sync-js">
(function(){
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const token=()=>new URLSearchParams(location.search).get('token')||'';
 function mount(){
   if(document.getElementById('page-callid'))return;
   const settings=document.querySelector('[data-page="settings"]'); if(!settings)return;
   const nav=document.createElement('button'); nav.className=settings.className;nav.dataset.page='callid';nav.innerHTML='<span class="w-5 text-center opacity-70">◉</span> Caller ID';nav.onclick=()=>openCallId();settings.parentElement.insertBefore(nav,settings);
   const host=document.getElementById('page-settings')?.parentElement;if(!host)return;
   const page=document.createElement('div');page.id='page-callid';page.className='page flex-col h-full overflow-y-auto p-5 lg:p-6 gap-4';
   page.innerHTML=`<section class="card p-5"><div class="section-kicker">ANDROID CALL SYNC</div><div class="flex flex-wrap justify-between gap-3"><div><div class="text-xl font-bold">Incoming caller ID</div><div class="text-[11px] text-nova-muted2 mt-1">Every Android call-screening lookup appears here, including trusted, unknown and scam results. Scam-only export remains available on the Scam Calls page.</div></div><div class="flex gap-2"><button class="btn-secondary px-3 py-2 rounded-lg text-[10px]" onclick="callIdExport('json')">Export JSON</button><button class="btn-secondary px-3 py-2 rounded-lg text-[10px]" onclick="callIdExport('html')">Export HTML</button></div></div></section><section class="card p-4"><div id="call-id-list" class="space-y-2">Loading…</div></section>`;host.appendChild(page);
 }
 window.openCallId=function(){showPage('callid');const t=document.getElementById('page-title'),s=document.getElementById('page-sub');if(t)t.textContent='Caller ID';if(s)s.textContent='Android incoming-call delivery and reputation status';callIdRefresh();};
 window.callIdRefresh=async function(){const out=document.getElementById('call-id-list');if(!out)return;try{const r=await fetch('/api/call-events',{headers:{'X-Neko-Token':token()}}),j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');const items=j.items||[];out.innerHTML=items.length?items.slice().reverse().map(x=>`<div class="call-row"><div class="flex justify-between gap-3"><div><div class="font-semibold">${esc(x.organisation||x.display_number||x.number)}</div><div class="text-[10px] text-nova-muted">${esc(x.display_number||x.number)} · ${esc(x.carrier||'Unknown provider')}${x.location?' · '+esc(x.location):''}</div></div><div class="text-[11px] font-bold state-${esc(x.identity_status||'unknown')}">${esc(String(x.identity_status||'unknown').toUpperCase())}</div></div><div class="text-[11px] mt-2">${esc(x.summary||'')}</div><div class="text-[9px] text-nova-muted mt-2">${esc(x.device_name||'Android')} · app ${esc(x.app_version||'?')}</div></div>`).join(''):'<div class="text-[11px] text-nova-muted">No incoming Android call checks received yet.</div>';}catch(e){out.innerHTML='<div class="text-[11px] text-red-300">'+esc(e.message)+'</div>'}};
 window.callIdExport=function(fmt){location.href='/api/call-events/export?format='+encodeURIComponent(fmt)+'&token='+encodeURIComponent(token())};
 addEventListener('DOMContentLoaded',()=>{mount();setTimeout(mount,100)});setTimeout(mount,30);setInterval(()=>{if(document.getElementById('page-callid')?.classList.contains('active'))callIdRefresh()},4000);
})();
</script>
'''


def install_call_sync_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_server = http.server.ThreadingHTTPServer

    class CallSyncThreadingHTTPServer(original_server):
        def __init__(self, server_address, RequestHandlerClass, *args, **kwargs):
            base_handler = RequestHandlerClass

            class CallSyncHandler(base_handler):
                def do_POST(self):
                    if urlparse(self.path).path != "/api/android/scam-call":
                        return super().do_POST()
                    if not hasattr(self, "_device_authorized") or not self._device_authorized():
                        return _json(self, 401, {"error": "paired device authorization required"})
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        payload = json.loads(self.rfile.read(length) or b"{}")
                        number = str(payload.get("number") or "").strip()
                        if not number:
                            return _json(self, 400, {"error": "number is required"})
                        result = classify_and_remember(number, str(payload.get("region") or "GB"), payload)
                        return _json(self, 200, result)
                    except Exception as exc:
                        return _json(self, 400, {"error": str(exc)})

                def do_GET(self):
                    parsed = urlparse(self.path)
                    if parsed.path not in {"/api/call-events", "/api/call-events/export"}:
                        return super().do_GET()
                    query = parse_qs(parsed.query)
                    dashboard_ok = hasattr(self, "_dashboard_authorized") and self._dashboard_authorized()
                    if not dashboard_ok and hasattr(self, "_dashboard_authorized"):
                        supplied = query.get("token", [""])[0]
                        if supplied:
                            previous = self.headers.get("X-Neko-Token")
                            try:
                                if previous is None: self.headers["X-Neko-Token"] = supplied
                                else: self.headers.replace_header("X-Neko-Token", supplied)
                                dashboard_ok = bool(self._dashboard_authorized())
                            finally:
                                if previous is None:
                                    try: del self.headers["X-Neko-Token"]
                                    except Exception: pass
                                else: self.headers.replace_header("X-Neko-Token", previous)
                    if not dashboard_ok:
                        return _json(self, 401, {"error": "dashboard authorization required"})
                    items = _read_events()
                    if parsed.path == "/api/call-events":
                        return _json(self, 200, {"items": items})
                    fmt = query.get("format", ["json"])[0].lower()
                    if fmt == "html":
                        body = _export_html(items); content_type = "text/html; charset=utf-8"; filename = "nekosuneai-caller-id.html"
                    else:
                        body = json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8"); content_type = "application/json; charset=utf-8"; filename = "nekosuneai-caller-id.json"
                    self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Content-Disposition", f'attachment; filename="{filename}"'); self.send_header("Content-Length", str(len(body))); self.end_headers()
                    try: self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError): pass

            super().__init__(server_address, CallSyncHandler, *args, **kwargs)

    http.server.ThreadingHTTPServer = CallSyncThreadingHTTPServer

    from . import webserver
    original_decorate = webserver._decorate_dashboard
    if not getattr(original_decorate, "_neko_call_sync", False):
        def decorate(html_text: str) -> str:
            rendered = original_decorate(html_text)
            marker = "</body>"
            return rendered.replace(marker, CALL_SYNC_UI + marker) if marker in rendered else rendered + CALL_SYNC_UI
        decorate._neko_call_sync = True
        webserver._decorate_dashboard = decorate
