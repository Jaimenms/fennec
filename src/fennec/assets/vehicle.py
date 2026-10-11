"""Electric vehicle charged at home while it is plugged in."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional, Sequence, Tuple

import pyomo.environ as pyo
from pyomo.environ import Binary, NonNegativeReals

from ..commands import Command, group_steps, step_span
from ..horizon import Horizon
from ..results import Results
from .base import Asset, BuildContext, values


@dataclass
class ElectricVehicle(Asset):
    """
    EV with a home charger (no vehicle-to-home).

    ``plugged[t]`` says whether the car is at home during step ``t``. While it is away its SOC is not
    tracked; when it comes back the SOC is given by ``soc_on_return[t]`` for the step ``t`` of the
    return. ``soc_target`` maps a step to a desired SOC at the start of that step; missing percentage
    points are penalised by ``target_penalty`` (soft constraint, so an impossible target does not make
    the problem infeasible).

    The charger is on/off at ``max_charge_kw`` unless ``modulated`` is set, in which case the power is
    continuous. Every change of the charger setpoint between consecutive steps is a command, limited by
    ``max_commands`` and penalised by ``command_penalty``.
    """

    kind: ClassVar[str] = "ev"

    name: str
    capacity_kwh: float
    max_charge_kw: float
    plugged: Sequence[bool]
    soc_initial: float = 50.0
    soc_on_return: Dict[int, float] = field(default_factory=dict)
    soc_target: Dict[int, float] = field(default_factory=dict)
    target_penalty: float = 0.5
    soc_min: float = 0.0
    soc_max: float = 100.0
    charge_efficiency: float = 0.95
    modulated: bool = False
    max_commands: int = 100
    command_penalty: float = 0.0
    initial_charge: Optional[float] = None  # charger setpoint in force before step 0 (0/1, or a fraction)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def daily_trip(
        horizon: Horizon, leave: str, back: str, soc_on_return: float
    ) -> Tuple[List[bool], Dict[int, float]]:
        """
        Availability for a car that leaves every day at ``leave`` and is back at ``back`` (``"HH:MM"``),
        returning the ``plugged`` series and the ``soc_on_return`` map to pass to the constructor.
        """
        away = horizon.within(leave, back)
        plugged = [not a for a in away]
        returns = {t: soc_on_return for t in horizon.index if plugged[t] and t > 0 and not plugged[t - 1]}
        return plugged, returns

    def charge_on_arrival(self, horizon: Horizon, max_energy: Optional[Sequence[float]] = None) -> List[float]:
        """
        kWh per step of a dumb charger that charges at full power whenever the car is plugged until it
        is full. Wrap it in a ``Load`` to get the reference cost of not optimizing the car.
        ``max_energy`` caps the charger per step, e.g. with the power left under the contracted power
        once the house load is served (a charger with dynamic load management).
        """
        limits = self.charge_limits(horizon)
        soc, energy = self.soc_initial, []
        for t in horizon.index:
            if t in self.soc_on_return:
                soc = self.soc_on_return[t]
            if not self.plugged[t]:
                energy.append(0.0)
                continue
            room = (self.soc_max - soc) / 100.0 * self.capacity_kwh / self.charge_efficiency
            cap = limits[t] if max_energy is None else min(limits[t], max(0.0, max_energy[t]))
            e = min(cap, max(0.0, room))
            energy.append(e)
            soc += 100.0 / self.capacity_kwh * self.charge_efficiency * e
        return energy

    def return_steps(self) -> List[int]:
        return [t for t in range(1, len(self.plugged)) if self.plugged[t] and not self.plugged[t - 1]]

    def charge_limits(self, horizon: Horizon) -> List[float]:
        """kWh the charger can deliver in each step."""
        return [horizon.energy(self.max_charge_kw, t) for t in horizon.index]

    def validate(self, horizon: Horizon) -> None:
        super().validate(horizon)
        self._check_series(f"{self.name}.plugged", self.plugged, horizon)
        if self.capacity_kwh <= 0 or self.max_charge_kw <= 0:
            raise ValueError(f"{self.name}: capacity and charge power must be positive")
        if not 0 < self.charge_efficiency <= 1:
            raise ValueError(f"{self.name}: charge efficiency must be in (0, 1]")
        if not 0 <= self.soc_min <= self.soc_initial <= self.soc_max <= 100:
            raise ValueError(f"{self.name}: need 0 <= soc_min <= soc_initial <= soc_max <= 100")
        missing = [t for t in self.return_steps() if t not in self.soc_on_return]
        if missing:
            raise ValueError(f"{self.name}: soc_on_return missing for return steps {missing}")
        for t, soc in self.soc_on_return.items():
            if t not in self.return_steps():
                raise ValueError(f"{self.name}: step {t} is not a return step (car was already plugged)")
            if not self.soc_min <= soc <= self.soc_max:
                raise ValueError(f"{self.name}.soc_on_return[{t}] outside the SOC window")
        for t in self.soc_target:
            if t not in horizon.index:
                raise ValueError(f"{self.name}.soc_target: step {t} outside the horizon")

    # ------------------------------------------------------------------ model

    def build(self, ctx: BuildContext) -> pyo.Block:
        h, t = ctx.horizon, ctx.t
        v = self.new_block(ctx)
        e_max = self.charge_limits(h)

        v.charge = pyo.Var(t, bounds=(0, 1), domain=Binary if not self.modulated else NonNegativeReals)
        v.energy_to = pyo.Var(t, bounds=lambda b, i: (0, e_max[i]), domain=NonNegativeReals)
        v.energy_from = pyo.Param(t, initialize=0.0)
        v.energy_to_const = pyo.Constraint(t, rule=lambda b, i: b.energy_to[i] == e_max[i] * b.charge[i])
        for i in h.index:
            if not self.plugged[i]:
                v.charge[i].fix(0)

        v.soc = pyo.Var(t, bounds=(self.soc_min, self.soc_max))
        v.soc_end = pyo.Expression(
            t, rule=lambda b, i: b.soc[i] + 100.0 / self.capacity_kwh * self.charge_efficiency * b.energy_to[i]
        )
        v.soc_end_max = pyo.Constraint(t, rule=lambda b, i: b.soc_end[i] <= self.soc_max)

        # SOC is only tracked while the car is at home; a return fixes it to the value given.
        if self.plugged[0]:
            v.soc_initial_const = pyo.Constraint(expr=v.soc[0] == self.soc_initial)

        def dynamics(b, i):
            if i == 0 or not self.plugged[i - 1]:
                return pyo.Constraint.Skip
            return b.soc[i] == b.soc_end[i - 1]

        v.soc_dynamics = pyo.Constraint(t, rule=dynamics)
        returns = self.soc_on_return
        if returns:
            v.soc_return_const = pyo.Constraint(list(returns), rule=lambda b, i: b.soc[i] == returns[i])

        # soft SOC targets
        targets = self.soc_target
        v.shortfall = pyo.Var(list(targets), domain=NonNegativeReals)
        v.shortfall_const = pyo.Constraint(list(targets), rule=lambda b, i: b.shortfall[i] >= targets[i] - b.soc[i])

        # commands: any change of the charger setpoint (including from the state in force before step 0)
        def previous(b, i):
            if i > 0:
                return b.charge[i - 1]
            return self.initial_charge  # None when unknown: the first step is free

        v.command = pyo.Var(t, domain=Binary)
        v.command_up = pyo.Constraint(
            t,
            rule=lambda b, i: (
                pyo.Constraint.Skip if previous(b, i) is None else b.command[i] >= b.charge[i] - previous(b, i)
            ),
        )
        v.command_down = pyo.Constraint(
            t,
            rule=lambda b, i: (
                pyo.Constraint.Skip if previous(b, i) is None else b.command[i] >= previous(b, i) - b.charge[i]
            ),
        )
        v.max_commands_const = pyo.Constraint(expr=sum(v.command[i] for i in h.index) <= self.max_commands)

        v.cost = pyo.Expression(
            t,
            rule=lambda b, i: self.command_penalty * b.command[i]
            + (self.target_penalty * b.shortfall[i] if i in targets else 0.0),
        )
        return v

    def commands(self, results: Results) -> List[Command]:
        """``charge`` commands while the car is plugged: ``on`` for an on/off charger, ``power_kw`` when modulated."""
        h = results.horizon
        charge = results.column(self.name, "charge")

        def key(t):
            if not self.plugged[t]:
                return None
            fraction = charge[t] or 0.0
            return round(fraction * self.max_charge_kw, 2) if self.modulated else (fraction > 0.5)

        def make(first, last, k):
            at, until = step_span(h, first, last)
            params = {"power_kw": k} if self.modulated else {"on": bool(k)}
            return Command(self.name, "charge", at, until, params)

        return group_steps(h, key, make)

    def extract(self, block: pyo.Block, horizon: Horizon) -> Dict[str, List[Optional[float]]]:
        cols = super().extract(block, horizon)
        # the SOC is known while the car is at home and at the step it leaves (SOC at departure)
        soc = values(block.soc, horizon)
        tracked = [self.plugged[i] or (i > 0 and self.plugged[i - 1]) for i in horizon.index]
        cols["soc"] = [s if tracked[i] else None for i, s in enumerate(soc)]
        cols["plugged"] = [1.0 if p else 0.0 for p in self.plugged]
        cols["charge"] = values(block.charge, horizon)
        cols["command"] = values(block.command, horizon)
        return cols
