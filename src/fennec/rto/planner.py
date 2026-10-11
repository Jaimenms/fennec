"""Build the house from the current state and the forecasts, solve, and translate the plan into commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..assets import Asset, Battery, ElectricVehicle, Load, PVProduction
from ..commands import Command
from ..horizon import Horizon
from ..model import SmartHome
from ..results import Results
from ..scenario import controller_from_dict, grid_from_dict, resolve_steps
from .config import RtoConfig
from .forecast import fallback_load, fallback_pv, series_for
from .learning import Learner
from .state import HouseState, Reading


class PlanningError(RuntimeError):
    """The optimizer returned no usable plan (infeasible, no solution within the time limit, ...)."""


@dataclass
class Plan:
    created_at: datetime
    horizon: Horizon
    results: Results
    commands: Dict[str, List[Command]] = field(default_factory=dict)  # device -> schedule
    notes: Dict[str, Any] = field(default_factory=dict)

    def current(self, device: str, now: datetime) -> Optional[Command]:
        """The command of ``device`` that applies at ``now`` (or the first one after it)."""
        schedule = self.commands.get(device, [])
        for cmd in schedule:
            if cmd.at <= now < cmd.until:
                return cmd
        for cmd in schedule:
            if cmd.at >= now:
                return cmd
        return None

    def summary(self) -> Dict[str, Any]:
        s = self.results.summary()
        s["horizon_start"] = self.horizon.start.isoformat()
        s["horizon_end"] = self.horizon.end.isoformat()
        s.update(self.notes)
        return s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "created_at": self.created_at.isoformat(),
            "summary": self.summary(),
            "commands": {device: [c.to_dict() for c in cmds] for device, cmds in self.commands.items()},
        }


class Planner:
    """
    Builds and solves the house for "now". Optional pieces: a ``Learner`` whose forecasts replace the
    configured fallbacks once it has enough data, command ``budgets`` (per device kind) that cap the
    optimizer's ``max_commands``, and a warm start from the previous plan.
    """

    def __init__(self, config: RtoConfig, learner: Optional[Learner] = None):
        self.config = config
        self.learner = learner
        self._pv_config = fallback_pv(config.house["pv"])
        self._load_config = fallback_load(config.house["load"])
        self.last_home: Optional[SmartHome] = None

    def pv_fallback(self, horizon: Horizon) -> List[float]:
        learned = self.learner.pv(horizon) if self.learner is not None else None
        return learned if learned is not None else self._pv_config(horizon)

    def load_fallback(self, horizon: Horizon) -> List[float]:
        learned = self.learner.load(horizon) if self.learner is not None else None
        return learned if learned is not None else self._load_config(horizon)

    # ------------------------------------------------------------------ pieces

    def horizon(self, now: datetime) -> Horizon:
        h = self.config.horizon
        return Horizon.rolling(
            now,
            fine=self.config.fine,
            fine_hours=float(h["fine_hours"]),
            coarse=self.config.coarse,
            total_hours=float(h["total_hours"]),
            align="floor",  # the running settlement period is the first step: commands apply right away
        )

    def battery(self, horizon: Horizon, reading: Reading, budget: Optional[int] = None) -> Battery:
        cfg = dict(self.config.house["battery"])
        controller_cfg = dict(cfg.pop("controller", {"type": "ideal"}))
        if controller_cfg.get("type") == "huawei":
            mode = reading.data.get("mode")
            if mode is not None:
                controller_cfg["initial_mode"] = mode  # the reading is the truth
            setpoint = reading.data.get("setpoint_kw")
            if mode == "forced" and setpoint is not None:
                controller_cfg["initial_charge_setpoint"] = min(1.0, max(0.0, setpoint) / float(cfg["max_charge_kw"]))
                controller_cfg["initial_discharge_setpoint"] = min(
                    1.0, max(0.0, -setpoint) / float(cfg["max_discharge_kw"])
                )
            if budget is not None:
                controller_cfg["max_commands"] = min(int(controller_cfg.get("max_commands", 100)), budget)
        controller = controller_from_dict(controller_cfg)
        soc_required = resolve_steps(cfg.pop("soc_required", {}), horizon)
        soc_min, soc_max = float(cfg.get("soc_min", 0.0)), float(cfg.get("soc_max", 100.0))
        cfg["soc_initial"] = min(max(float(reading.data["soc"]), soc_min), soc_max)
        return Battery(controller=controller, soc_required=soc_required, **cfg)

    def availability(self, horizon: Horizon, reading: Reading) -> Tuple[List[bool], Dict[int, float]]:
        """
        Plugged flags and SOC-on-return map for the horizon, from the daily trip in the configuration
        corrected by what the connector reports now: plugged or not, and an expected departure or return
        when announced. An announced instant replaces the next scheduled one; the daily pattern resumes
        after that.
        """
        trip = self.config.house["ev"]["trip"]
        base = horizon.within(trip["leave"], trip["back"])  # scheduled "away" flags
        away = list(base)
        plugged_now = bool(reading.data["plugged"])
        soc_on_return = float(reading.data.get("soc_on_return") or trip["soc_on_return"])

        def step_at_or_after(instant) -> int:
            later = horizon.steps_after(instant)
            return later[0] if later else horizon.steps

        def next_transition(after: int, to_value: bool) -> int:
            """First step after ``after`` where the scheduled flags switch to ``to_value``."""
            for t in range(max(after, 0) + 1, horizon.steps):
                if base[t] == to_value and base[t - 1] != to_value:
                    return t
            return horizon.steps

        if plugged_now:
            announced = reading.data.get("expected_departure")
            departure = step_at_or_after(announced) if announced is not None else next_transition(0, True)
            for t in range(departure):
                away[t] = False
            if announced is not None:  # away from the announced departure until the next scheduled return
                for t in range(departure, next_transition(departure, False)):
                    away[t] = True
        else:
            announced = reading.data.get("expected_return")
            back = step_at_or_after(announced) if announced is not None else next_transition(0, False)
            for t in range(back):
                away[t] = True
            if announced is not None:  # home from the announced return until the next scheduled departure
                for t in range(back, next_transition(back, True)):
                    away[t] = False

        plugged = [not a for a in away]
        returns = {t: soc_on_return for t in range(1, horizon.steps) if plugged[t] and not plugged[t - 1]}
        return plugged, returns

    def vehicle(
        self, horizon: Horizon, reading: Reading, state: HouseState, budget: Optional[int] = None
    ) -> ElectricVehicle:
        cfg = dict(self.config.house["ev"])
        trip = cfg.pop("trip")
        if reading.data.get("charging") is not None:
            cfg["initial_charge"] = 1.0 if reading.data["charging"] else 0.0
        if budget is not None:
            cfg["max_commands"] = min(int(cfg.get("max_commands", 100)), budget)
        plugged, returns = self.availability(horizon, reading)
        soc_now = reading.data.get("soc")
        if soc_now is None:
            soc_now = state.ev_soc_estimate if state.ev_soc_estimate is not None else trip["soc_on_return"]
        cfg["soc_target"] = resolve_steps(cfg.get("soc_target", {}), horizon)
        cfg.pop("soc_on_return", None)
        cfg.pop("plugged", None)
        soc_min, soc_max = float(cfg.get("soc_min", 0.0)), float(cfg.get("soc_max", 100.0))
        return ElectricVehicle(
            plugged=plugged,
            soc_initial=min(max(float(soc_now), soc_min), soc_max),
            soc_on_return=returns,
            **cfg,
        )

    # ------------------------------------------------------------------ build and solve

    def build(
        self, now: datetime, state: HouseState, budgets: Optional[Dict[str, int]] = None
    ) -> Tuple[SmartHome, Dict[str, Any]]:
        h = self.horizon(now)
        budgets = budgets or {}
        notes: Dict[str, Any] = {}
        pv, notes["pv_source"] = series_for(h, state.get("forecast.pv"), self.pv_fallback)
        load, notes["load_source"] = series_for(h, state.get("forecast.load"), self.load_fallback)
        if self.learner is not None:
            notes["learned"] = self.learner.summary()
        if budgets:
            notes["command_budgets"] = dict(budgets)
        assets: List[Asset] = [
            PVProduction(self.config.house["pv"].get("name", "pv"), energy=pv),
            Load(self.config.house["load"].get("name", "house"), energy=load),
        ]
        if self.config.has_battery:
            reading = state.get("battery")
            if reading is None:
                notes["battery"] = "excluded: no reading"
            else:
                assets.append(self.battery(h, reading, budgets.get("battery")))
        if self.config.has_ev:
            reading = state.get("ev")
            if reading is None:
                notes["ev"] = "excluded: no reading"
            else:
                assets.append(self.vehicle(h, reading, state, budgets.get("ev")))
        return SmartHome(h, grid_from_dict(self.config.house["grid"]), assets), notes

    def plan(self, now: datetime, state: HouseState, budgets: Optional[Dict[str, int]] = None) -> Plan:
        try:
            home, notes = self.build(now, state, budgets)
        except ValueError as e:  # inconsistent state / configuration
            raise PlanningError(f"cannot build the house: {e}") from e
        warm = 0
        if self.last_home is not None:
            try:
                warm = home.warm_start_from(self.last_home)
            except Exception:  # a warm start is a hint, never a reason to fail
                warm = 0
        notes["warm_start_values"] = warm
        results = home.solve(**self.config.solver, warm_start=warm > 0)
        if not results.feasible:
            raise PlanningError(f"solver returned {results.status}")
        self.last_home = home
        commands: Dict[str, List[Command]] = {}
        for asset in home.assets:
            if isinstance(asset, Battery):
                commands[asset.name] = asset.controller.commands(results, asset)
            elif isinstance(asset, ElectricVehicle):
                commands[asset.name] = asset.commands(results)
        notes["status"] = results.status
        notes["gap"] = results.gap
        return Plan(created_at=now, horizon=home.horizon, results=results, commands=commands, notes=notes)
