from __future__ import annotations

import json
from typing import Any

_INSTALLED = False


def _field(key: str, label: str, ftype: str = "text", **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": ftype, **extra}


def _read_saved_app_settings() -> dict[str, Any]:
    try:
        from . import database

        value = json.loads(database.get_state("app_settings", "{}") or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_app_setting(key: str, value: Any) -> None:
    try:
        from . import database

        store = _read_saved_app_settings()
        store[key] = value
        database.set_state("app_settings", json.dumps(store))
    except Exception:
        pass


def _install_schema() -> None:
    from . import webgui

    schema = webgui.APP_SETTINGS_SCHEMA

    llm = schema.get("llm", {"label": "AI Provider & Models", "fields": []})
    llm["fields"] = [
        f for f in llm.get("fields", [])
        if f.get("key") not in {"vision_model", "rag_embedding_provider", "rag_embedding_model"}
    ]
    existing_llm = {f.get("key") for f in llm["fields"]}
    for f in [
        _field("llm_keep_alive", "Ollama keep-alive", "text"),
        _field("llm_num_predict", "Maximum generated tokens", "int"),
        _field("llm_num_ctx", "Context window (0 = backend default)", "int"),
        _field("request_timeout", "AI request timeout (seconds)", "int"),
        _field("history_turns", "Conversation turns kept in context", "int"),
        _field("auto_tune_performance", "Automatically tune for this machine", "bool"),
        _field("auto_tune_goal", "Auto-tune goal", "select", options=["balanced", "speed", "quality"]),
    ]:
        if f["key"] not in existing_llm:
            llm["fields"].append(f)
    schema["llm"] = llm

    schema["vision"] = {
        "label": "Vision & Scene Understanding",
        "description": "Choose the model used by Watch & React, phone/Kinect camera vision and other image-aware companion features.",
        "fields": [
            _field("vision_model", "Vision model", "model", category="vision"),
        ],
    }

    rag = schema.get("rag", {"label": "Memory (RAG)", "fields": []})
    rag_keys = {f.get("key") for f in rag.get("fields", [])}
    for f in [
        _field("rag_embedding_provider", "Embedding provider", "select", options=["local", "ollama", "openai"]),
        _field("rag_embedding_model", "Embedding model", "model", category="embedding"),
    ]:
        if f["key"] not in rag_keys:
            rag["fields"].insert(0, f)
    rag["description"] = "Long-term memory retrieval, embedding model and recall thresholds."
    schema["rag"] = rag

    stt = schema.get("stt", {"label": "Speech-to-Text", "fields": []})
    stt_keys = {f.get("key") for f in stt.get("fields", [])}
    for f in [
        _field("stt_use_gpu", "Use GPU when supported", "bool"),
        _field("stt_compute_type", "Whisper compute type", "text"),
        _field("stt_beam_size", "Beam size", "int"),
        _field("stt_best_of", "Best-of candidates", "int"),
        _field("stt_vad_filter", "Use voice activity detection filter", "bool"),
        _field("stt_timeout_seconds", "Speech recognition timeout (seconds)", "float"),
        _field("stt_non_speaking_duration_seconds", "Non-speaking duration (seconds)", "float"),
        _field("stt_ambient_duration_seconds", "Ambient-noise calibration time (seconds)", "float"),
    ]:
        if f["key"] not in stt_keys:
            stt["fields"].append(f)
    stt["description"] = "Microphone recognition engine, Whisper/Vosk tuning and room-noise behaviour."
    schema["stt"] = stt

    web = schema.get("web", {"label": "Web Search", "fields": []})
    web_keys = {f.get("key") for f in web.get("fields", [])}
    prefix = []
    if "web_browsing_enabled" not in web_keys:
        prefix.append(_field("web_browsing_enabled", "Enable web browsing", "bool"))
    if "web_auto_search" not in web_keys:
        prefix.append(_field("web_auto_search", "Automatically search when useful", "bool"))
    web["fields"] = prefix + web.get("fields", [])
    web["description"] = "Search provider, automatic browsing, regional results and gateway authentication."
    schema["web"] = web

    voice = schema.get("voice", {"label": "Voice (TTS)", "fields": []})
    voice["description"] = "Spoken replies, multilingual speech, XTTS cloning and optional RVC voice conversion."
    schema["voice"] = voice

    media = schema.get("media", {"label": "Media", "fields": []})
    media["description"] = "Music provider and the sounds used while the assistant is processing longer requests."
    schema["media"] = media

    schema["youtube"] = {
        "label": "YouTube Music & yt-dlp Nightly",
        "description": "API-key-free yt-search discovery plus the always-updated yt-dlp nightly stream resolver used by the Music page.",
        "fields": [
            _field("youtube_music_volume", "Default YouTube music volume (0-100)", "int"),
            _field("ytdlp_cookies_file", "yt-dlp cookies file (optional)", "text"),
        ],
    }

    descriptions = {
        "llm": "Provider, chat model, context limits and performance behaviour.",
        "mcp": "Remote MCP tools, OAuth and NekoAI Bridge voice connectivity.",
        "alerts": "Warning sounds and spoken monitor or emergency announcements.",
        "bluetooth": "Automatic Bluetooth speaker/Alexa reconnection.",
        "home": "Wake word recognition and Home Assistant MQTT integration.",
        "singing": "Singing backend, RVC model and cloud singing service.",
    }
    for key, text in descriptions.items():
        if key in schema:
            schema[key]["description"] = text

    webgui._APP_FIELD_TYPES.clear()
    webgui._APP_FIELD_TYPES.update({
        f["key"]: f["type"]
        for meta in schema.values()
        for f in meta.get("fields", [])
    })


SETTINGS_UI = r'''
<style id="neko-settings-redesign-css">
#page-settings.settings-redesigned{padding:18px!important;gap:14px!important;background:radial-gradient(circle at 75% 0,rgba(124,58,237,.10),transparent 30%)}
#page-settings .settings-hero{border:1px solid rgba(167,139,250,.28);background:linear-gradient(120deg,rgba(25,28,58,.96),rgba(13,15,36,.96));box-shadow:0 18px 55px rgba(0,0,0,.24),inset 0 1px rgba(255,255,255,.03)}
#page-settings .settings-workspace{display:grid;grid-template-columns:245px minmax(0,1fr);gap:14px;align-items:start}
#page-settings .settings-subnav{position:sticky;top:0;display:flex;flex-direction:column;gap:7px;padding:12px;border-radius:16px;border:1px solid rgba(120,126,190,.22);background:linear-gradient(160deg,rgba(17,19,41,.97),rgba(10,11,28,.97));box-shadow:0 16px 44px rgba(0,0,0,.20)}
#page-settings .settings-subnav-title{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:#777da9;font-weight:800;padding:3px 5px 7px}
#page-settings #settings-tabs{display:flex!important;flex-direction:column;gap:6px;margin:0!important}
#page-settings .settings-nav-btn{width:100%;text-align:left;display:grid;grid-template-columns:30px 1fr;gap:9px;padding:10px;border:1px solid transparent;border-radius:12px;color:#b3b7dc;background:transparent;transition:.16s ease}
#page-settings .settings-nav-btn:hover{background:rgba(167,139,250,.07);border-color:rgba(167,139,250,.18);transform:translateX(2px)}
#page-settings .settings-nav-btn.active{background:linear-gradient(100deg,rgba(167,139,250,.18),rgba(103,232,249,.07));border-color:rgba(167,139,250,.35);color:#fff;box-shadow:inset 0 0 22px rgba(167,139,250,.06)}
#page-settings .settings-nav-icon{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;background:rgba(167,139,250,.09);font-size:15px}
#page-settings .settings-nav-name{font-size:11px;font-weight:750;line-height:1.2}
#page-settings .settings-nav-desc{font-size:9px;color:#777da9;line-height:1.25;margin-top:3px}
#page-settings .settings-main{min-width:0;display:flex;flex-direction:column;gap:12px}
#page-settings #app-settings{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px!important}
#page-settings .settings-config-card{position:relative;overflow:hidden;border:1px solid rgba(120,126,190,.23);border-radius:15px;padding:15px;background:linear-gradient(145deg,rgba(24,27,56,.90),rgba(13,15,34,.96));box-shadow:0 12px 30px -18px rgba(0,0,0,.8)}
#page-settings .settings-config-card::before{content:'';position:absolute;inset:0 0 auto 0;height:1px;background:linear-gradient(90deg,transparent,rgba(167,139,250,.75),rgba(103,232,249,.55),transparent)}
#page-settings .settings-config-card:hover{border-color:rgba(167,139,250,.36)}
#page-settings .settings-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:13px}
#page-settings .settings-card-icon{width:34px;height:34px;display:grid;place-items:center;border-radius:10px;background:linear-gradient(135deg,rgba(167,139,250,.18),rgba(103,232,249,.09));border:1px solid rgba(167,139,250,.18);font-size:16px}
#page-settings .settings-card-title{font-size:12px;font-weight:800;color:#f4f2ff}.settings-card-desc{font-size:10px;color:#8f95c5;line-height:1.35;margin-top:3px;max-width:620px}
#page-settings .settings-field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px 11px}
#page-settings .settings-field-grid label{min-width:0}
#page-settings .settings-field-grid input:not([type=checkbox]),#page-settings .settings-field-grid select,#page-settings .settings-field-grid textarea{background:#0b0d20;border-color:#30355c;min-height:37px}
#page-settings .settings-field-grid textarea{min-height:120px}
#page-settings .settings-check{grid-column:span 2;padding:9px 10px;border:1px solid rgba(120,126,190,.16);border-radius:10px;background:rgba(255,255,255,.018)}
#page-settings .settings-save-btn{min-width:94px;white-space:nowrap}
#page-settings .settings-tools-row{display:flex;flex-wrap:wrap;gap:7px;justify-content:flex-end}
#page-settings .settings-quick-card{border-color:rgba(103,232,249,.18)!important;background:linear-gradient(145deg,rgba(18,22,46,.88),rgba(12,14,32,.94))!important}
#page-settings .settings-empty{grid-column:1/-1;padding:35px;text-align:center;color:#777da9;border:1px dashed #343961;border-radius:14px}
@media(max-width:1180px){#page-settings .settings-workspace{grid-template-columns:205px minmax(0,1fr)}#page-settings #app-settings{grid-template-columns:1fr}}
@media(max-width:780px){#page-settings.settings-redesigned{padding:10px!important}#page-settings .settings-workspace{grid-template-columns:1fr}#page-settings .settings-subnav{position:static}#page-settings #settings-tabs{flex-direction:row!important;overflow-x:auto;padding-bottom:3px}#page-settings .settings-nav-btn{min-width:180px}#page-settings .settings-field-grid{grid-template-columns:1fr}#page-settings .settings-check{grid-column:span 1}}
</style>
<script id="neko-settings-redesign-js">
(function(){
  const icons={all:'⌂',ai:'✦',voice:'◖',connections:'⌁',home:'⌾',media:'♫'};
  const descriptions={all:'Everything in one view',ai:'Models, vision & memory',voice:'TTS, STT & audio',connections:'Web, MCP & alerts',home:'Wake word & smart home',media:'Music, YouTube & singing'};
  window.SETTINGS_CATEGORIES={
    all:{label:'All Settings',sections:[]},
    ai:{label:'AI & Vision',sections:['llm','vision','rag']},
    voice:{label:'Voice & Speech',sections:['voice','stt','bluetooth']},
    connections:{label:'Web & Connections',sections:['web','mcp','alerts']},
    home:{label:'Home & Wake Word',sections:['home']},
    media:{label:'Media & YouTube',sections:['media','youtube','singing']},
  };
  window.renderSettingsTabs=function(){
    const tabs=document.getElementById('settings-tabs');if(!tabs)return;
    tabs.innerHTML=Object.entries(window.SETTINGS_CATEGORIES).map(([key,item])=>`<button onclick="setSettingsCategory('${key}')" class="settings-nav-btn ${key===window._settingsCategory?'active':''}"><span class="settings-nav-icon">${icons[key]||'•'}</span><span><span class="settings-nav-name">${item.label}</span><span class="settings-nav-desc">${descriptions[key]||''}</span></span></button>`).join('');
  };
  window.setSettingsCategory=function(category){
    window._settingsCategory=window.SETTINGS_CATEGORIES[category]?category:'all';
    const search=document.getElementById('settings-search');if(search)search.value='';
    window.renderSettingsTabs();window.filterSettings('');
  };
  const sectionIcons={llm:'✦',vision:'◉',rag:'▤',voice:'◖',stt:'≋',web:'⌕',mcp:'⌁',alerts:'!',bluetooth:'⌁',home:'⌾',media:'♫',youtube:'▶',singing:'♪'};
  const originalRender=window._renderAppSection;
  window._renderAppSection=function(name,meta){
    const card=document.createElement('section');card.className='settings-config-card';card.dataset.settingsSection=name;
    const fields=(meta.fields||[]).map(f=>{
      const id='aset__'+name+'__'+f.key,v=f.value!=null?String(f.value):'';
      if(f.type==='bool')return `<label class="settings-check flex items-center gap-2 text-[11px] text-nova-muted2"><input id="${id}" type="checkbox" class="w-4 h-4 rounded accent-violet-400" ${f.value?'checked':''}/><span>${escHtml(f.label)}</span></label>`;
      if(f.type==='select'){const opts=(f.options||[]).map(o=>`<option ${String(f.value)===String(o)?'selected':''}>${escHtml(o)}</option>`).join('');return `<label class="flex flex-col gap-1 text-[10px] text-nova-muted"><span>${escHtml(f.label)}</span><select id="${id}" class="w-full">${opts}</select></label>`;}
      if(f.type==='model')return `<label class="flex flex-col gap-1 text-[10px] text-nova-muted"><span>${escHtml(f.label)}</span><input id="${id}" list="dl-${f.category||'chat'}" class="w-full" value="${escHtml(v)}"/></label>`;
      if(f.type==='textarea')return `<label class="flex flex-col gap-1 text-[10px] text-nova-muted col-span-2"><span>${escHtml(f.label)}</span><textarea id="${id}" rows="5" spellcheck="false" class="w-full font-mono text-[10px] resize-y">${escHtml(v)}</textarea></label>`;
      const itype=f.type==='password'?'password':((f.type==='float'||f.type==='int')?'number':'text'),step=f.type==='float'?' step="0.05"':'';
      return `<label class="flex flex-col gap-1 text-[10px] text-nova-muted"><span>${escHtml(f.label)}</span><input id="${id}" type="${itype}"${step} class="w-full" value="${escHtml(v)}"/></label>`;
    }).join('');
    const actions=name==='mcp'?`<button class="btn-secondary px-2.5 py-1.5 rounded-lg text-[10px]" onclick="doConnectMcpOAuth()">Connect OAuth</button>`:name==='bluetooth'?`<button class="btn-secondary px-2.5 py-1.5 rounded-lg text-[10px]" onclick="doReconnectAlexa()">Reconnect</button><button class="btn-secondary px-2.5 py-1.5 rounded-lg text-[10px]" onclick="doTestTtsOutput()">Test Audio</button>`:name==='home'?`<button class="btn-secondary px-2.5 py-1.5 rounded-lg text-[10px]" onclick="doTestWakeSound()">Test Wake Sound</button>`:'';
    card.innerHTML=`<div class="settings-card-head"><div class="flex gap-3 min-w-0"><span class="settings-card-icon">${sectionIcons[name]||'⚙'}</span><div class="min-w-0"><div class="settings-card-title">${escHtml(meta.label)}</div><div class="settings-card-desc">${escHtml(meta.description||'Configure this part of NekoSuneAI.')}</div></div></div><div class="settings-tools-row">${actions}<button class="btn-primary settings-save-btn px-3 py-1.5 rounded-lg text-[10px]" onclick="doSaveAppSection('${name}')">Save</button></div></div><div class="settings-field-grid">${fields}</div>`;
    return card;
  };
  const oldFilter=window.filterSettings;
  window.filterSettings=function(query){
    if(oldFilter)oldFilter(query);
    const wrap=document.getElementById('app-settings');if(!wrap)return;
    const visible=[...wrap.querySelectorAll('[data-settings-section]')].filter(x=>!x.classList.contains('hidden'));
    let empty=document.getElementById('settings-empty-state');
    if(!visible.length){if(!empty){empty=document.createElement('div');empty.id='settings-empty-state';empty.className='settings-empty';empty.textContent='No settings match this category or search.';wrap.appendChild(empty);}}else if(empty)empty.remove();
  };
  function arrange(){
    const page=document.getElementById('page-settings');if(!page||page.classList.contains('settings-redesigned'))return;
    page.classList.add('settings-redesigned');
    const hero=page.querySelector(':scope > .card');if(hero)hero.classList.add('settings-hero');
    const config=[...page.children].find(x=>x.querySelector&&x.querySelector('#app-settings'));if(!config)return;
    const tabs=document.getElementById('settings-tabs'),search=document.getElementById('settings-search');
    const workspace=document.createElement('div');workspace.className='settings-workspace';
    const nav=document.createElement('aside');nav.className='settings-subnav';nav.innerHTML='<div class="settings-subnav-title">Settings</div>';
    if(tabs)nav.appendChild(tabs);if(search){search.classList.remove('mt-3');search.placeholder='Search settings…';nav.appendChild(search);}
    const main=document.createElement('main');main.className='settings-main';
    const title=config.querySelector('.text-\\[13px\\].font-bold');if(title)title.textContent='Configuration Workspace';
    config.classList.add('settings-quick-card');main.appendChild(config);
    [...page.querySelectorAll(':scope > [data-settings-quick]')].forEach(x=>{x.classList.add('settings-quick-card');main.appendChild(x)});
    workspace.appendChild(nav);workspace.appendChild(main);page.appendChild(workspace);window.renderSettingsTabs();window.filterSettings(search?search.value:'');
  }
  addEventListener('DOMContentLoaded',()=>{arrange();setTimeout(arrange,120)});setTimeout(arrange,30);
})();
</script>
'''


def _install_dashboard_ui() -> None:
    from . import webserver

    original = webserver._decorate_dashboard
    if getattr(original, "_neko_settings_redesign", False):
        return

    def decorated(body: bytes) -> bytes:
        result = original(body)
        text = result.decode("utf-8")
        if "neko-settings-redesign-css" not in text:
            text = text.replace("</body>", SETTINGS_UI + "</body>", 1)
        return text.encode("utf-8")

    decorated._neko_settings_redesign = True  # type: ignore[attr-defined]
    webserver._decorate_dashboard = decorated


def _install_youtube_settings() -> None:
    from .youtube_music import YouTubeMusicPlayer

    if getattr(YouTubeMusicPlayer, "_neko_settings_patched", False):
        return

    original_init = YouTubeMusicPlayer.__init__
    original_common_args = YouTubeMusicPlayer._common_args
    original_set_volume = YouTubeMusicPlayer.set_volume

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        saved = _read_saved_app_settings()
        try:
            self._volume = max(0, min(100, int(saved.get("youtube_music_volume", self._volume))))
        except (TypeError, ValueError):
            pass

    def patched_common_args(self):
        args = original_common_args(self)
        saved = _read_saved_app_settings()
        cookies = str(saved.get("ytdlp_cookies_file", "") or "").strip()
        if cookies:
            cleaned: list[str] = []
            skip = False
            for item in args:
                if skip:
                    skip = False
                    continue
                if item == "--cookies":
                    skip = True
                    continue
                cleaned.append(item)
            args = cleaned + ["--cookies", cookies]
        return args

    def patched_set_volume(self, percent: int):
        result = original_set_volume(self, percent)
        _save_app_setting("youtube_music_volume", int(self._volume))
        return result

    YouTubeMusicPlayer.__init__ = patched_init
    YouTubeMusicPlayer._common_args = patched_common_args
    YouTubeMusicPlayer.set_volume = patched_set_volume
    YouTubeMusicPlayer._neko_settings_patched = True


def install_settings_dashboard_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_schema()
    _install_youtube_settings()
    _install_dashboard_ui()
    _INSTALLED = True
