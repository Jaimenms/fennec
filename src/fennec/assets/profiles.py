"""Devices with a fixed, known energy profile: loads and PV production."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Dict, List, Optional, Sequence

import pyomo.environ as pyo

from ..horizon import Horizon
from .base import Asset, BuildContext, values


@dataclass
class FixedProfile(Asset):
    """kWh per step that the house must absorb (``direction="to"``) or receives (``direction="from"``)."""

    kind: ClassVar[str] = "profile"
    direction: ClassVar[str] = "to"

    name: str
    energy: Sequence[float]

    def validate(self, horizon: Horizon) -> None:
        super().validate(horizon)
        self._check_series(f"{self.name}.energy", self.energy, horizon)
        if any(e < 0 for e in self.energy):
            raise ValueError(f"{self.name}.energy must be non-negative")

    def build(self, ctx: BuildContext) -> pyo.Block:
        b = self.new_block(ctx)
        series = pyo.Param(ctx.t, initialize=dict(enumerate(self.energy)))
        zeros = pyo.Param(ctx.t, initialize=0.0)
        if self.direction == "to":
            b.energy_to, b.energy_from = series, zeros
        else:
            b.energy_from, b.energy_to = series, zeros
        self.zero_cost(b, ctx)
        return b

    def extract(self, block: pyo.Block, horizon: Horizon) -> Dict[str, List[Optional[float]]]:
        return {"energy": values(block.energy_to if self.direction == "to" else block.energy_from, horizon)}

    @property
    def total_kwh(self) -> float:
        return float(sum(self.energy))


@dataclass
class Load(FixedProfile):
    """Non-flexible household consumption."""

    kind: ClassVar[str] = "load"
    direction: ClassVar[str] = "to"


@dataclass
class PVProduction(FixedProfile):
    """Photovoltaic production (no curtailment)."""

    kind: ClassVar[str] = "pv"
    direction: ClassVar[str] = "from"
