from datetime import datetime, timezone
from ..utils import convert_power_to_energy


def simulate_house_load_power(utc_timestamp, area, num_residents, longitude):
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


def calculate_house_load_energy_timeseries(utc_timestamps, area, num_residents, longitude):
    power = [
        simulate_house_load_power(
            utc_timestamp=utc_timestamp, area=area, num_residents=num_residents, longitude=longitude
        )
        for utc_timestamp in utc_timestamps
    ]

    return convert_power_to_energy(power, utc_timestamps)
