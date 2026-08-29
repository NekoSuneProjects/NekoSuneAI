from __future__ import annotations

from typing import Any

_INSTALLED = False
_ACTIVE_PLAYER = None


def _install_player_registry() -> None:
    from .youtube_music import YouTubeMusicPlayer

    if getattr(YouTubeMusicPlayer, "_neko_music_registry", False):
        return
    original_init = YouTubeMusicPlayer.__init__

    def patched_init(self, *args, **kwargs):
        global _ACTIVE_PLAYER
        original_init(self, *args, **kwargs)
        _ACTIVE_PLAYER = self

    YouTubeMusicPlayer.__init__ = patched_init
    YouTubeMusicPlayer._neko_music_registry = True


def _player():
    if _ACTIVE_PLAYER is None:
        raise RuntimeError("YouTube music player is not ready yet.")
    return _ACTIVE_PLAYER


def _install_api() -> None:
    from .webgui import Api
    from .youtube_music import Track

    if getattr(Api, "_neko_music_dashboard_api", False):
        return

    def music_dashboard_state(self) -> dict[str, Any]:
        player = _player()
        return {"status": player.status_dict(), "playlists": player.playlists_snapshot()}

    def music_dashboard_search(self, query: str) -> dict[str, Any]:
        player = _player()
        return {"items": [track.as_dict() for track in player.search_many(str(query), 12)]}

    def music_dashboard_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        player = _player()
        data = payload or {}
        action = str(action or "").strip().lower()
        if action == "play_query":
            message = player.play_query(str(data.get("query", "")))
        elif action == "play_url":
            message = player.play_url(str(data.get("url", "")), str(data.get("title", "YouTube track")))
        elif action == "pause":
            message = player.pause()
        elif action == "resume":
            message = player.resume()
        elif action == "stop":
            message = player.stop()
        elif action == "skip":
            message = player.skip()
        elif action == "previous":
            message = player.previous()
        elif action == "volume":
            message = player.set_volume(int(data.get("value", 75)))
        elif action == "create_playlist":
            message = player.create_playlist(str(data.get("name", "")))
        elif action == "delete_playlist":
            message = player.delete_playlist(str(data.get("name", "")))
        elif action == "play_playlist":
            message = player.play_playlist(str(data.get("name", "")), False)
        elif action == "shuffle_playlist":
            message = player.play_playlist(str(data.get("name", "")), True)
        elif action == "import_playlist":
            message = player.import_playlist(str(data.get("name", "imported")), str(data.get("url", "")))
        elif action == "add_track":
            track = Track(
                str(data.get("title", "YouTube track")),
                str(data.get("url", "")),
                str(data.get("author", "")),
                str(data.get("duration", "")),
                str(data.get("thumbnail", "")),
            )
            message = player.add_track_to_playlist(str(data.get("playlist", "")), track)
        else:
            raise ValueError(f"Unknown music action: {action}")
        return {"ok": True, "message": message, "status": player.status_dict(), "playlists": player.playlists_snapshot()}

    Api.music_dashboard_state = music_dashboard_state
    Api.music_dashboard_search = music_dashboard_search
    Api.music_dashboard_action = music_dashboard_action
    Api._neko_music_dashboard_api = True


