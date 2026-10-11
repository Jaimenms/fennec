"""
Battery controllers: what the optimizer is allowed to do with a battery.

The physics (SOC dynamics, limits, efficiencies) lives in ``fennec.assets.Battery``. A controller adds
the behaviour of a specific inverter / brand on top of it: operating modes, which setpoints exist, how
many commands can be sent, and the cost of sending them. It must leave ``block.cost`` defined.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional

import pyomo.environ as pyo

from ..commands import Command
from ..horizon import Horizon
from ..results import Results

if TYPE_CHECKING:  # pragma: no cover
    from ..assets.base import BuildContext
    from ..assets.battery import Battery


class BatteryController(ABC):
    def validate(self, battery: "Battery", horizon: Horizon) -> None:
        """Raise ``ValueError`` when the controller cannot be applied to this battery / horizon."""

    @abstractmethod
    def build(self, block: pyo.Block, battery: "Battery", ctx: "BuildContext") -> None:
        """Add constraints and ``block.cost`` to the battery block."""

    def extract(self, block: pyo.Block, horizon: Horizon) -> Dict[str, List[Optional[float]]]:
        return {}

    def commands(self, results: Results, battery: "Battery") -> List[Command]:
        """Translate the solved plan of ``battery`` into device commands, in the brand's vocabulary."""
        return []

    def describe(self) -> str:
        return type(self).__name__
