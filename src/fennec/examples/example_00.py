from datetime import datetime, timezone

import pyomo.environ as pyo

from fennec import tariffs
from fennec.fennec import run
from fennec.utils import convert_power_to_energy, get_utc_timestamps
from fennec.utils import convert_list_to_dict as convert
from fennec.simulators.pv import calculate_pv_energy_timeseries
from fennec.simulators.load import calculate_house_load_energy_timeseries


def get_data():

    # Sample period in seconds
    delta_t = 15 * 60

    # Start and End Dates
    start_dt = datetime(2025, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2025, 3, 23, 12, 0, 0, tzinfo=timezone.utc)

    # Timestamp list in seconds
    utc_timestamps = get_utc_timestamps(start_dt, end_dt, delta_t)

    # House Parameters
    load_index = 'LOAD01'
    house_area = 100  # in m²
    num_residents = 4  # number of residents
    latitude = +41.2089  # degrees
    longitude = -8.6143  # degrees
    house_load_energy_timeseries = calculate_house_load_energy_timeseries(
        utc_timestamps=utc_timestamps,
        area=house_area,
        num_residents=num_residents,
        longitude=longitude
    )

    # PV Parameters
    pv_index = 'PV01'
    pv_area = 8.0  # m2
    pv_efficiency = 0.2  # -
    pv_tilt_deg = 35  # deg
    pv_azimuth_deg = 180  # deg
    pv_energy_timeseries = calculate_pv_energy_timeseries(
        utc_timestamps=utc_timestamps,
        area=pv_area,
        efficiency=pv_efficiency,
        latitude=latitude,
        longitude=longitude,
        tilt_deg=pv_tilt_deg,
        azimuth_deg=pv_azimuth_deg
    )

    # Grid Parameters
    grid_contracted_power = 6.75  # in kW
    grid_tariff_export = tariffs.export_none_tariff
    grid_tariff_import = tariffs.import_bi_daily_tariff
    grid_energy_limit = convert_power_to_energy(grid_contracted_power, delta_t=delta_t)
    tariff_energy_from_timeseries = grid_tariff_export.calculate_timeseries(utc_timestamps)
    tariff_energy_to_timeseries = grid_tariff_import.calculate_timeseries(utc_timestamps)

    # The following data dictionary has a strange structure that was actually defined in Pyomo as a
    # data object to specify data to an Abstract Model.
    # This None key means that data items are for the top-level model
    data = {
        None: {
            't': {None: [i for i, _ in enumerate(utc_timestamps)]},
            'nodeIndex': {None: [pv_index, load_index]},
            'grid': {
                'energy_limit': {None: grid_energy_limit},
                'tariff_energy_from': convert(tariff_energy_from_timeseries),
                'tariff_energy_to': convert(tariff_energy_to_timeseries),
            },
            'node': {
                'PV01': {
                    'energy_from': convert(pv_energy_timeseries)
                },
                'LOAD01': {
                    'energy_to': convert(house_load_energy_timeseries)
                }
            },
        }
    }

    return data


if __name__ == "__main__":


    data = get_data()

    results, instance = run(data)

    _v = lambda x, i: f"{round(pyo.value(x[i]), 3):7.3f}"

    # Output:
    for ti in instance.t:
        print(f"t={ti:3.0f}, load_energy={_v(instance.node['LOAD01'].energy_to, ti)}, pv_energy_from={_v(instance.node['PV01'].energy_from, ti)}, grid_energy_from={_v(instance.grid.energy_from, ti)}, grid_energy_to={_v(instance.grid.energy_to, ti)}")
