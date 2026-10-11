"""
Scenarios as plain dictionaries (JSON / YAML friendly) and back.

Example::

    {
      "horizon": {"start": "2025-03-22T00:00:00+00:00", "steps": 144, "step_minutes": 15},
      "grid": {"contracted_power_kw": 6.9, "import_tariff": "bi_daily", "export_tariff": "none"},
      "assets": [
        {"type": "pv", "name": "pv",
         "simulate": {"area_m2": 25, "efficiency": 0.2, "latitude": 41.21, "longitude": -8.61}},
        {"type": "load", "name": "house", "simulate": {"area_m2": 100, "residents": 4, "longitude": -8.61}},
        {"type": "battery", "name": "battery", "capacity_kwh": 10, "max_charge_kw": 5, "max_discharge_kw": 5,
         "soc_initial": 50, "soc_min": 10, "controller": {"type": "huawei", "max_commands": 4}},
        {"type": "ev", "name": "car", "capacity_kwh": 40, "max_charge_kw": 3.7,
         "daily_trip": {"leave": "08:30", "back": "18:00", "soc_on_return": 40},
         "soc_target": {"08:00": 80}, "max_commands": 6, "command_penalty": 0.001}
      ],
      "solver": {"time_limit": 60}
    }

Time series (``"energy"``, ``"plugged"``) can be given explicitly with one value per step, or produced
by the simulators with ``"simulate"`` / ``"daily_trip"``. Step references (``soc_target``,
``soc_required``) accept step indexes or ``"HH:MM"`` strings (first step at that time on every day).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Mapping, Union

from .assets import Asset, Battery, ElectricVehicle, Grid, Load, PVProduction
from .controllers import BatteryController, HuaweiLuna2000Controller, IdealController
from .horizon import Horizon
from .model import SmartHome
from .results import Results
from .simulators import simulate_house_load_energy, simulate_pv_energy
from .tariffs import PRESETS, Schedule, Tariff

CONTROLLERS = {"ideal": IdealController, "huawei": HuaweiLuna2000Controller}


def _only(d: Mapping[str, Any], allowed: set, what: str) -> Dict[str, Any]:
    unknown = set(d) - allowed
    if unknown:
        raise ValueError(f"{what}: unknown keys {sorted(unknown)}; allowed: {sorted(allowed)}")
    return dict(d)


def resolve_steps(ref: Mapping[Union[str, int], float], horizon: Horizon) -> Dict[int, float]:
    """Map ``{"HH:MM" | step: value}`` onto step indexes of the horizon (a time hits the first step of every day)."""
    out: Dict[int, float] = {}
    for key, value in ref.items():
        if isinstance(key, str) and ":" in key:
            for t in horizon.first_steps_at(key):
                out[t] = float(value)
        else:
            out[int(key)] = float(value)
    return out


_steps = resolve_steps


# ---------------------------------------------------------------------- pieces


def horizon_from_dict(d: Mapping[str, Any]) -> Horizon:
    d = _only(d, {"start", "end", "steps", "step_minutes", "days"}, "horizon")
    start = datetime.fromisoformat(d["start"])
    delta = timedelta(minutes=d.get("step_minutes", 15))
    if "steps" in d:
        return Horizon(start, int(d["steps"]), delta)
    if "end" in d:
        return Horizon.from_range(start, datetime.fromisoformat(d["end"]), delta)
    if "days" in d:
        return Horizon.days(start, float(d["days"]), delta)
    raise ValueError("horizon: give 'steps', 'end' or 'days'")


def tariff_from_value(value: Any) -> Tariff:
    if isinstance(value, Tariff):
        return value
    if isinstance(value, str):
        if value not in PRESETS:
            raise ValueError(f"unknown tariff preset {value!r}; known: {sorted(PRESETS)}")
        return PRESETS[value]
    if isinstance(value, (int, float)):
        return Tariff.flat(float(value))
    d = _only(value, {"flat", "name", "prices", "schedules", "default"}, "tariff")
    if "flat" in d:
        return Tariff.flat(float(d["flat"]), name=d.get("name", "flat"))
    schedules = [Schedule(s["start"], s["end"], s["price"], s.get("weekdays")) for s in d.get("schedules", [])]
    return Tariff(d.get("name", "custom"), dict(d.get("prices", {})), schedules, float(d.get("default", 0.0)))


def grid_from_dict(d: Mapping[str, Any]) -> Grid:
    d = _only(
        d, {"name", "import_tariff", "export_tariff", "contracted_power_kw", "export_power_kw", "settled"}, "grid"
    )
    return Grid(
        name=d.get("name", "grid"),
        import_tariff=tariff_from_value(d.get("import_tariff", "simple")),
        export_tariff=tariff_from_value(d.get("export_tariff", "none")),
        contracted_power_kw=float(d.get("contracted_power_kw", 6.9)),
        export_power_kw=d.get("export_power_kw"),
        settled=d.get("settled"),
    )


def controller_from_dict(d: Mapping[str, Any]) -> BatteryController:
    d = dict(d)
    kind = d.pop("type", "ideal")
    if kind not in CONTROLLERS:
        raise ValueError(f"unknown controller type {kind!r}; known: {sorted(CONTROLLERS)}")
    return CONTROLLERS[kind](**d)


def asset_from_dict(d: Mapping[str, Any], horizon: Horizon) -> Asset:
    d = dict(d)
    kind = d.pop("type", None)
    if kind in ("pv", "load"):
        cls = PVProduction if kind == "pv" else Load
        d = _only(d, {"name", "energy", "simulate"}, kind)
        if "simulate" in d:
            sim = d.pop("simulate")
            if kind == "pv":
                energy = simulate_pv_energy(horizon, **sim)
            else:
                energy = simulate_house_load_energy(horizon, **sim)
        else:
            energy = list(d.pop("energy"))
        return cls(name=d["name"], energy=energy)

    if kind == "battery":
        controller = controller_from_dict(d.pop("controller", {"type": "ideal"}))
        soc_required = _steps(d.pop("soc_required", {}), horizon)
        return Battery(controller=controller, soc_required=soc_required, **d)

    if kind == "ev":
        if "daily_trip" in d:
            trip = d.pop("daily_trip")
            plugged, returns = ElectricVehicle.daily_trip(horizon, trip["leave"], trip["back"], trip["soc_on_return"])
            d["plugged"], d["soc_on_return"] = plugged, returns
        else:
            d["plugged"] = [bool(p) for p in d["plugged"]]
            d["soc_on_return"] = _steps(d.get("soc_on_return", {}), horizon)
        d["soc_target"] = _steps(d.get("soc_target", {}), horizon)
        return ElectricVehicle(**d)

    raise ValueError(f"unknown asset type {kind!r}; known: pv, load, battery, ev")


# ---------------------------------------------------------------------- whole scenario


def smart_home_from_dict(d: Mapping[str, Any]) -> SmartHome:
    d = _only(d, {"horizon", "grid", "assets", "solver", "name", "description"}, "scenario")
    horizon = horizon_from_dict(d["horizon"])
    grid = grid_from_dict(d.get("grid", {}))
    assets = [asset_from_dict(a, horizon) for a in d.get("assets", [])]
    return SmartHome(horizon, grid, assets)


def load_scenario(path: Union[str, Path]) -> SmartHome:
    with open(path, "r", encoding="utf-8") as f:
        return smart_home_from_dict(json.load(f))


def solver_options(d: Mapping[str, Any]) -> Dict[str, Any]:
    return _only(d.get("solver", {}), {"time_limit", "mip_rel_gap", "mip_abs_gap", "threads", "tee"}, "solver")


def results_to_dict(results: Results) -> Dict[str, Any]:
    """JSON-serializable view of the results (time series per asset plus the summary)."""
    return {
        "status": results.status,
        "objective": results.objective,
        "bound": results.bound,
        "gap": results.gap,
        "solve_seconds": results.solve_seconds,
        "timestamps": [ts.isoformat() for ts in results.horizon.timestamps],
        "kinds": results.kinds,
        "summary": results.summary(),
        "series": results.data,
    }
