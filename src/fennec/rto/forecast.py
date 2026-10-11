"""
PV and load forecasts for a horizon: delivered by the connector when available, otherwise a fallback.

A delivered forecast is a series of kWh per fixed step starting at some instant; it is resampled onto the
horizon pro rata. Steps the delivered series does not fully cover fall back to the configured model, so a
forecast that ends before the horizon does is still usable.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..horizon import Horizon
from ..simulators import simulate_house_load_energy, simulate_pv_energy
from .state import Reading

Series = List[float]


def fallback_pv(cfg: Dict[str, Any]) -> Callable[[Horizon], Series]:
    """Clear-sky production scaled by ``factor`` (typical cloudiness), from the ``simulate`` parameters."""
    params, factor = dict(cfg.get("simulate", {})), float(cfg.get("factor", 1.0))
    if "energy_kwh_by_hour" in cfg:
        by_hour = [float(v) for v in cfg["energy_kwh_by_hour"]]
        return lambda h: h.integrate(lambda ts: by_hour[ts.hour])  # kWh per hour == kW
    return lambda h: [v * factor for v in simulate_pv_energy(h, **params)]


def fallback_load(cfg: Dict[str, Any]) -> Callable[[Horizon], Series]:
    """A daily profile in kW by hour of day, or the household simulator."""
    if "kw_by_hour" in cfg:
        by_hour = [float(v) for v in cfg["kw_by_hour"]]
        if len(by_hour) != 24:
            raise ValueError("load.kw_by_hour needs 24 values")
        return lambda h: h.integrate(lambda ts: by_hour[ts.hour])
    params = dict(cfg.get("simulate", {}))
    return lambda h: simulate_house_load_energy(h, **params)


def coverage(horizon: Horizon, start, step: timedelta, n: int) -> List[bool]:
    """True for the horizon steps fully covered by a series of ``n`` intervals of ``step`` from ``start``."""
    end = start + n * step
    return [ts >= start and ts + d <= end for ts, d in zip(horizon.timestamps, horizon.durations)]


def series_for(
    horizon: Horizon, reading: Optional[Reading], fallback: Callable[[Horizon], Series]
) -> Tuple[Series, str]:
    """The forecast to use on ``horizon`` and where it came from: 'connector', 'connector+fallback' or 'fallback'."""
    base = fallback(horizon)
    if reading is None:
        return base, "fallback"
    data = reading.data
    start, step, values = (
        data["start"],
        timedelta(minutes=float(data["step_minutes"])),
        [float(v) for v in data["values_kwh"]],
    )
    delivered = horizon.resample(start, step, values, fill=0.0)
    covered = coverage(horizon, start, step, len(values))
    merged = [d if c else b for d, b, c in zip(delivered, base, covered)]
    source = "connector" if all(covered) else "connector+fallback"
    return merged, source
