"""Stationary battery: the physics is shared, the behaviour comes from a controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional, Union

import pyomo.environ as pyo
from pyomo.environ import Binary, NonNegativeReals

from ..controllers.base import BatteryController
from ..controllers.ideal import IdealController
from ..horizon import Horizon
from .base import Asset, BuildContext, values

MIN_IMPORT_PRICE = "min_import_price"
MEAN_IMPORT_PRICE = "mean_import_price"


@dataclass
class Battery(Asset):
    """
    Battery behind one inverter.

    Convention: ``soc[t]`` (%) is the state of charge at the START of step ``t``, the energies are
    exchanged DURING the step and ``soc_end[t]`` is the state of charge at its end. Both ends of every
    step stay inside ``[soc_min, soc_max]``. Charging and discharging never happen in the same step.

    The ``controller`` decides what the optimizer is allowed to do with the battery: an
    ``IdealController`` gives perfect freedom (a benchmark), a brand controller such as
    ``HuaweiLuna2000Controller`` reproduces the inverter's operating modes and the commands available.

    ``soc_required`` maps a step index to a minimum SOC at the start of that step (hard constraint) and
    ``soc_final_min`` is a minimum SOC at the end of the horizon.

    **End of horizon.** Left alone, an optimizer drains the battery before the end of the horizon
    because stored energy is worth nothing to it. ``terminal_value`` gives that energy a price: the
    objective receives ``-price * (usable kWh at the end - usable kWh at the start)``, so draining the
    battery is paid for and filling it is credited, and the objective of a plan that ends where it
    started is exactly its bill. ``usable kWh`` is what the battery can deliver to the house above
    ``soc_min``, i.e. after the discharge efficiency. The price may be a number (currency per kWh) or
    ``"min_import_price"`` (default: the cheapest import price of the horizon, which makes buying energy
    at that price to store it neutral and never rewards hoarding) or ``"mean_import_price"``. ``None``
    disables the valuation; combine it with ``soc_final_min`` for a hard reserve instead.
    """

    kind: ClassVar[str] = "battery"

    name: str
    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    soc_initial: float = 50.0
    soc_min: float = 0.0
    soc_max: float = 100.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    controller: BatteryController = field(default_factory=IdealController)
    soc_required: Dict[int, float] = field(default_factory=dict)
    soc_final_min: Optional[float] = None
    terminal_value: Union[float, str, None] = MIN_IMPORT_PRICE

    # ------------------------------------------------------------------ derived quantities

    def usable_kwh(self, soc) -> object:
        """kWh the battery can deliver to the house from a given SOC (Pyomo expression or number)."""
        return (soc - self.soc_min) / 100.0 * self.capacity_kwh * self.discharge_efficiency

    def terminal_price(self, ctx: BuildContext) -> Optional[float]:
        """Resolve ``terminal_value`` into a currency-per-kWh number (None when disabled)."""
        if self.terminal_value is None:
            return None
        if isinstance(self.terminal_value, str):
            grid = ctx.require_grid(f"{self.name}.terminal_value={self.terminal_value!r}")
            prices = [pyo.value(grid.import_price[t]) for t in ctx.horizon.index]
            return min(prices) if self.terminal_value == MIN_IMPORT_PRICE else sum(prices) / len(prices)
        return float(self.terminal_value)

    def charge_limits(self, horizon: Horizon) -> List[float]:
        """kWh that can be charged in each step."""
        return [horizon.energy(self.max_charge_kw, t) for t in horizon.index]

    def discharge_limits(self, horizon: Horizon) -> List[float]:
        return [horizon.energy(self.max_discharge_kw, t) for t in horizon.index]

    def validate(self, horizon: Horizon) -> None:
        super().validate(horizon)
        if self.capacity_kwh <= 0 or self.max_charge_kw <= 0 or self.max_discharge_kw <= 0:
            raise ValueError(f"{self.name}: capacity and power limits must be positive")
        if not 0 < self.charge_efficiency <= 1 or not 0 < self.discharge_efficiency <= 1:
            raise ValueError(f"{self.name}: efficiencies must be in (0, 1]")
        if not 0 <= self.soc_min <= self.soc_initial <= self.soc_max <= 100:
            raise ValueError(f"{self.name}: need 0 <= soc_min <= soc_initial <= soc_max <= 100")
        for t, soc in self.soc_required.items():
            if t not in horizon.index:
                raise ValueError(f"{self.name}.soc_required: step {t} outside the horizon")
            if not self.soc_min <= soc <= self.soc_max:
                raise ValueError(f"{self.name}.soc_required[{t}] outside the SOC window")
        if self.soc_final_min is not None and not self.soc_min <= self.soc_final_min <= self.soc_max:
            raise ValueError(f"{self.name}.soc_final_min outside the SOC window")
        if isinstance(self.terminal_value, str):
            if self.terminal_value not in (MIN_IMPORT_PRICE, MEAN_IMPORT_PRICE):
                raise ValueError(
                    f"{self.name}.terminal_value must be a price, None, {MIN_IMPORT_PRICE!r} or {MEAN_IMPORT_PRICE!r}"
                )
        elif self.terminal_value is not None and self.terminal_value < 0:
            raise ValueError(f"{self.name}.terminal_value must be non-negative")
        self.controller.validate(self, horizon)

    # ------------------------------------------------------------------ model

    def build(self, ctx: BuildContext) -> pyo.Block:
        h, t = ctx.horizon, ctx.t
        b = self.new_block(ctx)
        e_to, e_from = self.charge_limits(h), self.discharge_limits(h)

        b.energy_to = pyo.Var(t, bounds=lambda blk, i: (0, e_to[i]), domain=NonNegativeReals)
        b.energy_from = pyo.Var(t, bounds=lambda blk, i: (0, e_from[i]), domain=NonNegativeReals)
        b.soc = pyo.Var(t, bounds=(self.soc_min, self.soc_max))

        b.soc_end = pyo.Expression(
            t,
            rule=lambda blk, i: blk.soc[i]
            + 100.0
            / self.capacity_kwh
            * (self.charge_efficiency * blk.energy_to[i] - blk.energy_from[i] / self.discharge_efficiency),
        )

        # no simultaneous charge and discharge
        b.charging = pyo.Var(t, domain=Binary)
        b.charge_only = pyo.Constraint(t, rule=lambda blk, i: blk.energy_to[i] <= e_to[i] * blk.charging[i])
        b.discharge_only = pyo.Constraint(
            t, rule=lambda blk, i: blk.energy_from[i] <= e_from[i] * (1 - blk.charging[i])
        )

        # SOC dynamics and window
        b.soc_initial_const = pyo.Constraint(expr=b.soc[0] == self.soc_initial)
        b.soc_dynamics = pyo.Constraint(
            t, rule=lambda blk, i: pyo.Constraint.Skip if i == 0 else blk.soc[i] == blk.soc_end[i - 1]
        )
        b.soc_end_min = pyo.Constraint(t, rule=lambda blk, i: blk.soc_end[i] >= self.soc_min)
        b.soc_end_max = pyo.Constraint(t, rule=lambda blk, i: blk.soc_end[i] <= self.soc_max)

        if self.soc_required:
            b.soc_required_const = pyo.Constraint(
                list(self.soc_required), rule=lambda blk, i: blk.soc[i] >= self.soc_required[i]
            )
        if self.soc_final_min is not None:
            b.soc_final_const = pyo.Constraint(expr=b.soc_end[h.last_step()] >= self.soc_final_min)

        # value of the energy left at the end of the horizon, relative to the start (a credit is negative)
        price = self.terminal_price(ctx)
        if price is not None:
            b.terminal_price = pyo.Param(initialize=price)
            b.terminal_cost = pyo.Expression(
                expr=-price * (self.usable_kwh(b.soc_end[h.last_step()]) - self.usable_kwh(self.soc_initial))
            )

        # behaviour and cost come from the controller
        self.controller.build(b, self, ctx)
        if not hasattr(b, "cost"):
            self.zero_cost(b, ctx)
        return b

    def extract(self, block: pyo.Block, horizon: Horizon) -> Dict[str, List[Optional[float]]]:
        cols = super().extract(block, horizon)
        cols["soc"] = values(block.soc, horizon)
        cols["soc_end"] = values(block.soc_end, horizon)
        cols.update(self.controller.extract(block, horizon))
        return cols
