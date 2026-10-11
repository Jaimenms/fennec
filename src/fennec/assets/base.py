"""
Common interface of everything that exchanges energy with the house.

An asset is a plain Python object describing a device (its parameters and time series). When the
house model is built, ``Asset.build`` adds a Pyomo block to the model exposing, for every step ``t``:

* ``energy_from[t]``: kWh the device injects into the house (production, discharge, grid import);
* ``energy_to[t]``: kWh the device absorbs from the house (consumption, charge, grid export);
* ``cost[t]``: contribution to the objective (currency, or penalties).

A block may also expose a scalar ``terminal_cost``: a one-off term added to the objective for the state
the device is left in at the end of the horizon (a battery credits the energy it still holds).

The house only needs those three things to write the energy balance and the objective, so adding a new
kind of device (a heat pump, a water heater, an air conditioner...) is a matter of writing a new
``Asset`` subclass. Devices whose behaviour depends on the brand delegate that behaviour to a
controller object (see ``fennec.controllers``).
"""

from __future__ import annotations

import keyword
from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Optional

import pyomo.environ as pyo

from ..horizon import Horizon
from ..results import values  # noqa: F401  (re-exported for assets and controllers)

RESERVED_NAMES = {"t", "balance", "objective", "grid", "assets"}


class BuildContext:
    """What an asset can see while it is being added to the model."""

    def __init__(self, model: pyo.ConcreteModel, horizon: Horizon):
        self.model = model
        self.horizon = horizon
        self.grid: Optional[pyo.Block] = None  # set once the grid block exists

    @property
    def t(self) -> pyo.RangeSet:
        return self.model.t

    def require_grid(self, who: str) -> pyo.Block:
        if self.grid is None:
            raise ValueError(f"{who} needs the grid block to be built first")
        return self.grid


class Asset(ABC):
    """Base class of every device. Subclasses are dataclasses with at least a ``name`` field."""

    kind: ClassVar[str] = "asset"
    name: str

    # ------------------------------------------------------------------ validation

    def validate(self, horizon: Horizon) -> None:
        """Raise ``ValueError`` when the asset cannot be built for the given horizon."""
        if not isinstance(self.name, str) or not self.name.isidentifier() or keyword.iskeyword(self.name):
            raise ValueError(f"asset name {self.name!r} must be a valid Python identifier")
        if self.name in RESERVED_NAMES and self.kind != "grid":
            raise ValueError(f"asset name {self.name!r} is reserved")

    @staticmethod
    def _check_series(name: str, values, horizon: Horizon) -> None:
        if len(values) != horizon.steps:
            raise ValueError(f"{name}: expected {horizon.steps} values, got {len(values)}")

    # ------------------------------------------------------------------ model building

    @abstractmethod
    def build(self, ctx: BuildContext) -> pyo.Block:
        """Add this asset's block to ``ctx.model`` and return it."""

    def new_block(self, ctx: BuildContext) -> pyo.Block:
        block = pyo.Block()
        ctx.model.add_component(self.name, block)
        return block

    @staticmethod
    def zero_cost(block: pyo.Block, ctx: BuildContext) -> None:
        block.cost = pyo.Expression(ctx.t, rule=lambda b, t: 0.0)

    # ------------------------------------------------------------------ results

    def extract(self, block: pyo.Block, horizon: Horizon) -> Dict[str, List[Optional[float]]]:
        """Columns to report for this asset after a solve."""
        return {
            "energy_from": values(block.energy_from, horizon),
            "energy_to": values(block.energy_to, horizon),
            "cost": values(block.cost, horizon),
        }
