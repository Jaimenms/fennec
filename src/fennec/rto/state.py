"""What the daemon knows about the house, with the age of every piece of information."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from .messages import Observation


class Health(str, Enum):
    STARTING = "starting"  # waiting for the first reading of every required signal
    RUNNING = "running"  # planning and commanding
    DEGRADED = "degraded"  # planning with an optional signal missing, or last plan failed
    FAULT = "fault"  # a required signal missed its deadline: safe commands sent, no planning
    PAUSED = "paused"  # told to pause by the connector: no commands


@dataclass(frozen=True)
class Deadline:
    """How old a signal may be before the daemon stops trusting it."""

    max_age: timedelta
    required: bool = True

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Deadline":
        return cls(max_age=timedelta(seconds=float(d["max_age_s"])), required=bool(d.get("required", True)))


@dataclass
class Reading:
    data: Dict[str, Any]
    measured_at: datetime
    received_at: datetime

    def age(self, now: datetime) -> timedelta:
        return now - self.measured_at


@dataclass
class Freshness:
    missing: List[str]  # required signals never received
    stale: List[str]  # required signals older than their deadline
    degraded: List[str]  # optional signals that were received before and are now older than their deadline
    optional_missing: List[str]  # optional signals never received (reported, but not a degradation)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.stale


@dataclass
class HouseState:
    deadlines: Dict[str, Deadline]
    readings: Dict[str, Reading] = field(default_factory=dict)
    ev_soc_estimate: Optional[float] = None  # last SOC the car reported, kept while it is away

    def update(self, obs: Observation, now: datetime) -> Optional[Reading]:
        """Store the reading; returns the previous reading of the same signal."""
        previous = self.readings.get(obs.signal)
        self.readings[obs.signal] = Reading(dict(obs.data), obs.time, now)
        if obs.kind == "ev" and obs.data.get("soc") is not None:
            self.ev_soc_estimate = float(obs.data["soc"])
        return previous

    def get(self, signal: str) -> Optional[Reading]:
        return self.readings.get(signal)

    def age(self, signal: str, now: datetime) -> Optional[timedelta]:
        reading = self.readings.get(signal)
        return None if reading is None else reading.age(now)

    def freshness(self, now: datetime) -> Freshness:
        missing, stale, degraded, optional_missing = [], [], [], []
        for signal, deadline in self.deadlines.items():
            age = self.age(signal, now)
            if age is None:
                (missing if deadline.required else optional_missing).append(signal)
            elif age > deadline.max_age:
                (stale if deadline.required else degraded).append(signal)
        return Freshness(missing, stale, degraded, optional_missing)

    def snapshot(self, now: datetime) -> Dict[str, Any]:
        return {
            signal: {"age_s": round(r.age(now).total_seconds(), 1), "measured_at": r.measured_at.isoformat(), **r.data}
            for signal, r in self.readings.items()
            if signal != "forecast.pv" and signal != "forecast.load"
        }
