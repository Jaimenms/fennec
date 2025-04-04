from typing import List
from datetime import datetime, timezone
from .utils import convert_power_to_energy, calculate_pv_power, calculate_house_load_power
from .tariffs import Tariff, export_none_tariff, import_bi_daily_tariff


def get_grid_data(
    utc_timestamps: List[float],
    contracted_power: float = 6.75,  # in kW
    tariff_export: Tariff = export_none_tariff,
    tariff_import: Tariff = import_bi_daily_tariff,
):
    """

    :param utc_timestamps:
    :param contracted_power:
    :param tariff_export:
    :param tariff_import:
    :return:
    """

    tariff_energy_to = [tariff_export(datetime.fromtimestamp(ti, tz=timezone.utc)) for ti in utc_timestamps]
    tariff_energy_from = [tariff_import(datetime.fromtimestamp(ti, tz=timezone.utc)) for ti in utc_timestamps]

    grid_energy_limit = convert_power_to_energy(contracted_power, utc_timestamps)

    return {
        'energy_limit': {None: grid_energy_limit},
        'tariff_energy_from': {i: v for i, v in enumerate(tariff_energy_from)},
        'tariff_energy_to': {i: v for i, v in enumerate(tariff_energy_to)},
    }


def get_pv_data(
    utc_timestamps: List[float],
    pv_area: float,
    efficiency: float,
    latitude: float,
    longitude: float,
    tilt_deg: float,
    azimuth_deg: float,
):
    """

    :param utc_timestamps:
    :param pv_area:
    :param efficiency:
    :param latitude:
    :param longitude:
    :param tilt_deg:
    :param azimuth_deg:
    :return:
    """

    # TODO - Add a parameter that could consider the effect of clouds
    power = [
        calculate_pv_power(
            utc_timestamp=utc_timestamp,
            area=pv_area,
            efficiency=efficiency,
            latitude=latitude,
            longitude=longitude,
            tilt_deg=tilt_deg,
            azimuth_deg=azimuth_deg,
        )
        for utc_timestamp in utc_timestamps
    ]

    energy = convert_power_to_energy(power, utc_timestamps)

    return {'energy_from': {i: v for i, v in enumerate(energy)}}


def get_load_data(
    utc_timestamps: List[float],
    house_area: float,
    num_residents: int,
    longitude: float
):

    power = [
        calculate_house_load_power(
            utc_timestamp=utc_timestamp, area=house_area, num_residents=num_residents, longitude=longitude
        )
        for utc_timestamp in utc_timestamps
    ]

    energy = convert_power_to_energy(power, utc_timestamps)

    return {'energy_to': {i: v for i, v in enumerate(energy)}}
