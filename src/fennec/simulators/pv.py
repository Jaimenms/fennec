import math
from datetime import datetime, timezone

from pysolar.radiation import get_radiation_direct
from pysolar.solar import get_altitude, get_azimuth
from ..utils import convert_power_to_energy


def simulate_pv_power(utc_timestamp, area, efficiency, latitude, longitude, tilt_deg, azimuth_deg):
    """
    Estimate the instantaneous power output (in kW) of a tilted solar panel using PySolar.

    Parameters:
        utc_timestamp (float): Unix timestamp in seconds (UTC).
        area (float): Panel area in m².
        efficiency (float): Panel efficiency (e.g., 0.20 for 20%).
        latitude (float): Latitude in degrees.
        longitude (float): Longitude in degrees.
        tilt_deg (float): Panel tilt angle from horizontal in degrees.
        azimuth_deg (float): Panel azimuth in degrees (0 = North, 90 = East, etc.)

    Returns:
        float: Estimated power output in kW. Returns 0 if the sun is below the horizon or behind the panel.
    """
    # Convert the timestamp to a UTC datetime object.
    dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)

    # Get the solar altitude and azimuth using PySolar.
    altitude = get_altitude(latitude, longitude, dt)
    # If the sun is below the horizon, no power is produced.
    if altitude <= 0:
        return 0.0

    solar_azimuth = get_azimuth(latitude, longitude, dt)

    # Convert all angles to radians.
    alt_rad = math.radians(altitude)
    solar_azimuth_rad = math.radians(solar_azimuth)
    tilt_rad = math.radians(tilt_deg)
    panel_azimuth_rad = math.radians(azimuth_deg)

    # Calculate the incidence angle using the formula:
    # cos(theta_i) = sin(alt)*cos(tilt) + cos(alt)*sin(tilt)*cos(solar_azimuth - panel_azimuth)
    cos_theta_i = math.sin(alt_rad) * math.cos(tilt_rad) + math.cos(alt_rad) * math.sin(tilt_rad) * math.cos(
        solar_azimuth_rad - panel_azimuth_rad
    )

    # If the sun is behind the panel, no effective irradiance is received.
    if cos_theta_i < 0:
        return 0.0

    # Obtain the direct normal irradiance (DNI) from PySolar (in W/m²).
    dni = get_radiation_direct(dt, altitude)

    # Compute the effective irradiance on the panel (W/m²) adjusted by the incidence angle.
    effective_irradiance = dni * cos_theta_i

    # Convert irradiance from W/m² to kW/m².
    effective_irradiance_kw = effective_irradiance / 1000.0

    # Compute the panel power output in kW.
    power_output = area * efficiency * effective_irradiance_kw
    return power_output


def calculate_pv_energy_timeseries(utc_timestamps, area, efficiency, latitude, longitude, tilt_deg, azimuth_deg):
    power = [
        simulate_pv_power(
            utc_timestamp=utc_timestamp,
            area=area,
            efficiency=efficiency,
            latitude=latitude,
            longitude=longitude,
            tilt_deg=tilt_deg,
            azimuth_deg=azimuth_deg,
        )
        for utc_timestamp in utc_timestamps
    ]

    return convert_power_to_energy(power, utc_timestamps)
