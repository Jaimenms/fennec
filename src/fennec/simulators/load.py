"""Synthetic household load: a base load plus an occupancy profile by local solar time."""

from datetime import datetime
from typing import List

from ..horizon import Horizon


def house_load_kw(instant: datetime, area_m2: float, residents: int, longitude: float) -> float:
    """
    Instantaneous load in kW of a typical European household.

    Base load: 0.5 kW + 0.005 kW per m2. Occupancy load per resident by local solar time: 0.5 kW in
    the morning (06-09), 0.3 kW during the day (09-18), 0.7 kW in the evening (18-23) and 0.2 kW at night.
    """
    utc_hour = instant.hour + instant.minute / 60.0 + instant.second / 3600.0
    solar_hour = (utc_hour + longitude / 15.0) % 24

    if 6 <= solar_hour < 9:
        per_resident = 0.5
    elif 9 <= solar_hour < 18:
        per_resident = 0.3
    elif 18 <= solar_hour < 23:
        per_resident = 0.7
    else:
        per_resident = 0.2

    return 0.5 + 0.005 * area_m2 + residents * per_resident


def simulate_house_load_energy(horizon: Horizon, area_m2: float, residents: int, longitude: float) -> List[float]:
    """kWh consumed in each step of the horizon (power sampled every 15 minutes inside the step)."""
    return horizon.integrate(lambda ts: house_load_kw(ts, area_m2, residents, longitude))
