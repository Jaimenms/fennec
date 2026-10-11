"""The house: a grid connection plus any number of assets, balanced at every step."""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence

import pyomo.environ as pyo

from .assets.base import Asset, BuildContext
from .assets.grid import Grid
from .horizon import Horizon
from .results import Results


class SmartHome:
    """
    Minimises the total cost over the horizon subject to the energy balance

        sum(asset.energy_from[t]) == sum(asset.energy_to[t])   for every step t

    where the grid is just another asset. Build with ``build()`` (to inspect the Pyomo model) or go
    straight to ``solve()``.
    """

    def __init__(self, horizon: Horizon, grid: Grid, assets: Sequence[Asset] = ()):
        self.horizon = horizon
        self.grid = grid
        self.assets: List[Asset] = list(assets)
        self.model: Optional[pyo.ConcreteModel] = None
        self.blocks: Dict[str, pyo.Block] = {}
        self._validate()

    # ------------------------------------------------------------------ validation

    def _validate(self) -> None:
        names = [self.grid.name] + [a.name for a in self.assets]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate asset names: {sorted(duplicates)}")
        self.grid.validate(self.horizon)
        for asset in self.assets:
            asset.validate(self.horizon)

    @property
    def all_assets(self) -> List[Asset]:
        return [self.grid] + self.assets

    # ------------------------------------------------------------------ build

    def build(self) -> pyo.ConcreteModel:
        m = pyo.ConcreteModel(name="SmartHome")
        m.t = pyo.RangeSet(0, self.horizon.steps - 1)
        ctx = BuildContext(m, self.horizon)

        self.blocks = {self.grid.name: self.grid.build(ctx)}
        for asset in self.assets:
            self.blocks[asset.name] = asset.build(ctx)

        blocks = list(self.blocks.values())
        m.balance = pyo.Constraint(
            m.t, rule=lambda mm, t: sum(b.energy_from[t] for b in blocks) == sum(b.energy_to[t] for b in blocks)
        )
        running = sum(b.cost[t] for b in blocks for t in m.t)
        terminal = sum(b.terminal_cost for b in blocks if hasattr(b, "terminal_cost"))
        m.objective = pyo.Objective(expr=running + terminal, sense=pyo.minimize)
        self.model = m
        return m

    # ------------------------------------------------------------------ solve

    def warm_start_from(self, previous: "SmartHome") -> int:
        """
        Use the solution of a previously solved house (typically the same house one period earlier) as
        the starting point of the next solve: every variable takes the value it had at the step of the
        previous horizon that contains the same instant. Returns the number of values set. Pass
        ``warm_start=True`` to ``solve()`` afterwards.
        """
        if self.model is None:
            self.build()
        if previous.model is None:
            return 0
        assert self.model is not None
        mapping = {t: previous.horizon.step_at(ts) for t, ts in enumerate(self.horizon.timestamps)}
        count = 0
        for var in self.model.component_objects(pyo.Var, active=True):
            source = previous.model.find_component(var.name)
            if source is None:
                continue
            if not var.is_indexed():
                if source.value is not None:
                    var.value = source.value
                    count += 1
                continue
            for idx in var:
                t = idx if isinstance(idx, int) else None
                if t is None or mapping.get(t) is None or mapping[t] not in source:
                    continue
                value = source[mapping[t]].value
                if value is None:
                    continue
                target = var[idx]
                if target.is_binary():
                    value = round(value)
                else:  # steps of different lengths: keep the value inside the new bounds
                    lb, ub = target.lb, target.ub
                    value = max(lb, value) if lb is not None else value
                    value = min(ub, value) if ub is not None else value
                target.value = value
                count += 1
        return count

    def solve(
        self,
        time_limit: float = 60.0,
        mip_rel_gap: float = 1e-3,
        mip_abs_gap: float = 1e-4,
        threads: Optional[int] = None,
        tee: bool = False,
        warm_start: bool = False,
    ) -> Results:
        """
        Solve with HiGHS and return the ``Results``. A time limit returns the best plan found. With
        ``warm_start`` the current variable values (see ``warm_start_from``) are given to HiGHS as a MIP
        start.
        """
        from pyomo.contrib.appsi.base import TerminationCondition as TC
        from pyomo.contrib.appsi.solvers.highs import Highs

        if self.model is None:
            self.build()
        assert self.model is not None

        opt = Highs()
        if not opt.available():
            raise RuntimeError("HiGHS is not available: install the 'highspy' package")
        opt.config.time_limit = time_limit
        opt.config.load_solution = False
        opt.config.stream_solver = tee
        opt.config.warmstart = warm_start
        options = {"mip_rel_gap": mip_rel_gap, "mip_abs_gap": mip_abs_gap}
        if threads is not None:
            options["threads"] = threads
        opt.highs_options = options

        start = time.perf_counter()
        res = opt.solve(self.model)
        elapsed = time.perf_counter() - start

        objective = res.best_feasible_objective
        if objective is not None:
            opt.load_vars()

        status = {
            TC.optimal: "optimal",
            TC.maxTimeLimit: "time_limit",
            TC.infeasible: "infeasible",
            TC.unbounded: "unbounded",
            TC.infeasibleOrUnbounded: "infeasible_or_unbounded",
        }.get(res.termination_condition, str(res.termination_condition.name))

        return self.collect(status, objective, res.best_objective_bound, elapsed)

    def collect(self, status: str, objective: Optional[float], bound: Optional[float], elapsed: float) -> Results:
        results = Results(
            horizon=self.horizon,
            status=status,
            objective=objective,
            bound=bound,
            solve_seconds=elapsed,
            kinds={a.name: a.kind for a in self.all_assets},
        )
        if objective is not None:
            for asset in self.all_assets:
                block = self.blocks[asset.name]
                results.data[asset.name] = asset.extract(block, self.horizon)
                if hasattr(block, "terminal_cost"):
                    results.terminal[asset.name] = float(pyo.value(block.terminal_cost))
        results.notes["capacity"] = {a.name: a.capacity_kwh for a in self.assets if hasattr(a, "capacity_kwh")}
        results.notes["terminal_price"] = {
            name: float(pyo.value(block.terminal_price))
            for name, block in self.blocks.items()
            if hasattr(block, "terminal_price")
        }
        results.notes["controllers"] = {
            a.name: a.controller.describe() for a in self.assets if hasattr(a, "controller")
        }
        return results

    # ------------------------------------------------------------------ introspection

    def statistics(self) -> Dict[str, int]:
        """Number of variables (binary / continuous) and constraints of the built model."""
        if self.model is None:
            self.build()
        assert self.model is not None
        binaries = continuous = 0
        for v in self.model.component_data_objects(pyo.Var, active=True):
            if v.fixed:
                continue
            if v.is_binary():
                binaries += 1
            else:
                continuous += 1
        constraints = sum(1 for _ in self.model.component_data_objects(pyo.Constraint, active=True))
        return {"binaries": binaries, "continuous": continuous, "constraints": constraints}
