from __future__ import annotations

from pathlib import Path

from nekosuneai.youtube_music import YouTubeMusicPlayer


def test_stream_picker_accepts_hls_audio() -> None:
    player = YouTubeMusicPlayer()
    info = {
        "title": "Example",
        "webpage_url": "https://www.youtube.com/watch?v=example",
        "formats": [
            {"url": "https://example.invalid/video.mp4", "protocol": "https", "ext": "mp4", "acodec": "none", "vcodec": "avc1", "format_id": "137"},
            {"url": "https://example.invalid/audio.m3u8", "protocol": "m3u8_native", "ext": "m4a", "acodec": "mp4a", "vcodec": "none", "format_id": "140"},
        ],
    }
    stream = player._stream_from_info(info)
    assert stream["url"].endswith("audio.m3u8")
    assert stream["protocol"] == "m3u8_native"
    assert stream["acodec"] == "mp4a"


def test_stream_picker_prefers_audio_only_direct_url() -> None:
    player = YouTubeMusicPlayer()
    info = {
        "requested_downloads": [
            {"url": "https://example.invalid/audio.m4a", "protocol": "https", "ext": "m4a", "acodec": "mp4a", "vcodec": "none", "format_id": "140"}
        ],
        "formats": [],
    }
    assert player._stream_from_info(info)["url"].endswith("audio.m4a")


def test_yt_search_helper_is_shipped() -> None:
    helper = Path(__file__).resolve().parent.parent / "tools" / "yt_search.js"
    text = helper.read_text(encoding="utf-8")
    assert "require('yt-search')" in text
    assert "videoId" in text


def test_vrm_idle_pose_is_not_t_pose() -> None:
    page = (Path(__file__).resolve().parent.parent / "nekosuneai" / "static" / "vrm.html").read_text(encoding="utf-8")
    assert "function naturalArms" in page
    assert "1.18+sway" in page
    assert "-1.18-sway" in page
