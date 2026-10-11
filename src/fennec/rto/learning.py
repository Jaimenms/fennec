"""
Forecasts learned from what the house reported, so that the fallback profiles improve with time.

Everything the daemon sees is written to the audit file, so the learner is rebuilt from it at start-up
(``Learner.from_audit``) and fed live afterwards (``Learner.observe``). Two things are learned:

* **PV**: the ratio between the production the inverter reported (``pv_kw`` in the battery message) and
  the clear-sky model of the configuration, as a median per hour of the day over the last ``days``. The
  forecast is clear-sky times that factor.
* **Load**: the house consumption per 15-minute slot of the day, separately for weekdays and weekends, as
  a median over the last ``days``. The consumption is ``load_kw`` from the meter message when the meter
  measures it, otherwise derived from the balance ``import - export + pv - battery - car`` with the powers
  reported (a missing part is taken as zero, so report them all for a clean estimate).

Until ``min_days`` of data exist for a quantity the learner answers ``None`` and the planner keeps the
configured fallback.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..horizon import Horizon, floor_to
from .forecast import fallback_pv
from .messages import MessageError, Observation

SLOT = timedelta(minutes=15)
Series = List[float]


class History:
    """Power samples (kW) per 15-minute slot and per quantity, kept for a number of days."""

    def __init__(self, days: int = 14):
        self.days = days
        self.samples: Dict[str, Dict[datetime, List[float]]] = defaultdict(lambda: defaultdict(list))
        self.latest: Optional[datetime] = None

    def add(self, quantity: str, at: datetime, kw: float) -> None:
        slot = floor_to(at, SLOT)
        self.samples[quantity][slot].append(float(kw))
        if self.latest is None or at > self.latest:
            self.latest = at
            self.prune()

    def prune(self) -> None:
        if self.latest is None:
            return
        cutoff = self.latest - timedelta(days=self.days)
        for quantity in self.samples.values():
            for slot in [s for s in quantity if s < cutoff]:
                del quantity[slot]

    def observe(self, obs: Observation) -> None:
        d = obs.data
        if obs.kind == "battery":
            if d.get("pv_kw") is not None:
                self.add("pv", obs.time, d["pv_kw"])
            if d.get("power_kw") is not None:
                self.add("battery", obs.time, d["power_kw"])
        elif obs.kind == "ev":
            power = d.get("power_kw")
            if power is None and d.get("charging") is not None:
                power = None if d["charging"] else 0.0
            if not d.get("plugged"):
                power = 0.0
            if power is not None:
                self.add("car", obs.time, power)
        elif obs.kind == "meter":
            if d.get("load_kw") is not None:
                self.add("load", obs.time, d["load_kw"])
            net = d["power_kw"] if "power_kw" in d else d["import_kw"] - d["export_kw"]
            self.add("net", obs.time, net)

    def mean_kw(self, quantity: str) -> Dict[datetime, float]:
        return {slot: sum(v) / len(v) for slot, v in self.samples[quantity].items() if v}

    def load_kw(self) -> Dict[datetime, float]:
        """House consumption per slot: measured when available, otherwise from the balance."""
        measured = self.mean_kw("load")
        if measured:
            return measured
        net, pv = self.mean_kw("net"), self.mean_kw("pv")
        battery, car = self.mean_kw("battery"), self.mean_kw("car")
        return {slot: net[slot] + pv.get(slot, 0.0) - battery.get(slot, 0.0) - car.get(slot, 0.0) for slot in net}

    def days_with(self, quantity: str) -> int:
        slots = self.samples[quantity]
        return len({s.date() for s in slots})


class Learner:
    def __init__(self, pv_config: Dict[str, Any], days: int = 14, min_days: int = 3, tz: Optional[timezone] = None):
        self.history = History(days)
        self.min_days = min_days
        self.tz = tz
        self.clear_sky: Callable[[Horizon], Series] = fallback_pv({**pv_config, "factor": 1.0})
        self.default_factor = float(pv_config.get("factor", 1.0))
        self._factor_cache: Tuple[Optional[datetime], Dict[int, float]] = (None, {})

    # ------------------------------------------------------------------ feeding

    def observe(self, obs: Observation) -> None:
        self.history.observe(obs)

    @classmethod
    def from_audit(
        cls, path: Union[str, Path], pv_config: Dict[str, Any], days: int = 14, min_days: int = 3
    ) -> "Learner":
        learner = cls(pv_config, days=days, min_days=min_days)
        path = Path(path)
        if not path.exists():
            return learner
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("kind") != "observation":
                    continue
                payload = {k: v for k, v in record.items() if k not in ("kind",)}
                try:
                    learner.observe(Observation.from_dict(payload))
                except (MessageError, KeyError, TypeError):
                    continue
        return learner

    # ------------------------------------------------------------------ PV

    def _local_hour(self, slot: datetime) -> int:
        return (slot.astimezone(self.tz) if self.tz else slot).hour

    def pv_factors(self) -> Dict[int, float]:
        """Median ratio observed / clear-sky per local hour of the day."""
        if self.history.latest is not None and self._factor_cache[0] == self.history.latest:
            return self._factor_cache[1]
        observed = self.history.mean_kw("pv")
        ratios: Dict[int, List[float]] = defaultdict(list)
        for slot, kw in observed.items():
            clear = self.clear_sky(Horizon(slot, 1, SLOT))[0] / SLOT.total_seconds() * 3600.0  # kW
            if clear > 0.05:
                ratios[self._local_hour(slot)].append(max(0.0, kw) / clear)
        factors = {hour: float(median(v)) for hour, v in ratios.items() if v}
        self._factor_cache = (self.history.latest, factors)
        return factors

    def pv(self, horizon: Horizon) -> Optional[Series]:
        if self.history.days_with("pv") < self.min_days:
            return None
        factors = self.pv_factors()
        clear = self.clear_sky(horizon)
        return [e * factors.get(self._local_hour(ts), self.default_factor) for e, ts in zip(clear, horizon.timestamps)]

    # ------------------------------------------------------------------ load

    def load_profile(self) -> Dict[Tuple[bool, int], float]:
        """Median kW per (weekend?, slot of the day) over the kept days."""
        by_key: Dict[Tuple[bool, int], List[float]] = defaultdict(list)
        for slot, kw in self.history.load_kw().items():
            local = slot.astimezone(self.tz) if self.tz else slot
            key = (local.weekday() >= 5, local.hour * 4 + local.minute // 15)
            by_key[key].append(kw)
        return {key: float(median(v)) for key, v in by_key.items() if v}

    def load(self, horizon: Horizon) -> Optional[Series]:
        quantity = "load" if self.history.samples["load"] else "net"
        if self.history.days_with(quantity) < self.min_days:
            return None
        profile = self.load_profile()
        if not profile:
            return None

        def kw(ts: datetime) -> float:
            local = ts.astimezone(self.tz) if self.tz else ts
            key = (local.weekday() >= 5, local.hour * 4 + local.minute // 15)
            if key in profile:
                return profile[key]
            other = (not key[0], key[1])
            return profile.get(other, 0.0)

        return horizon.integrate(kw, sample=SLOT)

    # ------------------------------------------------------------------ reporting

    def summary(self) -> Dict[str, Any]:
        return {
            "pv_days": self.history.days_with("pv"),
            "load_days": self.history.days_with("load" if self.history.samples["load"] else "net"),
            "pv_factor_hours": len(self.pv_factors()) if self.history.samples["pv"] else 0,
            "min_days": self.min_days,
        }
