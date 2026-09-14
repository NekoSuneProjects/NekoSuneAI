"""Local music queue and transport controls.

Playback runs on this node rather than the backend because YouTube's
bot/cookie verification blocks a VPS's datacenter IP but not a home Pi's
residential one -- and because the speaker is here, not in the datacenter.
"""
from __future__ import annotations

import pytest

from nekosuneai.music import _SIGCONT, _SIGSTOP, MusicController

# SIGSTOP/SIGCONT do not exist on Windows. The controller reports pause as
# unsupported there rather than crashing, so the pause tests only mean
# anything on a POSIX host -- which is the deployment target anyway.
posix_signals = pytest.mark.skipif(
    _SIGSTOP is None or _SIGCONT is None,
    reason="SIGSTOP/SIGCONT are POSIX-only; pause is unsupported on this host",
)


class FakeProc:
    """Stands in for an ffplay subprocess."""

    def __init__(self, url):
        self.url = url
        self.pid = 4242
        self.signals = []
        self._done = False
        self.terminated = False

    def poll(self):
        return 0 if self._done else None

    def terminate(self):
        self.terminated = True
        self._done = True

    def wait(self, timeout=None):
        self._done = True
        return 0

    def kill(self):
        self._done = True

    def finish(self):
        """Simulate the track playing through to its end."""
        self._done = True


@pytest.fixture
def music(monkeypatch):
    """A controller whose resolve and playback are faked, queue logic real."""
    started: list[FakeProc] = []
    notes: list[str] = []
    controller = MusicController(notify=notes.append)

    monkeypatch.setattr("nekosuneai.music.shutil.which", lambda name: "/usr/bin/" + name)

    def fake_popen(args, **kwargs):
        proc = FakeProc(args[-1])
        started.append(proc)
        return proc

    monkeypatch.setattr("nekosuneai.music.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        controller, "_resolve",
        lambda query: ("http://stream/" + query.replace(" ", "+"), "Title: " + query),
    )
    # Auto-advance is driven explicitly in tests; a real thread would race them.
    monkeypatch.setattr(controller, "_ensure_watcher", lambda: None)
    monkeypatch.setattr("nekosuneai.music.os.kill", lambda pid, sig: started[-1].signals.append(sig))

    controller.started = started
    controller.notes = notes
    return controller


def test_play_resolves_and_starts_the_stream(music):
    result = music.play(["lofi hip hop"])

    assert result["playing"] is True
    assert result["title"] == "Title: lofi hip hop"
    assert music.started[-1].url == "http://stream/lofi+hip+hop"


def test_play_accepts_a_whole_playlist_and_queues_the_rest(music):
    """The backend hands over a playlist in one command so the gap between
    tracks is a local resolve, not a network round trip."""
    result = music.play(["one", "two", "three"])

    assert result["queued"] == 2
    assert len(music.started) == 1          # only the first track starts now
    assert music.status()["title"] == "Title: one"


def test_queue_flag_appends_instead_of_replacing(music):
    music.play(["one"])
    music.play(["two"], replace=False)

    assert len(music.started) == 1          # still playing the first
    assert music.status()["queued"] == 1


def test_finished_track_advances_the_queue(music):
    music.play(["one", "two"])
    music.started[-1].finish()

    music._watch_once()

    assert music.started[-1].url == "http://stream/two"
    assert music.status()["title"] == "Title: two"


def test_unplayable_track_is_skipped_not_fatal(music, monkeypatch):
    def flaky(query):
        if query == "bad":
            raise RuntimeError("blocked")
        return ("http://stream/" + query, "Title: " + query)

    monkeypatch.setattr(music, "_resolve", flaky)

    result = music.play(["bad", "good"])

    assert result["title"] == "Title: good"
    assert any("Skipping" in note for note in music.notes)


@posix_signals
def test_pause_and_resume_stop_and_restart_the_reader(music):
    music.play(["one"])

    assert music.pause()["paused"] is True
    assert music.started[-1].signals == [_SIGSTOP]
    assert music.is_playing() is False
    assert music.status()["paused"] is True

    assert music.resume()["paused"] is False
    assert music.started[-1].signals == [_SIGSTOP, _SIGCONT]
    assert music.is_playing() is True


def test_pause_with_nothing_playing_is_reported_not_raised(music):
    assert music.pause()["ok"] is False
    assert music.resume()["ok"] is False


def test_skip_moves_to_the_next_track(music):
    music.play(["one", "two"])
    first = music.started[-1]

    result = music.skip()

    assert first.terminated
    assert result["title"] == "Title: two"


def test_skip_on_the_last_track_stops(music):
    music.play(["only"])

    result = music.skip()

    assert "last track" in result["message"]
    assert music.status()["playing"] is False


def test_previous_returns_to_the_track_before(music):
    music.play(["one", "two"])
    music.skip()

    result = music.previous()

    assert result["title"] == "Title: one"
    assert music.started[-1].url == "http://stream/one"


def test_previous_with_no_history_is_reported(music):
    music.play(["one"])
    assert music.previous()["ok"] is False


def test_stop_clears_the_queue(music):
    music.play(["one", "two", "three"])

    music.stop()

    status = music.status()
    assert status["playing"] is False
    assert status["queued"] == 0
    assert status["title"] == ""


@posix_signals
def test_stopping_a_paused_track_does_not_hang(music):
    """terminate() on a SIGSTOPped process is not acted on until it runs
    again, so it has to be woken first."""
    music.play(["one"])
    music.pause()
    proc = music.started[-1]

    music.stop()

    assert _SIGCONT in proc.signals
    assert proc.terminated


def test_volume_goes_through_pactl(music, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr("nekosuneai.music.subprocess.run", fake_run)

    assert music.set_volume(60)["volume"] == 60
    assert calls[-1] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "60%"]
    # clamped, never negative or past 100
    assert music.set_volume(500)["volume"] == 100
    assert music.set_volume(-20)["volume"] == 0


def test_play_requires_something_to_play(music):
    with pytest.raises(ValueError):
        music.play([])
    with pytest.raises(ValueError):
        music.play(["", "   "])


def test_missing_ffplay_is_reported(music, monkeypatch):
    monkeypatch.setattr("nekosuneai.music.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffplay"):
        music.play(["one"])
