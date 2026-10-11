"""What comes out of a solve: status, objective and one table of time series per asset."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pyomo.environ as pyo

from .horizon import Horizon

Columns = Dict[str, List[Optional[float]]]


@dataclass
class Results:
    horizon: Horizon
    status: str  # "optimal", "time_limit", "infeasible", ...
    objective: Optional[float]
    bound: Optional[float]
    solve_seconds: float
    kinds: Dict[str, str] = field(default_factory=dict)  # asset name -> kind
    data: Dict[str, Columns] = field(default_factory=dict)  # asset name -> column -> values
    terminal: Dict[str, float] = field(default_factory=dict)  # asset name -> end-of-horizon cost term
    notes: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ status

    @property
    def feasible(self) -> bool:
        return self.objective is not None

    @property
    def optimal(self) -> bool:
        return self.status == "optimal"

    @property
    def gap(self) -> Optional[float]:
        """Relative MIP gap of the returned solution (None when unknown)."""
        if self.objective is None or self.bound is None:
            return None
        return abs(self.objective - self.bound) / max(abs(self.objective), 1e-9)

    # ------------------------------------------------------------------ access

    def assets(self, kind: Optional[str] = None) -> List[str]:
        return [name for name, k in self.kinds.items() if kind is None or k == kind]

    def column(self, asset: str, column: str) -> List[Optional[float]]:
        return self.data[asset][column]

    def total(self, asset: str, column: str) -> float:
        return float(sum(v or 0.0 for v in self.data[asset][column]))

    def cost(self, asset: Optional[str] = None) -> float:
        """Total running cost (sum of ``cost[t]``) of one asset, or of the whole house."""
        names = [asset] if asset else list(self.data)
        return float(sum(self.total(n, "cost") for n in names if "cost" in self.data[n]))

    def terminal_cost(self, asset: Optional[str] = None) -> float:
        """End-of-horizon term of one asset, or of all assets (negative when energy is left stored)."""
        names = [asset] if asset else list(self.terminal)
        return float(sum(self.terminal.get(n, 0.0) for n in names))

    def stored_value(self, asset: Optional[str] = None) -> float:
        """Value of the energy gained over the horizon, i.e. minus the terminal cost."""
        return -self.terminal_cost(asset)

    def summary(self) -> Dict[str, Any]:
        grid = self.assets("grid")
        out: Dict[str, Any] = {
            "status": self.status,
            "objective": self.objective,
            "gap": self.gap,
            "solve_seconds": round(self.solve_seconds, 2),
            "steps": self.horizon.steps,
        }
        if not self.data:  # no solution: nothing else to report
            return out
        if grid:
            g = grid[0]
            out["grid_import_kwh"] = self.total(g, "energy_from")
            out["grid_export_kwh"] = self.total(g, "energy_to")
            out["grid_cost"] = self.cost(g)
        for name in self.assets("battery"):
            out[f"{name}_commands"] = self.total(name, "command") if "command" in self.data[name] else None
            out[f"{name}_cycles"] = self.total(name, "energy_to") / self.notes.get("capacity", {}).get(name, 1.0)
            out[f"{name}_final_soc"] = self.data[name]["soc_end"][-1]
            if name in self.terminal:
                out[f"{name}_stored_value"] = self.stored_value(name)
        for name in self.assets("ev"):
            out[f"{name}_charged_kwh"] = self.total(name, "energy_to")
            out[f"{name}_commands"] = self.total(name, "command")
        return out

    # ------------------------------------------------------------------ pandas

    def frame(self, asset: Optional[str] = None):
        """
        Time-indexed ``pandas.DataFrame``. With ``asset`` the columns are that asset's; without it
        the columns are ``"<asset>.<column>"`` for every asset. Requires pandas.
        """
        import pandas as pd  # optional dependency

        index = pd.DatetimeIndex(self.horizon.timestamps, name="time")
        if asset is not None:
            return pd.DataFrame(self.data[asset], index=index)
        flat = {f"{a}.{c}": v for a, cols in self.data.items() for c, v in cols.items()}
        return pd.DataFrame(flat, index=index)

    def __repr__(self) -> str:
        obj = "n/a" if self.objective is None else f"{self.objective:.4f}"
        return f"Results(status={self.status}, objective={obj}, assets={list(self.data)})"


def values(component, horizon: Horizon) -> List[Optional[float]]:
    """Numeric values of an indexed Var / Param / Expression over the horizon (None when unset)."""
    out = []
    for t in horizon.index:
        try:
            v = pyo.value(component[t], exception=False)
        except (KeyError, IndexError):
            v = None
        out.append(None if v is None else float(v))
    return out
