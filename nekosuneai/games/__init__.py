"""NekoSuneAI game-playing subsystem.

A pluggable layer that lets NekoSuneAI autonomously play games and narrate
what it is doing. The LLM brain (``GameAgent``) is game-agnostic; each game
provides a ``GameDriver`` that knows how to observe and act. VRChat (via its
official OSC API) is the only driver implemented.
"""
from .base import GameCommand, GameDriver, GameObservation

__all__ = ["GameCommand", "GameDriver", "GameObservation"]
