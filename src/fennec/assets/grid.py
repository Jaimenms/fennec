"""Connection to the distribution grid."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional

import pyomo.environ as pyo
from pyomo.environ import Binary, NonNegativeReals

from ..horizon import Horizon
from ..tariffs import Tariff
from .base import Asset, BuildContext, values


@dataclass
class Grid(Asset):
    """
    Grid connection with time-of-use import and export tariffs.

    ``energy_from`` is energy imported (bought) and ``energy_to`` energy exported (sold). Import is
    limited by the contracted power and export by ``export_power_kw`` (default: the contracted power).

    ``settled`` forbids importing and exporting in the same step with a binary per step. When it is
    ``None`` the binary is only added if some step has an export price at least as high as the import
    price, which is the only situation where simultaneous import and export could pay off.
    """

    kind: ClassVar[str] = "grid"

    import_tariff: Tariff
    export_tariff: Tariff = field(default_factory=Tariff.none)
    contracted_power_kw: float = 6.9
    export_power_kw: Optional[float] = None
    settled: Optional[bool] = None
    name: str = "grid"

    def validate(self, horizon: Horizon) -> None:
        super().validate(horizon)
        if self.contracted_power_kw <= 0:
            raise ValueError("Grid.contracted_power_kw must be positive")

    def needs_settling(self, horizon: Horizon) -> bool:
        if self.settled is not None:
            return self.settled
        buy, sell = self.import_tariff.series(horizon), self.export_tariff.series(horizon)
        return any(s >= b for b, s in zip(buy, sell))

    def build(self, ctx: BuildContext) -> pyo.Block:
        h = ctx.horizon
        g = self.new_block(ctx)

        export_kw = self.export_power_kw if self.export_power_kw is not None else self.contracted_power_kw
        import_limit = [h.energy(self.contracted_power_kw, t) for t in h.index]
        export_limit = [h.energy(export_kw, t) for t in h.index]

        g.import_price = pyo.Param(ctx.t, initialize=dict(enumerate(self.import_tariff.series(h))))
        g.export_price = pyo.Param(ctx.t, initialize=dict(enumerate(self.export_tariff.series(h))))

        g.energy_from = pyo.Var(ctx.t, bounds=lambda b, t: (0, import_limit[t]), domain=NonNegativeReals)
        g.energy_to = pyo.Var(ctx.t, bounds=lambda b, t: (0, export_limit[t]), domain=NonNegativeReals)

        if self.needs_settling(h):
            g.importing = pyo.Var(ctx.t, domain=Binary)
            g.settle_import = pyo.Constraint(
                ctx.t, rule=lambda b, t: b.energy_from[t] <= import_limit[t] * b.importing[t]
            )
            g.settle_export = pyo.Constraint(
                ctx.t, rule=lambda b, t: b.energy_to[t] <= export_limit[t] * (1 - b.importing[t])
            )

        g.cost = pyo.Expression(
            ctx.t, rule=lambda b, t: b.import_price[t] * b.energy_from[t] - b.export_price[t] * b.energy_to[t]
        )
        ctx.grid = g
        return g

    def extract(self, block: pyo.Block, horizon: Horizon) -> Dict[str, List[Optional[float]]]:
        cols = super().extract(block, horizon)
        cols["import_price"] = values(block.import_price, horizon)
        cols["export_price"] = values(block.export_price, horizon)
        return cols
