from __future__ import annotations

import html
import http.server
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from duckduckgo_search import DDGS
import phonenumbers
from phonenumbers import carrier, geocoder, number_type, PhoneNumberType

SCAM_CALLS_FILE = Path(os.getenv("NEKOSUNEAI_SCAM_CALLS_FILE", "/app/data/scam_calls.json"))
_INSTALLED = False
_LOCK = threading.RLock()

RISK_TERMS = {
    "scam": 4,
    "scammer": 4,
    "fraud": 4,
    "fraudulent": 4,
    "spam": 3,
    "nuisance": 3,
    "robocall": 4,
    "cold call": 2,
    "phishing": 4,
    "spoof": 3,
    "reported": 1,
    "harassment": 2,
    "telemarketing": 2,
}


def _read_items() -> list[dict]:
    with _LOCK:
        try:
            value = json.loads(SCAM_CALLS_FILE.read_text("utf-8"))
            return value if isinstance(value, list) else []
        except Exception:
            return []


def _write_items(items: list[dict]) -> None:
    with _LOCK:
        SCAM_CALLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SCAM_CALLS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[-1000:], ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(SCAM_CALLS_FILE)


def _phone_type_label(value: int) -> str:
    labels = {
        PhoneNumberType.MOBILE: "mobile",
        PhoneNumberType.FIXED_LINE: "fixed-line",
        PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed-line-or-mobile",
        PhoneNumberType.TOLL_FREE: "toll-free",
        PhoneNumberType.PREMIUM_RATE: "premium-rate",
        PhoneNumberType.VOIP: "voip",
        PhoneNumberType.PERSONAL_NUMBER: "personal-number",
        PhoneNumberType.PAGER: "pager",
    }
    return labels.get(value, "unknown")


def _number_metadata(raw_number: str, default_region: str = "GB") -> dict:
    raw = (raw_number or "").strip()
    try:
        parsed = phonenumbers.parse(raw, None if raw.startswith("+") else default_region)
        valid = phonenumbers.is_valid_number(parsed)
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164) if valid else raw
        national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL) if valid else raw
        return {
            "number": e164,
            "display_number": national,
            "country_code": phonenumbers.region_code_for_number(parsed) or default_region,
            "location": geocoder.description_for_number(parsed, "en") or "",
            "carrier": carrier.name_for_number(parsed, "en") or "",
            "number_type": _phone_type_label(number_type(parsed)),
            "valid": valid,
        }
    except Exception:
        return {
            "number": raw,
            "display_number": raw,
            "country_code": default_region,
            "location": "",
            "carrier": "",
            "number_type": "unknown",
            "valid": False,
        }


def _search_reputation(meta: dict) -> tuple[int, list[dict]]:
    number = str(meta.get("number") or "").strip()
    display = str(meta.get("display_number") or number).strip()
    if not number:
        return 0, []
    queries = [
        f'"{number}" scam spam caller',
        f'"{display}" scam fraud nuisance call',
        f'"{number}" who called me',
    ]
    evidence: list[dict] = []
    seen: set[str] = set()
    score = 0
    try:
        with DDGS() as ddgs:
            for query in queries:
                for result in ddgs.text(query, max_results=8):
                    url = str(result.get("href") or result.get("url") or "").strip()
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    title = str(result.get("title") or "").strip()
                    body = str(result.get("body") or result.get("snippet") or "").strip()
                    haystack = f"{title} {body}".lower()
                    local_score = sum(weight for term, weight in RISK_TERMS.items() if term in haystack)
                    if local_score <= 0:
                        continue
                    score += local_score
                    evidence.append({
                        "title": title[:180],
                        "url": url[:700],
                        "snippet": body[:500],
                        "score": local_score,
                    })
                    if len(evidence) >= 12:
                        break
                if len(evidence) >= 12:
                    break
    except Exception:
        pass
    distinct_hosts = {urlparse(str(item.get("url") or "")).netloc.lower() for item in evidence}
    if len(distinct_hosts) >= 2:
        score += 2
    return score, evidence[:8]


def lookup_number(raw_number: str, default_region: str = "GB") -> dict:
    meta = _number_metadata(raw_number, default_region)
    score, evidence = _search_reputation(meta)
    flagged = score >= 5 and bool(evidence)
    risk = "high" if score >= 12 else "medium" if score >= 7 else "low" if flagged else "unverified"
    summary = "No strong public scam reports found."
    if flagged:
        summary = f"Public search results contain multiple spam/scam indicators ({risk} confidence)."
    return {
        **meta,
        "flagged": flagged,
        "risk": risk,
        "score": score,
        "summary": summary,
        "evidence": evidence,
        "checked_at": int(time.time()),
    }


