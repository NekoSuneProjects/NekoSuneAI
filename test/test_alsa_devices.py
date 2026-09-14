"""Capture-device resolution -- the fix for command capture opening the wrong
microphone. See nekosuneai/alsa_devices.py's module docstring."""
from __future__ import annotations

import pytest

from nekosuneai import alsa_devices

# A Raspberry Pi with onboard audio, a generic USB mic and a Kinect array --
# exactly the ambiguous case where picking the ALSA default was wrong.
ARECORD_L = """**** List of CAPTURE Hardware Devices ****
card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]
  Subdevices: 8/8
card 1: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
card 2: Audio [Xbox NUI Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
"""


@pytest.fixture
def arecord(monkeypatch):
    """Pretend `arecord -l` is present and returns `listing`."""

    def _install(listing: str = ARECORD_L) -> None:
        monkeypatch.setattr(alsa_devices.shutil, "which", lambda name: "/usr/bin/" + name)
        monkeypatch.setattr(
            alsa_devices.subprocess, "run",
            lambda *a, **k: type("R", (), {"stdout": listing, "returncode": 0})(),
        )

    return _install


def test_lists_capture_devices_as_plughw(arecord):
    arecord()
    devices = alsa_devices.alsa_capture_devices()
    assert [item["alsa_device"] for item in devices] == ["plughw:0,0", "plughw:1,0", "plughw:2,0"]
    # plughw, never hw: the Kinect array is 4-channel and will not open as the
    # mono 16 kHz stream the backend's STT endpoint requires without ALSA's
    # conversion plugin in front of it.
    assert all(item["alsa_device"].startswith("plughw:") for item in devices)
    assert [item["is_kinect"] for item in devices] == [False, False, True]


def test_explicit_config_wins_over_every_guess(arecord):
    arecord()
    assert alsa_devices.resolve_capture_device(
        alsa_device="plughw:9,9", portaudio_name="USB Audio (hw:1,0)",
    ) == "plughw:9,9"


def test_address_embedded_in_portaudio_name_is_used_directly(arecord):
    arecord()
    assert alsa_devices.resolve_capture_device(
        portaudio_name="USB Audio Device: - (hw:1,0)",
    ) == "plughw:1,0"


@pytest.mark.parametrize(
    ("portaudio_name", "expected"),
    [("Xbox NUI Audio", "plughw:2,0"), ("USB PnP Sound Device", "plughw:1,0")],
)
def test_name_without_address_matches_arecord_listing(arecord, portaudio_name, expected):
    arecord()
    assert alsa_devices.resolve_capture_device(portaudio_name=portaudio_name) == expected


def test_kinect_preference_only_applies_when_nothing_else_matched(arecord):
    arecord()
    assert alsa_devices.resolve_capture_device(portaudio_name="", prefer_kinect=True) == "plughw:2,0"


def test_ambiguous_listing_refuses_to_guess(arecord):
    """Returning "" means the caller omits -D and keeps the old behaviour.

    Guessing between several capture cards would reintroduce exactly the
    wrong-microphone bug this module exists to fix.
    """
    arecord()
    assert alsa_devices.resolve_capture_device(portaudio_name="") == ""


def test_single_capture_card_is_unambiguous(arecord):
    arecord("card 1: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]\n")
    assert alsa_devices.resolve_capture_device(portaudio_name="") == "plughw:1,0"


def test_missing_arecord_degrades_instead_of_raising(monkeypatch):
    monkeypatch.setattr(alsa_devices.shutil, "which", lambda name: None)
    assert alsa_devices.alsa_capture_devices() == []
    assert alsa_devices.resolve_capture_device(portaudio_name="anything") == ""
