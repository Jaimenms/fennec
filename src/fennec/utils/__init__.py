import math
from datetime import datetime, timezone
from pysolar.solar import get_altitude, get_azimuth
from pysolar.radiation import get_radiation_direct


def convert_power_to_energy(power, timestamps):
    """
    Convert a list of power values (in kW) and timestamps (in seconds) to energy values (in kWh).
    :param power:
    :param timestamps:
    :return:
    """

    n = len(timestamps)

    delta_timestamps = [timestamps[i + 1] - timestamps[i] for i in range(n - 1)] + [
        timestamps[-1] - timestamps[-2]
    ]

    return [load_power_i * delta_timestamp_i / 3600 for delta_timestamp_i, load_power_i in zip(delta_timestamps, power)]


def calculate_house_load_power(utc_timestamp, area, num_residents, longitude):
    """
    Estimate the instantaneous electrical load (in kW) for a typical European household.

    The load model consists of:
      - A base load that scales with the house area.
      - An occupancy load that varies with the time of day and number of residents.

    Local solar time is computed using the UTC timestamp and the longitude:
        local_solar_time = (UTC time in hours + (longitude/15)) mod 24
    (Note: latitude is provided for completeness, although it is not used in this conversion.)

    Assumptions for occupancy load per resident:
        06:00 to 09:00 -> 0.5 kW  (morning peak)
        09:00 to 18:00 -> 0.3 kW  (daytime moderate usage)
        18:00 to 23:00 -> 0.7 kW  (evening peak)
        23:00 to 06:00 -> 0.2 kW  (night time low usage)

    The base load is assumed as:
        0.5 kW + 0.005 kW per square meter

    Parameters:
        utc_timestamp (float or int): UTC timestamp in seconds (epoch time)
        area (float): House area in square meters
        num_residents (int): Number of residents in the house
        latitude (float): Latitude in degrees (for potential future use)
        longitude (float): Longitude in degrees (east positive, west negative)

    Returns:
        float: Estimated instantaneous load in kW.
    """
    # Convert the UTC timestamp to a datetime object (UTC)
    dt_utc = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)

    # Calculate the fractional UTC hour (e.g., 13.25 for 13:15)
    utc_hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0

    # Compute local solar time using the longitude.
    # The Earth rotates 15° per hour, so each degree adds/subtracts 1/15 hour.
    local_solar_time = (utc_hour + (longitude / 15.0)) % 24

    # Base load (in kW): a fixed consumption plus an area-dependent component.
    base_load = 0.5 + 0.005 * area

    # Determine occupancy load per resident based on local solar time:
    if 6 <= local_solar_time < 9:
        occupancy_per_resident = 0.5  # morning peak
    elif 9 <= local_solar_time < 18:
        occupancy_per_resident = 0.3  # daytime
    elif 18 <= local_solar_time < 23:
        occupancy_per_resident = 0.7  # evening peak
    else:
        occupancy_per_resident = 0.2  # night time

    occupancy_load = num_residents * occupancy_per_resident

    # Total load is the sum of the base load and the occupancy load.
    total_load = base_load + occupancy_load
    return total_load


def calculate_pv_power(utc_timestamp, area, efficiency, latitude, longitude, tilt_deg, azimuth_deg):
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
