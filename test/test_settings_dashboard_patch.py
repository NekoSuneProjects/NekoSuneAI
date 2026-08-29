from nekosuneai import settings_dashboard_patch as patch
from nekosuneai import webgui


def test_settings_schema_has_dedicated_vision_and_youtube_sections():
    patch._install_schema()

    assert "vision" in webgui.APP_SETTINGS_SCHEMA
    assert "youtube" in webgui.APP_SETTINGS_SCHEMA
    assert any(f["key"] == "vision_model" for f in webgui.APP_SETTINGS_SCHEMA["vision"]["fields"])
    assert any(f["key"] == "youtube_music_volume" for f in webgui.APP_SETTINGS_SCHEMA["youtube"]["fields"])
    assert any(f["key"] == "ytdlp_cookies_file" for f in webgui.APP_SETTINGS_SCHEMA["youtube"]["fields"])


def test_vision_and_embedding_controls_are_not_duplicated_in_llm_card():
    patch._install_schema()

    llm_keys = {f["key"] for f in webgui.APP_SETTINGS_SCHEMA["llm"]["fields"]}
    rag_keys = {f["key"] for f in webgui.APP_SETTINGS_SCHEMA["rag"]["fields"]}

    assert "vision_model" not in llm_keys
    assert "rag_embedding_provider" not in llm_keys
    assert "rag_embedding_model" not in llm_keys
    assert {"rag_embedding_provider", "rag_embedding_model"}.issubset(rag_keys)


def test_new_settings_are_persistable_by_generic_settings_backend():
    patch._install_schema()

    assert webgui._APP_FIELD_TYPES["youtube_music_volume"] == "int"
    assert webgui._APP_FIELD_TYPES["ytdlp_cookies_file"] == "text"
    assert webgui._APP_FIELD_TYPES["vision_model"] == "model"
    assert webgui._APP_FIELD_TYPES["web_auto_search"] == "bool"


def test_dashboard_injection_has_single_install_marker():
    assert 'id="neko-settings-redesign-css"' in patch.SETTINGS_UI
    assert 'settings-workspace' in patch.SETTINGS_UI
    assert 'Media & YouTube' in patch.SETTINGS_UI
