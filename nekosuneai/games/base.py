"""The contract every game integration implements.

Game-specific knowledge is confined to a driver. ``GameAgent`` reasons only
against the Protocol declared here, so supporting another title - or a generic
vision-plus-keyboard driver that plays anything on screen - is a matter of
satisfying this interface rather than editing the agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = ["GameObservation", "GameCommand", "GameDriver"]


@dataclass
class GameObservation:
    """One sampled view of the world.

    ``raw`` carries whatever the driver natively reports; ``text`` is the
    condensed rendering handed to the language model and to narration.
    """

    raw: dict[str, Any] = field(default_factory=dict)
    text: str = ""


@dataclass
class GameCommand:
    """An intent the agent wants carried out, named by ``verb``."""

    verb: str
    args: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GameDriver(Protocol):
    """Lifecycle, observation and actuation for a single game."""

    name: str

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Bring the game up: spawn a bridge process, attach, join a server."""
        ...

    def stop(self) -> None:
        """Tear the session down and free anything it holds."""
        ...

    def is_running(self) -> bool:
        """Whether the game is currently attached and usable."""
        ...

    # -- observation -------------------------------------------------------

    def observe(self) -> GameObservation:
        """Sample the world as it stands right now."""
        ...

    def describe_state(self) -> str:
        """Summarise the world in prose short enough to prompt with."""
        ...

    # -- actuation ---------------------------------------------------------

    def act(self, command: GameCommand) -> dict[str, Any]:
        """Carry out ``command`` and report the outcome."""
        ...

    def available_verbs(self) -> list[str]:
        """Every verb :meth:`act` accepts on this driver."""
        ...