def _remember_flagged(item: dict, device_id: str = "", device_name: str = "") -> None:
    if not item.get("flagged"):
        return
    row = dict(item)
    row["device_id"] = device_id[:180]
    row["device_name"] = device_name[:180]
    items = _read_items()
    items.append(row)
    _write_items(items)


def _json(handler, code: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _export_html(items: list[dict]) -> bytes:
    rows = []
    for item in reversed(items):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('number','')))}</td>"
            f"<td>{html.escape(str(item.get('risk','')))}</td>"
            f"<td>{html.escape(str(item.get('carrier','')))}</td>"
            f"<td>{html.escape(str(item.get('location','')))}</td>"
            f"<td>{html.escape(str(item.get('number_type','')))}</td>"
            f"<td>{html.escape(str(item.get('summary','')))}</td>"
            "</tr>"
        )
    return ("<!doctype html><meta charset='utf-8'><title>NekoSuneAI flagged callers</title>"
            "<style>body{font:14px system-ui;background:#080914;color:#f4f2ff;padding:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #343961;padding:8px;text-align:left}th{background:#181b38}</style>"
            "<h1>Flagged incoming callers</h1><p>Community/public-web reputation signals are not proof of fraud. Verify independently before blocking.</p>"
            "<table><thead><tr><th>Number</th><th>Risk</th><th>Carrier</th><th>Location</th><th>Type</th><th>Reason</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>").encode("utf-8")


SCAM_UI = r'''
<style id="neko-scam-calls-css">
#page-scamcalls .scam-row{border:1px solid rgba(120,126,190,.2);background:rgba(13,15,36,.78);border-radius:13px;padding:12px}
#page-scamcalls .risk-high{color:#fda4af}.risk-medium{color:#fcd34d}.risk-low{color:#a7f3d0}
</style>
<script id="neko-scam-calls-js">
(function(){
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const token=()=>new URLSearchParams(location.search).get('token')||'';
 function mount(){
   if(document.getElementById('page-scamcalls'))return;
   const settings=document.querySelector('[data-page="settings"]'); if(!settings)return;
   const nav=document.createElement('button'); nav.className=settings.className; nav.dataset.page='scamcalls';
   nav.innerHTML='<span class="w-5 text-center opacity-70">☎</span> Scam Calls'; nav.onclick=()=>openScamCalls();
   settings.parentElement.insertBefore(nav,settings);
   const host=document.getElementById('page-settings')?.parentElement;if(!host)return;
   const page=document.createElement('div'); page.id='page-scamcalls'; page.className='page flex-col h-full overflow-y-auto p-5 lg:p-6 gap-4';
   page.innerHTML=`<section class="card p-5"><div class="section-kicker">PHONE PROTECTION</div><div class="flex flex-wrap items-end justify-between gap-3"><div><div class="text-xl font-bold mt-1">Flagged incoming calls</div><div class="text-[11px] text-nova-muted2 mt-1">Only numbers with public spam/scam indicators are stored here. Carrier/location data is best-effort and may be stale after number portability.</div></div><div class="flex gap-2"><button class="btn-secondary px-3 py-2 rounded-lg text-[10px]" onclick="scamExport('json')">Export JSON</button><button class="btn-secondary px-3 py-2 rounded-lg text-[10px]" onclick="scamExport('html')">Export HTML</button></div></div></section><section class="card p-4"><div id="scam-call-list" class="space-y-2"><div class="text-[11px] text-nova-muted">Loading…</div></div></section>`;
   host.appendChild(page);
 }
 window.openScamCalls=function(){showPage('scamcalls');const t=document.getElementById('page-title'),s=document.getElementById('page-sub');if(t)t.textContent='Scam Calls';if(s)s.textContent='Incoming numbers flagged by public reputation checks';scamRefresh();};
 window.scamRefresh=async function(){const out=document.getElementById('scam-call-list');if(!out)return;try{const r=await fetch('/api/scam-calls',{headers:{'X-Neko-Token':token()}}),j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');const items=j.items||[];out.innerHTML=items.length?items.slice().reverse().map(x=>`<div class="scam-row"><div class="flex justify-between gap-3"><div><div class="font-semibold">${esc(x.display_number||x.number)}</div><div class="text-[10px] text-nova-muted">${esc(x.carrier||'Unknown carrier')}${x.location?' · '+esc(x.location):''}${x.number_type?' · '+esc(x.number_type):''}</div></div><div class="text-[11px] font-bold risk-${esc(x.risk)}">${esc(String(x.risk||'').toUpperCase())}</div></div><div class="text-[11px] mt-2">${esc(x.summary)}</div><div class="text-[9px] text-nova-muted mt-2">Evidence: ${(x.evidence||[]).map(e=>esc(e.title||e.url)).slice(0,3).join(' · ')||'Public search signals'}</div></div>`).join(''):'<div class="text-[11px] text-nova-muted">No incoming callers have been flagged yet.</div>';}catch(e){out.innerHTML='<div class="text-[11px] text-red-300">'+esc(e.message)+'</div>'}};
 window.scamExport=function(fmt){location.href='/api/scam-calls/export?format='+encodeURIComponent(fmt)+'&token='+encodeURIComponent(token())};
 addEventListener('DOMContentLoaded',()=>{mount();setTimeout(mount,100)});setTimeout(mount,30);setInterval(()=>{if(document.getElementById('page-scamcalls')?.classList.contains('active'))scamRefresh()},5000);
})();
</script>
'''


