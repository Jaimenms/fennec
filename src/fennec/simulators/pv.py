"""Synthetic PV production from solar geometry (clear-sky, direct irradiance only)."""

import math
import warnings
from datetime import datetime
from typing import List

warnings.filterwarnings("ignore", message="no explicit representation of timezones available for np.datetime64")
warnings.filterwarnings("ignore", message="Leap seconds for year")

from pysolar.radiation import get_radiation_direct  # noqa: E402
from pysolar.solar import get_altitude, get_azimuth  # noqa: E402

from ..horizon import Horizon


def pv_power_kw(
    instant: datetime,
    area_m2: float,
    efficiency: float,
    latitude: float,
    longitude: float,
    tilt_deg: float = 35.0,
    azimuth_deg: float = 180.0,
) -> float:
    """
    Instantaneous output in kW of a tilted panel under clear sky.

    ``azimuth_deg`` follows pysolar's convention (0 = North, 90 = East, 180 = South). Returns 0 when the
    sun is below the horizon or behind the panel.
    """
    altitude = get_altitude(latitude, longitude, instant)
    if altitude <= 0:
        return 0.0
    solar_azimuth = get_azimuth(latitude, longitude, instant)

    alt = math.radians(altitude)
    tilt = math.radians(tilt_deg)
    cos_incidence = math.sin(alt) * math.cos(tilt) + math.cos(alt) * math.sin(tilt) * math.cos(
        math.radians(solar_azimuth) - math.radians(azimuth_deg)
    )
    if cos_incidence < 0:
        return 0.0

    irradiance_w_m2 = get_radiation_direct(instant, altitude) * cos_incidence
    return area_m2 * efficiency * irradiance_w_m2 / 1000.0


def simulate_pv_energy(
    horizon: Horizon,
    area_m2: float,
    efficiency: float,
    latitude: float,
    longitude: float,
    tilt_deg: float = 35.0,
    azimuth_deg: float = 180.0,
) -> List[float]:
    """kWh produced in each step of the horizon (power sampled every 15 minutes inside the step)."""
    return horizon.integrate(
        lambda ts: pv_power_kw(ts, area_m2, efficiency, latitude, longitude, tilt_deg, azimuth_deg)
    )
