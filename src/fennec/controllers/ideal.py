"""Perfect control: the optimizer sets the battery power freely at every step."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List

import pyomo.environ as pyo

from ..commands import Command, group_steps, step_span
from ..results import Results
from .base import BatteryController

if TYPE_CHECKING:  # pragma: no cover
    from ..assets.base import BuildContext
    from ..assets.battery import Battery


@dataclass
class IdealController(BatteryController):
    """
    No operating modes, no command limits, no cost. The result is a lower bound on what any real
    inverter can achieve, useful to measure how much a brand's restrictions cost.
    """

    def build(self, block: pyo.Block, battery: "Battery", ctx: "BuildContext") -> None:
        block.cost = pyo.Expression(ctx.t, rule=lambda b, t: 0.0)

    def commands(self, results: Results, battery: "Battery") -> List[Command]:
        """``set_power`` with the signed battery power in kW (positive charges), one per run of equal power."""
        h = results.horizon
        to, frm = results.column(battery.name, "energy_to"), results.column(battery.name, "energy_from")

        def key(t):
            return round(((to[t] or 0.0) - (frm[t] or 0.0)) / h.hours_at(t), 2)

        def make(first, last, power):
            at, until = step_span(h, first, last)
            return Command(battery.name, "set_power", at, until, {"power_kw": power})

        return group_steps(h, key, make)

    def describe(self) -> str:
        return "ideal (free dispatch)"