def install_scam_call_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_server = http.server.ThreadingHTTPServer

    class ScamCallThreadingHTTPServer(original_server):
        def __init__(self, server_address, RequestHandlerClass, *args, **kwargs):
            base_handler = RequestHandlerClass

            class ScamCallHandler(base_handler):
                def do_POST(self):
                    path = urlparse(self.path).path
                    if path != "/api/android/scam-call":
                        return super().do_POST()
                    if not hasattr(self, "_device_authorized") or not self._device_authorized():
                        return _json(self, 401, {"error": "paired device authorization required"})
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        payload = json.loads(self.rfile.read(length) or b"{}")
                        number = str(payload.get("number") or "").strip()
                        if not number:
                            return _json(self, 400, {"error": "number is required"})
                        result = lookup_number(number, str(payload.get("region") or "GB"))
                        _remember_flagged(result, str(payload.get("device_id") or ""), str(payload.get("device_name") or ""))
                        return _json(self, 200, result)
                    except Exception as exc:
                        return _json(self, 400, {"error": str(exc)})

                def do_GET(self):
                    parsed = urlparse(self.path)
                    if parsed.path not in {"/api/scam-calls", "/api/scam-calls/export"}:
                        return super().do_GET()
                    query = parse_qs(parsed.query)
                    dashboard_ok = hasattr(self, "_dashboard_authorized") and self._dashboard_authorized()
                    if not dashboard_ok:
                        supplied = query.get("token", [""])[0]
                        previous = self.headers.get("X-Neko-Token")
                        try:
                            if supplied:
                                if previous is not None:
                                    self.headers.replace_header("X-Neko-Token", supplied)
                                else:
                                    self.headers["X-Neko-Token"] = supplied
                                dashboard_ok = bool(self._dashboard_authorized())
                        finally:
                            if supplied and previous is None:
                                try: del self.headers["X-Neko-Token"]
                                except Exception: pass
                            elif supplied and previous is not None:
                                self.headers.replace_header("X-Neko-Token", previous)
                    if not dashboard_ok:
                        return _json(self, 401, {"error": "dashboard authorization required"})
                    items = _read_items()
                    if parsed.path == "/api/scam-calls":
                        return _json(self, 200, {"items": items})
                    fmt = query.get("format", ["json"])[0].lower()
                    if fmt == "html":
                        body = _export_html(items)
                        content_type, filename = "text/html; charset=utf-8", "nekosuneai-flagged-callers.html"
                    else:
                        body = json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8")
                        content_type, filename = "application/json; charset=utf-8", "nekosuneai-flagged-callers.json"
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            super().__init__(server_address, ScamCallHandler, *args, **kwargs)

    http.server.ThreadingHTTPServer = ScamCallThreadingHTTPServer

    # webserver has not been imported by app.py yet. Import it only after the
    # ThreadingHTTPServer wrapper above is installed so its local server binding
    # includes this route wrapper.
    from . import webserver
    original_decorate = webserver._decorate_dashboard
    if not getattr(original_decorate, "_neko_scam_calls", False):
        def decorated(body: bytes) -> bytes:
            rendered = original_decorate(body)
            text = rendered.decode("utf-8")
            if "neko-scam-calls-js" not in text:
                text = text.replace("</body>", SCAM_UI + "</body>", 1)
            return text.encode("utf-8")
        decorated._neko_scam_calls = True
        webserver._decorate_dashboard = decorated
