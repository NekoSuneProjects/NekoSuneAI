"""Music Assistant-first routing; never start local fallback after successful MA playback."""
from __future__ import annotations

from unittest.mock import Mock
import pytest

from nekosuneai.music_router import RoutedMusicController


def make_router(monkeypatch, *, playable=True, fallback=True):
    monkeypatch.setenv("MUSIC_ASSISTANT_URL", "http://music-assistant:8095")
    monkeypatch.setenv("MUSIC_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv("MUSIC_ASSISTANT_PLAYER_ID", "sendspin-test")
    monkeypatch.setenv("MUSIC_YOUTUBE_FALLBACK", str(fallback).lower())
    music = RoutedMusicController()
    music.client.play_query = Mock(return_value={"name": "Bangarang"})
    music.local.play = Mock(return_value={"ok": True, "playing": True, "title": "Bangarang"})
    music.local.stop = Mock(return_value={"ok": True})
    if not playable:
        music.client.player_id = ""
    return music


def test_music_assistant_preferred(monkeypatch):
    music = make_router(monkeypatch)
    result = music.play(["Skrillex Bangarang"])
    assert result["source"] == "music_assistant"
    music.client.play_query.assert_called_once_with("Skrillex Bangarang")
    music.local.play.assert_not_called()


def test_youtube_if_music_assistant_not_found(monkeypatch):
    music = make_router(monkeypatch)
    music.client.play_query.side_effect = RuntimeError("No result")
    result = music.play(["Skrillex Bangarang"])
    assert result["source"] == "youtube"
    music.local.play.assert_called_once()


def test_youtube_if_unconfigured(monkeypatch):
    music = make_router(monkeypatch, playable=False)
    result = music.play(["Skrillex Bangarang"])
    assert result["source"] == "youtube"
    music.local.play.assert_called_once()


def test_no_fallback_if_disabled(monkeypatch):
    music = make_router(monkeypatch, fallback=False)
    music.client.play_query.side_effect = RuntimeError("No result")
    with pytest.raises(RuntimeError, match="No result"):
        music.play(["Skrillex Bangarang"])
    music.local.play.assert_not_called()