MUSIC_UI = r'''
<style id="neko-music-dashboard-css">
#page-music{background:radial-gradient(circle at 80% 0,rgba(103,232,249,.08),transparent 32%)}
.music-hero{background:linear-gradient(130deg,rgba(32,36,73,.96),rgba(12,14,32,.98));border:1px solid rgba(167,139,250,.26);box-shadow:0 18px 50px rgba(0,0,0,.22)}
.music-result{display:grid;grid-template-columns:58px minmax(0,1fr) auto;gap:12px;align-items:center;padding:10px;border:1px solid rgba(120,126,190,.17);border-radius:13px;background:rgba(13,15,36,.74)}
.music-result img{width:58px;height:44px;object-fit:cover;border-radius:9px;background:#0b0d20}
.music-playlist{border:1px solid rgba(120,126,190,.18);background:rgba(13,15,36,.72);border-radius:13px;padding:11px}
.music-control{min-width:72px}
.music-now-art{width:82px;height:62px;object-fit:cover;border-radius:12px;background:#0b0d20;border:1px solid #343961}
@media(max-width:900px){#page-music .music-layout{grid-template-columns:1fr!important}.music-result{grid-template-columns:48px minmax(0,1fr)}.music-result-actions{grid-column:1/-1}.music-result img{width:48px;height:40px}}
</style>
<script id="neko-music-dashboard-js">
(function(){
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const token=()=>new URLSearchParams(location.search).get('token')||'';
  async function rpc(method,args=[]){
    const r=await fetch('/api/rpc',{method:'POST',headers:{'Content-Type':'application/json','X-Neko-Token':token()},body:JSON.stringify({method,args})});
    const j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');return j.result;
  }
  function mount(){
    if(document.getElementById('page-music'))return;
    const settingsBtn=document.querySelector('[data-page="settings"]');
    const nav=document.createElement('button');
    nav.setAttribute('data-page','music');nav.className='nav-item w-full text-left px-5 py-2.5 text-[13px] text-nova-muted2 border-l-[3px] border-transparent flex items-center gap-2.5';
    nav.innerHTML='<span class="w-5 text-center opacity-70">♫</span> Music & Playlists';nav.onclick=()=>openMusicPage();
    settingsBtn?.parentElement?.insertBefore(nav,settingsBtn);
    const host=document.getElementById('page-settings')?.parentElement;if(!host)return;
    const page=document.createElement('div');page.id='page-music';page.className='page flex-col h-full overflow-y-auto p-5 lg:p-6 gap-4';
    page.innerHTML=`
      <section class="card music-hero p-5"><div class="section-kicker">YouTube Music Studio</div><div class="flex flex-wrap items-end justify-between gap-3 mt-1"><div><div class="text-xl font-bold">Music & Playlists</div><div class="text-[11px] text-nova-muted2 mt-1">API-key-free search through yt-search, resilient yt-dlp nightly stream resolving, MP4/HLS playback and local playlists.</div></div><span class="live-pill">yt-dlp nightly</span></div></section>
      <div class="music-layout grid grid-cols-[minmax(0,1.45fr)_minmax(330px,.75fr)] gap-4">
        <div class="space-y-4">
          <section class="card p-4"><div class="text-[13px] font-bold mb-3">Search YouTube</div><div class="flex gap-2"><input id="music-search-input" class="flex-1" placeholder="Search artist, song, video…" onkeydown="if(event.key==='Enter')musicSearch()"><button class="btn-primary px-4 rounded-lg text-[11px]" onclick="musicSearch()">Search</button></div><div id="music-search-results" class="space-y-2 mt-4"><div class="text-[11px] text-nova-muted">Search results appear here.</div></div></section>
          <section class="card p-4"><div class="flex items-center justify-between gap-2 mb-3"><div class="text-[13px] font-bold">Playlists</div><button class="btn-secondary px-3 py-1.5 rounded-lg text-[10px]" onclick="musicCreatePlaylist()">New Playlist</button></div><div class="flex gap-2 mb-3"><input id="music-import-url" class="flex-1" placeholder="YouTube playlist URL"><input id="music-import-name" class="w-40" placeholder="Playlist name"><button class="btn-secondary px-3 rounded-lg text-[10px]" onclick="musicImportPlaylist()">Import</button></div><div id="music-playlists" class="space-y-2"><div class="text-[11px] text-nova-muted">No playlists loaded.</div></div></section>
        </div>
        <div class="space-y-4">
          <section class="card p-4 sticky top-0"><div class="section-kicker mb-2">Now playing</div><div class="flex gap-3 items-center"><img id="music-now-art" class="music-now-art" alt=""><div class="min-w-0"><div id="music-now-title" class="text-[14px] font-bold truncate">Nothing playing</div><div id="music-now-meta" class="text-[10px] text-nova-muted mt-1">Ready.</div></div></div><div class="grid grid-cols-3 gap-2 mt-4"><button class="btn-secondary music-control rounded-lg py-2 text-[11px]" onclick="musicAction('previous')">Previous</button><button class="btn-primary music-control rounded-lg py-2 text-[11px]" onclick="musicAction('pause')">Pause</button><button class="btn-secondary music-control rounded-lg py-2 text-[11px]" onclick="musicAction('resume')">Resume</button><button class="btn-secondary music-control rounded-lg py-2 text-[11px]" onclick="musicAction('skip')">Next</button><button class="btn-danger music-control rounded-lg py-2 text-[11px]" onclick="musicAction('stop')">Stop</button><button class="btn-secondary music-control rounded-lg py-2 text-[11px]" onclick="musicRefresh()">Refresh</button></div><label class="block mt-4 text-[10px] text-nova-muted">Volume <span id="music-volume-label">75%</span><input id="music-volume" type="range" min="0" max="100" value="75" class="w-full mt-1" oninput="document.getElementById('music-volume-label').textContent=this.value+'%'" onchange="musicAction('volume',{value:Number(this.value)})"></label><div id="music-stream-info" class="text-[9px] text-nova-muted mt-3 break-all"></div></section>
        </div>
      </div>`;
    host.appendChild(page);
  }
  window.openMusicPage=function(){showPage('music');const t=document.getElementById('page-title'),s=document.getElementById('page-sub');if(t)t.textContent='Music & Playlists';if(s)s.textContent='YouTube search, playback and playlists';musicRefresh();};
  window.musicSearch=async function(){const input=document.getElementById('music-search-input'),out=document.getElementById('music-search-results'),q=input?.value.trim();if(!q)return;out.innerHTML='<div class="text-[11px] text-nova-muted">Searching without a YouTube API key…</div>';try{const j=await rpc('music_dashboard_search',[q]);const items=j.items||[];out.innerHTML=items.length?items.map((x,i)=>`<div class="music-result"><img src="${esc(x.thumbnail)}"><div class="min-w-0"><div class="text-[12px] font-semibold truncate">${esc(x.title)}</div><div class="text-[10px] text-nova-muted truncate">${esc(x.author)}${x.duration?' · '+esc(x.duration):''}</div></div><div class="music-result-actions flex gap-2"><button class="btn-primary px-3 py-1.5 rounded-lg text-[10px]" data-play="${i}">Play</button><button class="btn-secondary px-3 py-1.5 rounded-lg text-[10px]" data-add="${i}">Add</button></div></div>`).join(''):'<div class="text-[11px] text-nova-muted">No videos found.</div>';out.querySelectorAll('[data-play]').forEach(b=>b.onclick=()=>{const x=items[Number(b.dataset.play)];musicAction('play_url',{url:x.webpage_url,title:x.title})});out.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>{const x=items[Number(b.dataset.add)],playlist=prompt('Add to which playlist?');if(playlist)musicAction('add_track',{playlist,title:x.title,url:x.webpage_url,author:x.author,duration:x.duration,thumbnail:x.thumbnail})});}catch(e){out.innerHTML='<div class="text-[11px] text-red-300">'+esc(e.message)+'</div>'}};
  window.musicAction=async function(action,payload={}){try{const j=await rpc('music_dashboard_action',[action,payload]);renderState({status:j.status,playlists:j.playlists});if(j.message)showNotification?.(j.message,'success')}catch(e){showNotification?.(e.message,'error')}};
  window.musicCreatePlaylist=async function(){const name=prompt('Playlist name');if(name)await musicAction('create_playlist',{name})};
  window.musicImportPlaylist=async function(){const url=document.getElementById('music-import-url')?.value.trim(),name=document.getElementById('music-import-name')?.value.trim()||'imported';if(url)await musicAction('import_playlist',{url,name})};
  window.musicRefresh=async function(){try{renderState(await rpc('music_dashboard_state'))}catch(e){console.warn(e)}};
  function renderState(j){const st=j.status||{},now=st.now||null,title=document.getElementById('music-now-title'),meta=document.getElementById('music-now-meta'),art=document.getElementById('music-now-art'),vol=document.getElementById('music-volume'),vl=document.getElementById('music-volume-label'),stream=document.getElementById('music-stream-info');if(title)title.textContent=now?.title||'Nothing playing';if(meta)meta.textContent=now?(st.paused?'Paused':'Playing')+(st.playlist?' · '+st.playlist:''):`Ready · ${st.queue?.length||0} queued`;if(art){art.src=now?.thumbnail||'';art.style.visibility=now?.thumbnail?'visible':'hidden'}if(vol)vol.value=Number(st.volume??75);if(vl)vl.textContent=String(st.volume??75)+'%';if(stream){const s=st.stream||{};stream.textContent=s.url?`Stream: ${s.protocol||'direct'} · ${s.ext||'unknown'} · format ${s.format_id||'auto'}`:'Stream resolver ready (MP4/HLS/direct audio).'}const wrap=document.getElementById('music-playlists'),pls=j.playlists||{};if(wrap){const rows=Object.entries(pls);wrap.innerHTML=rows.length?rows.map(([name,items])=>`<div class="music-playlist"><div class="flex items-center justify-between gap-3"><div><div class="text-[12px] font-semibold">${esc(name)}</div><div class="text-[10px] text-nova-muted">${items.length} track${items.length===1?'':'s'}</div></div><div class="flex gap-2"><button class="btn-primary px-3 py-1.5 rounded-lg text-[10px]" data-pl-play="${esc(name)}">Play</button><button class="btn-secondary px-3 py-1.5 rounded-lg text-[10px]" data-pl-shuffle="${esc(name)}">Shuffle</button><button class="btn-danger px-3 py-1.5 rounded-lg text-[10px]" data-pl-del="${esc(name)}">Delete</button></div></div><div class="text-[9px] text-nova-muted mt-2 truncate">${items.slice(0,4).map(x=>esc(x.title||'Track')).join(' · ')}</div></div>`).join(''):'<div class="text-[11px] text-nova-muted">No playlists yet.</div>';wrap.querySelectorAll('[data-pl-play]').forEach(b=>b.onclick=()=>musicAction('play_playlist',{name:b.dataset.plPlay}));wrap.querySelectorAll('[data-pl-shuffle]').forEach(b=>b.onclick=()=>musicAction('shuffle_playlist',{name:b.dataset.plShuffle}));wrap.querySelectorAll('[data-pl-del]').forEach(b=>b.onclick=()=>{if(confirm('Delete playlist '+b.dataset.plDel+'?'))musicAction('delete_playlist',{name:b.dataset.plDel})});}}
  }
  addEventListener('DOMContentLoaded',()=>{mount();setTimeout(mount,100)});setTimeout(mount,30);
  setInterval(()=>{if(document.getElementById('page-music')?.classList.contains('active'))musicRefresh()},4000);
})();
</script>
'''


def _install_ui() -> None:
    from . import webserver

    original = webserver._decorate_dashboard
    if getattr(original, "_neko_music_dashboard", False):
        return

    def decorated(body: bytes) -> bytes:
        result = original(body)
        text = result.decode("utf-8")
        if "neko-music-dashboard-css" not in text:
            text = text.replace("</body>", MUSIC_UI + "</body>", 1)
        return text.encode("utf-8")

    decorated._neko_music_dashboard = True  # type: ignore[attr-defined]
    webserver._decorate_dashboard = decorated


def install_music_dashboard_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_player_registry()
    _install_api()
    _install_ui()
    _INSTALLED = True
