"""Game driver contract.

A ``GameDriver`` is the only game-specific piece. The ``GameAgent`` brain talks
to it purely through this interface, so adding a new game (or a vision+keyboard
"any game" driver later) means implementing this Protocol without touching the
agent loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GameObservation:
    """A structured snapshot of the game world."""

    raw: dict[str, Any] = field(default_factory=dict)
    text: str = ""  # compact human/LLM-readable summary


@dataclass
class GameCommand:
    """A high-level action the agent wants to perform."""

    verb: str
    args: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GameDriver(Protocol):
    name: str

    def start(self) -> None:
        """Launch / connect the game (e.g. spawn the Node bridge, join server)."""

    def stop(self) -> None:
        """Disconnect and release resources."""

    def is_running(self) -> bool:
        ...

    def observe(self) -> GameObservation:
        """Return the current world state."""

    def describe_state(self) -> str:
        """Return a compact text description for the LLM and narration."""

    def act(self, command: GameCommand) -> dict[str, Any]:
        """Execute a high-level command and return an outcome dict."""

    def available_verbs(self) -> list[str]:
        """The high-level verbs this driver understands."""
