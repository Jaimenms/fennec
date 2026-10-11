"""
Daemon configuration (a JSON file). Example::

    {
      "house": {
        "grid": {"contracted_power_kw": 6.9, "import_tariff": "bi_daily", "export_tariff": "none"},
        "battery": {"name": "battery", "capacity_kwh": 10, "max_charge_kw": 5, "max_discharge_kw": 5,
                    "soc_min": 10, "controller": {"type": "huawei", "command_penalty": 0.01}},
        "ev": {"name": "car", "capacity_kwh": 40, "max_charge_kw": 3.7,
               "trip": {"leave": "08:30", "back": "18:00", "soc_on_return": 40},
               "soc_target": {"08:00": 80}, "command_penalty": 0.001},
        "pv": {"name": "pv", "simulate": {"area_m2": 25, "efficiency": 0.2, "latitude": 41.21,
                                           "longitude": -8.61}, "factor": 0.8},
        "load": {"name": "house", "kw_by_hour": [0.6, 0.6, ..., 1.8]}
      },
      "horizon": {"fine_minutes": 15, "fine_hours": 6, "coarse_minutes": 60, "total_hours": 36},
      "deadlines": {"battery": {"max_age_s": 900}, "ev": {"max_age_s": 1800},
                    "meter": {"max_age_s": 300, "required": false},
                    "forecast.pv": {"max_age_s": 21600, "required": false},
                    "forecast.load": {"max_age_s": 21600, "required": false}},
      "replan": {"period_minutes": 15, "event_debounce_s": 60, "retry_s": 120},
      "limits": {"battery": {"commands_per_day": 12}, "ev": {"commands_per_day": 12}},
      "learning": {"enabled": true, "days": 14, "min_days": 3},
      "solver": {"time_limit": 120, "mip_rel_gap": 0.005},
      "audit": "fennec-rto.jsonl"
    }

``pv`` and ``load`` describe the fallback forecasts used when the connector sends none (or a stale one) and
no learned forecast is available yet. ``battery`` and ``ev`` are optional: a house may have only one of
them. ``limits`` caps the commands actually sent to each device over a rolling day: the remaining budget
is handed to the optimizer as its ``max_commands``. ``learning`` rebuilds forecasts from the audit file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .state import Deadline

DEFAULT_DEADLINES = {
    "battery": {"max_age_s": 900, "required": True},
    "ev": {"max_age_s": 1800, "required": True},
    "meter": {"max_age_s": 300, "required": False},
    "forecast.pv": {"max_age_s": 6 * 3600, "required": False},
    "forecast.load": {"max_age_s": 6 * 3600, "required": False},
}


@dataclass
class RtoConfig:
    house: Dict[str, Any]
    horizon: Dict[str, float] = field(default_factory=dict)
    deadlines: Dict[str, Deadline] = field(default_factory=dict)
    replan: Dict[str, float] = field(default_factory=dict)
    solver: Dict[str, Any] = field(default_factory=dict)
    limits: Dict[str, Dict[str, float]] = field(default_factory=dict)
    learning: Dict[str, Any] = field(default_factory=dict)
    audit: Optional[str] = None

    def __post_init__(self):
        if "grid" not in self.house:
            raise ValueError("config.house needs a 'grid'")
        if "pv" not in self.house or "load" not in self.house:
            raise ValueError("config.house needs 'pv' and 'load' fallback forecasts")
        self.horizon = {"fine_minutes": 15, "fine_hours": 6, "coarse_minutes": 60, "total_hours": 36, **self.horizon}
        self.replan = {"period_minutes": 15, "event_debounce_s": 60, "retry_s": 120, **self.replan}
        self.solver = {"time_limit": 120, "mip_rel_gap": 0.005, **self.solver}
        self.learning = {"enabled": True, "days": 14, "min_days": 3, **self.learning}
        for kind, limit in self.limits.items():
            if kind not in ("battery", "ev"):
                raise ValueError(f"config.limits: unknown device kind {kind!r}")
            if "commands_per_day" in limit and limit["commands_per_day"] < 0:
                raise ValueError("config.limits.commands_per_day must be non-negative")
        defaults = {k: Deadline.from_dict(v) for k, v in DEFAULT_DEADLINES.items()}
        self.deadlines = {**defaults, **self.deadlines}
        # signals of devices the house does not have are never expected, whatever the deadlines say
        for kind in ("battery", "ev"):
            if kind not in self.house:
                self.deadlines.pop(kind, None)

    # ------------------------------------------------------------------ derived

    @property
    def period(self) -> timedelta:
        return timedelta(minutes=float(self.replan["period_minutes"]))

    @property
    def fine(self) -> timedelta:
        return timedelta(minutes=float(self.horizon["fine_minutes"]))

    @property
    def coarse(self) -> timedelta:
        return timedelta(minutes=float(self.horizon["coarse_minutes"]))

    @property
    def has_battery(self) -> bool:
        return "battery" in self.house

    @property
    def has_ev(self) -> bool:
        return "ev" in self.house

    def device_names(self) -> Dict[str, str]:
        """kind -> asset name for the controllable devices."""
        names = {}
        if self.has_battery:
            names["battery"] = self.house["battery"].get("name", "battery")
        if self.has_ev:
            names["ev"] = self.house["ev"].get("name", "car")
        return names

    # ------------------------------------------------------------------ loading

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RtoConfig":
        unknown = set(d) - {
            "house",
            "horizon",
            "deadlines",
            "replan",
            "solver",
            "limits",
            "learning",
            "audit",
            "name",
            "description",
        }
        if unknown:
            raise ValueError(f"config: unknown keys {sorted(unknown)}")
        deadlines = {k: Deadline.from_dict(v) for k, v in d.get("deadlines", {}).items()}
        return cls(
            house=dict(d["house"]),
            horizon=dict(d.get("horizon", {})),
            deadlines=deadlines,
            replan=dict(d.get("replan", {})),
            solver=dict(d.get("solver", {})),
            limits={k: dict(v) for k, v in d.get("limits", {}).items()},
            learning=dict(d.get("learning", {})),
            audit=d.get("audit"),
        )

    @classmethod
    def load(cls, path: Union[str, Path]) -> "RtoConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
