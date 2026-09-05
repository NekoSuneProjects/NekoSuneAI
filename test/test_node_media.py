import base64
from unittest.mock import Mock

import pytest

from nekosuneai.node_media_client import NodeMediaClient
from nekosuneai.vrchat_osc import VrchatOsc


def test_cancelled_synthesis_cannot_play():
    client = NodeMediaClient({})
    client.audio = Mock()
    def request(*args, **kwargs):
        client.cancel_audio()
        return {"audio_base64": base64.b64encode(b"audio").decode()}
    client.request = request
    with pytest.raises(RuntimeError, match="cancelled"):
        client.speak("hello")
    client.audio.play.assert_not_called()
    assert not client.speech_pending.is_set()


def test_stopped_client_rejects_network():
    client = NodeMediaClient({})
    client.close()
    with pytest.raises(RuntimeError, match="stopped"):
        client.request("tts", text="hello")


def test_vision_retains_capture_age_and_clears_missing_frame():
    client = NodeMediaClient({})
    client.request = Mock(return_value={"description": "menu"})
    client.vision({"ok": True, "screenshot_jpeg_base64": "abc", "epoch": 123})
    assert client.snapshot()["vision_epoch"] == 123
    with pytest.raises(RuntimeError):
        client.vision({"ok": False})
    assert client.snapshot()["description"] == ""


def test_cancelled_transcription_is_not_published():
    client = NodeMediaClient({"audio_input_device": 1})
    client.audio = Mock()
    client.audio.capture.return_value = b"wav"
    def request(*args, **kwargs):
        client.cancel_audio()
        return {"text": "late result"}
    client.request = request
    with pytest.raises(RuntimeError, match="cancelled"):
        client.listen()
    assert client.snapshot()["transcript"] == ""


def test_osc_requires_local_arm_and_releases_axis():
    transport = Mock()
    osc = VrchatOsc(client=transport)
    with pytest.raises(PermissionError):
        osc.pulse("Vertical", 1, .02)
    osc.arm()
    osc.pulse("Vertical", 1, .02)
    assert transport.send_message.call_args_list[0].args == ("/input/Vertical", 1.0)
    assert transport.send_message.call_args_list[-1].args == ("/input/Vertical", 0.0)
    osc.stop_input()
    with pytest.raises(PermissionError):
        osc.chatbox("hello")


@pytest.mark.parametrize("value,seconds", [(float("nan"), .1), (1, float("inf")), (2, .1), (1, 3)])
def test_osc_rejects_unbounded_inputs(value, seconds):
    osc = VrchatOsc(client=Mock())
    osc.arm()
    with pytest.raises(ValueError):
        osc.pulse("Vertical", value, seconds)


def test_avatar_change_clears_old_parameters():
    osc = VrchatOsc(client=Mock())
    osc._receive("/avatar/parameters/Voice", .5)
    assert osc.status()["parameters"] == {"Voice": .5}
    osc._receive("/avatar/change", "avtr_test")
    assert osc.status()["parameters"] == {}
    assert osc.status()["avatar_id"] == "avtr_test"


def test_osc_receives_real_loopback_packet():
    import time
    from pythonosc.udp_client import SimpleUDPClient
    osc = VrchatOsc(receive_port=0, client=Mock())
    osc.start()
    try:
        sender = SimpleUDPClient("127.0.0.1", osc._server.server_address[1])
        sender.send_message("/avatar/parameters/Voice", .5)
        deadline = time.monotonic() + 2
        while not osc.status()["parameters"] and time.monotonic() < deadline:
            time.sleep(.01)
        assert osc.status()["parameters"] == {"Voice": .5}
    finally:
        osc.close()


@pytest.mark.parametrize("geometry", ["920x620", "1080x720"])
def test_media_pages_fit_and_scroll(geometry):
    from tools.windows_gaming_node_gui import App
    app = App()
    try:
        app.attributes("-alpha", 0)
        app.geometry(geometry)
        for page in ("media", "vrchat"):
            app._show_page(page)
            app.update()
            assert app.pages[page].winfo_width() <= app.page_canvas.winfo_width()
            app.page_canvas.yview_moveto(1)
            app.update()
            assert app.page_canvas.yview()[1] == 1.0
            def check(widget):
                for child in widget.winfo_children():
                    if child.winfo_ismapped():
                        assert child.winfo_x() >= 0
                        assert child.winfo_x() + child.winfo_width() <= widget.winfo_width() + 2
                        check(child)
            check(app.pages[page])
    finally:
        app.destroy()
