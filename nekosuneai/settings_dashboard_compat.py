from __future__ import annotations

_INSTALLED = False

COMPAT_UI = r'''
<script id="neko-settings-redesign-compat">
(function(){
  // The stock dashboard declares these with top-level let/const. They are
  // global lexical bindings (not window properties), so update those bindings
  // directly rather than creating a second disconnected window object.
  Object.assign(SETTINGS_CATEGORIES, {
    all:{label:'All Settings',sections:[]},
    ai:{label:'AI & Vision',sections:['llm','vision','rag']},
    voice:{label:'Voice & Speech',sections:['voice','stt','bluetooth']},
    connections:{label:'Web & Connections',sections:['web','mcp','alerts']},
    home:{label:'Home & Wake Word',sections:['home']},
    media:{label:'Media & YouTube',sections:['media','youtube','singing']},
    vtuber:{label:'VTuber & VRChat',sections:['vrchat_friends']},
  });
  const icons={all:'⌂',ai:'✦',voice:'◖',connections:'⌁',home:'⌾',media:'♫',vtuber:'◇'};
  const descriptions={all:'Everything in one view',ai:'Models, vision & memory',voice:'TTS, STT & audio',connections:'Web, MCP & alerts',home:'Wake word & smart home',media:'Music, YouTube & singing',vtuber:'VRChat integration'};
  renderSettingsTabs=function(){
    const tabs=document.getElementById('settings-tabs');if(!tabs)return;
    tabs.innerHTML=Object.entries(SETTINGS_CATEGORIES).map(([key,item])=>`<button onclick="setSettingsCategory('${key}')" class="settings-nav-btn ${key===_settingsCategory?'active':''}"><span class="settings-nav-icon">${icons[key]||'•'}</span><span><span class="settings-nav-name">${item.label}</span><span class="settings-nav-desc">${descriptions[key]||''}</span></span></button>`).join('');
  };
  setSettingsCategory=function(category){
    _settingsCategory=SETTINGS_CATEGORIES[category]?category:'all';
    const search=document.getElementById('settings-search');if(search)search.value='';
    renderSettingsTabs();filterSettings('');
  };
  // Replace the disconnected window-backed versions installed by the visual
  // patch so onclick handlers and existing stock filtering share one state.
  window.renderSettingsTabs=renderSettingsTabs;
  window.setSettingsCategory=setSettingsCategory;
})();
</script>
'''


def install_settings_dashboard_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from . import webserver

    original = webserver._decorate_dashboard
    if getattr(original, "_neko_settings_compat", False):
        _INSTALLED = True
        return

    def decorated(body: bytes) -> bytes:
        result = original(body)
        text = result.decode("utf-8")
        if "neko-settings-redesign-compat" not in text:
            text = text.replace("</body>", COMPAT_UI + "</body>", 1)
        return text.encode("utf-8")

    decorated._neko_settings_compat = True  # type: ignore[attr-defined]
    webserver._decorate_dashboard = decorated
    _INSTALLED = True
