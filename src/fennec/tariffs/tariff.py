"""Time-of-use tariffs: a price per kWh that depends on the time of day and the weekday."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from ..horizon import Horizon


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


@dataclass(frozen=True)
class Schedule:
    """Daily window ``[start, end)`` in ``"HH:MM"`` (``"24:00"`` allowed) mapped to a price name."""

    start: str
    end: str
    price: str
    weekdays: Optional[Sequence[int]] = None  # 0 = Monday ... 6 = Sunday; None = every day

    def covers(self, instant: datetime) -> bool:
        if self.weekdays is not None and instant.weekday() not in self.weekdays:
            return False
        minute = instant.hour * 60 + instant.minute
        end = _minutes(self.end) if self.end != "00:00" else 24 * 60
        return _minutes(self.start) <= minute < end


@dataclass(frozen=True)
class Tariff:
    """
    Price per kWh as a function of time.

    ``prices`` maps a price name to a value (currency per kWh) and ``schedules`` says which name applies
    when. Instants not covered by any schedule get ``default`` (useful for a "no remuneration" export
    tariff). Prices are evaluated in ``tz`` (default UTC) so that "08:00" means local time of the grid
    operator, not of the horizon.
    """

    name: str
    prices: Dict[str, float] = field(default_factory=dict)
    schedules: List[Schedule] = field(default_factory=list)
    default: float = 0.0
    tz: timezone = timezone.utc

    def __post_init__(self):
        unknown = {s.price for s in self.schedules} - set(self.prices)
        if unknown:
            raise ValueError(f"Tariff {self.name}: schedules reference unknown prices {sorted(unknown)}")

    @classmethod
    def flat(cls, price: float, name: str = "flat") -> "Tariff":
        return cls(name=name, prices={"P": price}, schedules=[Schedule("00:00", "24:00", "P")])

    @classmethod
    def none(cls, name: str = "none") -> "Tariff":
        """Zero at every instant (e.g. PV export without remuneration)."""
        return cls(name=name)

    def price_name(self, instant: datetime) -> Optional[str]:
        local = instant.astimezone(self.tz)
        for schedule in self.schedules:
            if schedule.covers(local):
                return schedule.price
        return None

    def __call__(self, instant: datetime) -> float:
        name = self.price_name(instant)
        return self.default if name is None else self.prices[name]

    def series(self, horizon: Horizon, sample: timedelta = timedelta(minutes=15)) -> List[float]:
        """
        One price per step of the horizon. A step longer than ``sample`` gets the average of the prices
        sampled every ``sample`` inside it, which is exact when the energy is spread evenly over the step.
        """
        out = []
        for ts, d in zip(horizon.timestamps, horizon.durations):
            n = max(1, int(d / sample))
            sub = d / n
            out.append(sum(self(ts + k * sub) for k in range(n)) / n)
        return out
