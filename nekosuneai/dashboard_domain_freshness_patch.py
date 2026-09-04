from __future__ import annotations

import hashlib
import http.server
import json
import time
from urllib.parse import urlparse

_INSTALLED = False
_BUILD_ID = hashlib.sha256(str(time.time_ns()).encode("ascii")).hexdigest()[:12]

_FRESHNESS_UI = f'''<script id="neko-dashboard-freshness" data-build="{_BUILD_ID}">(function(){{
if(window.pywebview)return;
const build=document.currentScript?.dataset?.build||'{_BUILD_ID}';
let checking=false;
async function checkBuild(){{
  if(checking||document.hidden)return;
  checking=true;
  try{{
    const r=await fetch('/api/dashboard-build-id?ts='+Date.now(),{{cache:'no-store',credentials:'same-origin'}});
    if(!r.ok)return;
    const j=await r.json();
    if(j.build_id&&j.build_id!==build){{
      const u=new URL(location.href);
      u.searchParams.set('_refresh',j.build_id);
      location.replace(u.toString());
    }}
  }}catch(_){{}}finally{{checking=false}}
}}
addEventListener('pageshow',checkBuild);
addEventListener('focus',checkBuild);
setInterval(checkBuild,30000);
}})();</script>'''


def _clean_startup_print(*args, **kwargs):
    import builtins

    if args and isinstance(args[0], str):
        text = args[0]
        prefixes = (
            "NekoSuneAI web dashboard:",
            "NekoSuneAI mobile dashboard:",
            "NekoSuneAI VRM avatar:",
            "NekoSuneAI nodes and routines:",
        )
        if text.startswith(prefixes):
            text = text.split("?token=", 1)[0]
            args = (text, *args[1:])
    builtins.print(*args, **kwargs)


def install_dashboard_domain_freshness_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_server = http.server.ThreadingHTTPServer

    class FreshDashboardHTTPServer(original_server):
        def __init__(self, server_address, RequestHandlerClass, *args, **kwargs):
            base_handler = RequestHandlerClass

            class FreshDashboardHandler(base_handler):
                def _fresh_path(self) -> str:
                    try:
                        return urlparse(self.path).path
                    except Exception:
                        return ""

                def end_headers(self):
                    path = self._fresh_path()
                    if path in {
                        "/", "/index.html", "/mobile", "/mobile.html",
                        "/automations", "/avatar-upload", "/avatar-upload.html",
                    } or path.endswith((".js", ".css", ".html")):
                        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                        self.send_header("Pragma", "no-cache")
                        self.send_header("Expires", "0")
                    super().end_headers()

                def do_GET(self):
                    if self._fresh_path() == "/api/dashboard-build-id":
                        body = json.dumps({"build_id": _BUILD_ID}).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    return super().do_GET()

            super().__init__(server_address, FreshDashboardHandler, *args, **kwargs)

    http.server.ThreadingHTTPServer = FreshDashboardHTTPServer

    try:
        from . import webserver

        webserver.ThreadingHTTPServer = FreshDashboardHTTPServer
        # Keep the old fallback access token internal for compatibility, but do
        # not print it into Docker logs now that the HTTPS dashboard uses login.
        webserver.print = _clean_startup_print  # type: ignore[attr-defined]

        original_decorate = webserver._decorate_dashboard
        if not getattr(original_decorate, "_neko_dashboard_freshness", False):
            def decorate(body):
                rendered = original_decorate(body)
                was_bytes = isinstance(rendered, (bytes, bytearray))
                text = bytes(rendered).decode("utf-8") if was_bytes else str(rendered)
                if "neko-dashboard-freshness" not in text:
                    marker = "</body>"
                    text = text.replace(marker, _FRESHNESS_UI + marker, 1) if marker in text else text + _FRESHNESS_UI
                return text.encode("utf-8") if was_bytes else text

            decorate._neko_dashboard_freshness = True  # type: ignore[attr-defined]
            webserver._decorate_dashboard = decorate
    except Exception:
        pass
