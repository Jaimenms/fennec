"""Time horizon of an optimization: consecutive steps, not necessarily of equal length, from a tz-aware start."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, List, Optional, Sequence, Tuple


def _parse_hhmm(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def floor_to(instant: datetime, period: timedelta) -> datetime:
    """Last instant at or before ``instant`` that is a multiple of ``period`` counted from the epoch."""
    seconds = period.total_seconds()
    stamp = instant.timestamp()
    return datetime.fromtimestamp(stamp - stamp % seconds, tz=instant.tzinfo)


def ceil_to(instant: datetime, period: timedelta) -> datetime:
    """First instant at or after ``instant`` that is a multiple of ``period`` counted from the epoch."""
    seconds = period.total_seconds()
    stamp = instant.timestamp()
    remainder = stamp % seconds
    if remainder < 1e-9:
        return instant
    return datetime.fromtimestamp(stamp - remainder + seconds, tz=instant.tzinfo)


@dataclass(frozen=True, init=False)
class Horizon:
    """
    Consecutive steps starting at ``start``. Step ``t`` covers ``[timestamps[t], timestamps[t] + durations[t])``.
    Energies in the model are always "kWh exchanged during the step", so steps of different lengths mix
    freely: the usual choice for a rolling optimizer is a fine resolution near "now" and a coarse one later.

    ``Horizon(start, steps, delta_t)`` builds a uniform horizon; ``Horizon(start, durations=[...])`` an
    arbitrary one; ``Horizon.rolling(...)`` the fine-then-coarse horizon aligned to settlement boundaries.
    """

    start: datetime
    durations: Tuple[timedelta, ...]

    def __init__(
        self,
        start: datetime,
        steps: Optional[int] = None,
        delta_t: timedelta = timedelta(minutes=15),
        durations: Optional[Sequence[timedelta]] = None,
    ):
        if start.tzinfo is None:
            raise ValueError("Horizon.start must be timezone-aware")
        if durations is None:
            if steps is None or steps <= 0:
                raise ValueError("Horizon.steps must be positive")
            if delta_t <= timedelta(0):
                raise ValueError("Horizon.delta_t must be positive")
            durations = (delta_t,) * steps
        durations = tuple(durations)
        if not durations:
            raise ValueError("Horizon needs at least one step")
        if any(d <= timedelta(0) for d in durations):
            raise ValueError("every step duration must be positive")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "durations", durations)

    # ------------------------------------------------------------------ constructors

    @classmethod
    def from_range(cls, start: datetime, end: datetime, delta_t: timedelta = timedelta(minutes=15)) -> "Horizon":
        """Uniform horizon covering ``[start, end)``."""
        steps = int((end - start) / delta_t)
        return cls(start=start, steps=steps, delta_t=delta_t)

    @classmethod
    def days(cls, start: datetime, days: float, delta_t: timedelta = timedelta(minutes=15)) -> "Horizon":
        return cls.from_range(start, start + timedelta(days=days), delta_t)

    @classmethod
    def segments(cls, start: datetime, segments: Sequence[Tuple[timedelta, int]]) -> "Horizon":
        """``segments`` is a list of ``(step duration, number of steps)``."""
        durations: List[timedelta] = []
        for delta_t, steps in segments:
            durations.extend([delta_t] * int(steps))
        return cls(start, durations=durations)

    @classmethod
    def rolling(
        cls,
        now: datetime,
        fine: timedelta = timedelta(minutes=15),
        fine_hours: float = 6.0,
        coarse: timedelta = timedelta(hours=1),
        total_hours: float = 36.0,
        align: str = "ceil",
    ) -> "Horizon":
        """
        Horizon for a rolling optimizer: it starts at the ``fine`` boundary at or after ``now`` (``align=
        "ceil"``, e.g. the next quarter of an hour) or at or before it (``"floor"``: the period that is
        running, for a plan applied right away), runs at the ``fine`` step for at least ``fine_hours`` and
        until the clock reaches a ``coarse`` boundary, then at the ``coarse`` step until at least
        ``total_hours`` (the last coarse step is never cut short).
        """
        if align not in ("ceil", "floor"):
            raise ValueError("align must be 'ceil' or 'floor'")
        start = ceil_to(now, fine) if align == "ceil" else floor_to(now, fine)
        switch = ceil_to(start + timedelta(hours=fine_hours), coarse)
        end = start + timedelta(hours=total_hours)
        durations: List[timedelta] = []
        cursor = start
        while cursor < switch and cursor < end:
            durations.append(fine)
            cursor += fine
        while cursor < end:
            durations.append(coarse)
            cursor += coarse
        return cls(start, durations=durations)

    # ------------------------------------------------------------------ basic properties

    @property
    def steps(self) -> int:
        return len(self.durations)

    @property
    def uniform(self) -> bool:
        return all(d == self.durations[0] for d in self.durations)

    @property
    def delta_t(self) -> timedelta:
        """Step length of a uniform horizon (raises for a variable one: use ``durations``)."""
        if not self.uniform:
            raise ValueError("this horizon has steps of different lengths; use durations / hours_at(t)")
        return self.durations[0]

    @property
    def hours(self) -> float:
        """Length of one step in hours (uniform horizons only)."""
        return self.delta_t.total_seconds() / 3600.0

    def hours_at(self, t: int) -> float:
        return self.durations[t].total_seconds() / 3600.0

    @property
    def end(self) -> datetime:
        return self.start + sum(self.durations, timedelta(0))

    @property
    def index(self) -> range:
        return range(self.steps)

    def __len__(self) -> int:
        return self.steps

    def __iter__(self) -> Iterator[datetime]:
        return iter(self.timestamps)

    @property
    def timestamps(self) -> List[datetime]:
        out, cursor = [], self.start
        for d in self.durations:
            out.append(cursor)
            cursor += d
        return out

    @property
    def unix(self) -> List[float]:
        return [ts.timestamp() for ts in self.timestamps]

    def at(self, t: int) -> datetime:
        return self.start + sum(self.durations[:t], timedelta(0))

    def step_at(self, instant: datetime) -> Optional[int]:
        """Index of the step containing ``instant`` (None when outside the horizon)."""
        if instant < self.start:
            return None
        for t, ts in enumerate(self.timestamps):
            if ts <= instant < ts + self.durations[t]:
                return t
        return None

    # ------------------------------------------------------------------ conversions

    def energy(self, power_kw: float, t: Optional[int] = None) -> float:
        """kWh exchanged in one step at a constant power in kW (step ``t``, or any step when uniform)."""
        hours = self.hours if t is None else self.hours_at(t)
        return power_kw * hours

    def energies(self, power_kw: Sequence[float]) -> List[float]:
        """kWh per step from one power value per step."""
        return [p * self.hours_at(t) for t, p in enumerate(power_kw)]

    def integrate(
        self, power_kw: Callable[[datetime], float], sample: timedelta = timedelta(minutes=15)
    ) -> List[float]:
        """
        kWh per step of a power function of time, sampling it every ``sample`` (or once per step when the
        step is shorter) and averaging inside each step.
        """
        out = []
        for ts, d in zip(self.timestamps, self.durations):
            n = max(1, int(d / sample))
            sub = d / n
            mean = sum(power_kw(ts + k * sub) for k in range(n)) / n
            out.append(mean * d.total_seconds() / 3600.0)
        return out

    def resample(self, start: datetime, step: timedelta, values_kwh: Sequence[float], fill: float = 0.0) -> List[float]:
        """
        Map a series of kWh per ``step`` starting at ``start`` onto this horizon, splitting intervals pro
        rata where they overlap step boundaries. Parts of the horizon not covered get ``fill`` per hour.
        """
        out = []
        for ts, d in zip(self.timestamps, self.durations):
            total, covered = 0.0, timedelta(0)
            step_end = ts + d
            for k, value in enumerate(values_kwh):
                a, b = start + k * step, start + (k + 1) * step
                lo, hi = max(a, ts), min(b, step_end)
                if hi > lo:
                    total += value * ((hi - lo) / step)
                    covered += hi - lo
                if a >= step_end:
                    break
            missing = d - covered
            if missing > timedelta(0):
                total += fill * missing.total_seconds() / 3600.0
            out.append(total)
        return out

    # ------------------------------------------------------------------ daily windows

    def local(self, t: int, tz: Optional[timezone] = None) -> datetime:
        return self.at(t).astimezone(tz) if tz is not None else self.at(t)

    def within(self, start: str, end: str, tz: Optional[timezone] = None) -> List[bool]:
        """
        One flag per step: True when the step starts inside the daily window ``[start, end)`` given as
        ``"HH:MM"``. A window with ``end <= start`` wraps around midnight. Times are evaluated in ``tz``
        (default: the horizon's own timezone).
        """
        a, b = _parse_hhmm(start), _parse_hhmm(end)
        flags = []
        for t in self.index:
            local = self.local(t, tz)
            minute = local.hour * 60 + local.minute
            inside = a <= minute < b if a < b else (minute >= a or minute < b)
            flags.append(inside)
        return flags

    def first_steps_at(self, hhmm: str, tz: Optional[timezone] = None) -> List[int]:
        """Index of the first step starting at or after ``hhmm`` on each day of the horizon."""
        target = _parse_hhmm(hhmm)
        found, last_day = [], None
        for t in self.index:
            local = self.local(t, tz)
            minute = local.hour * 60 + local.minute
            if minute >= target and local.date() != last_day:
                found.append(t)
                last_day = local.date()
        return found

    def steps_after(self, instant: datetime) -> List[int]:
        """Indexes of the steps starting at or after ``instant``."""
        return [t for t, ts in enumerate(self.timestamps) if ts >= instant]

    def last_step(self) -> int:
        return self.steps - 1

    def __repr__(self) -> str:
        if self.uniform:
            return f"Horizon(start={self.start.isoformat()}, steps={self.steps}, delta_t={self.durations[0]})"
        return f"Horizon(start={self.start.isoformat()}, steps={self.steps}, durations={self.durations[0]}..{self.durations[-1]})"
