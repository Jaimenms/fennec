"""
Commands: what a plan asks a device to do, expressed in the device's own vocabulary.

The optimizer produces energies per step; a command is the translation of a run of consecutive steps into
one instruction the equipment understands ("self-consumption mode", "force charge at 3 kW for 45 minutes",
"charger on"). Fennec never talks to equipment: commands are handed to an external connector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Hashable, Iterable, List, Optional, Sequence, Tuple

from .horizon import Horizon


@dataclass(frozen=True)
class Command:
    device: str  # asset name
    action: str  # device-specific verb, e.g. "set_mode", "force_charge", "charge", "release"
    at: datetime  # when it applies
    until: datetime  # end of the run of steps it covers
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def minutes(self) -> float:
        return (self.until - self.at).total_seconds() / 60.0

    def same_intent(self, other: Optional["Command"]) -> bool:
        """True when both commands ask for the same thing (ignoring when and for how long)."""
        return (
            other is not None
            and self.device == other.device
            and self.action == other.action
            and self.params == other.params
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device": self.device,
            "action": self.action,
            "at": self.at.isoformat(),
            "until": self.until.isoformat(),
            "minutes": round(self.minutes, 1),
            **self.params,
        }


def group_steps(
    horizon: Horizon,
    key: Callable[[int], Optional[Hashable]],
    make: Callable[[int, int, Hashable], Command],
) -> List[Command]:
    """
    Turn a per-step signal into commands: consecutive steps with the same ``key`` become one command
    built by ``make(first_step, last_step, key)``. Steps whose key is None produce nothing.
    """
    commands: List[Command] = []
    current: Optional[Tuple[int, Hashable]] = None
    last = -1
    for t in horizon.index:
        k = key(t)
        if current is not None and (k is None or k != current[1]):
            commands.append(make(current[0], last, current[1]))
            current = None
        if k is not None and current is None:
            current = (t, k)
        if k is not None:
            last = t
    if current is not None:
        commands.append(make(current[0], last, current[1]))
    return commands


def step_span(horizon: Horizon, first: int, last: int) -> Tuple[datetime, datetime]:
    return horizon.at(first), horizon.at(last) + horizon.durations[last]
