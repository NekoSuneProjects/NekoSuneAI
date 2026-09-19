"""Autonomous game playing.

A pluggable layer that lets the assistant play a game on its own and narrate
what it is doing while it happens. The reasoning half, ``GameAgent``, knows
nothing about any particular title; each game supplies a ``GameDriver`` that
handles observing the world and acting on it. VRChat, driven through its
official OSC API, is the one driver shipped so far.
"""

from .base import GameCommand, GameDriver, GameObservation

__all__ = ["GameCommand", "GameDriver", "GameObservation"]
