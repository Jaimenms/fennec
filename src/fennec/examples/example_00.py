from datetime import datetime, timezone

import pyomo.environ as pyo

from fennec import tariffs, get_grid_data, get_pv_data, get_load_data
from fennec.fennec import run
from fennec.utils import get_detailed_results


def get_data():

    # Sample period in seconds
    delta_t = 15 * 60

    # Start and End Dates
    start_dt = datetime(2025, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2025, 3, 23, 12, 0, 0, tzinfo=timezone.utc)

    # Timestamp list in seconds
    utc_timestamps = [
        start_dt.timestamp() + i * delta_t for i in range(int((end_dt - start_dt).total_seconds() / delta_t))
    ]

    ##### House Parameters
    house_area = 100  # in m²
    num_residents = 4  # number of residents
    latitude = +41.2089  # degrees
    longitude = -8.6143  # degrees

    #### PV Parameters
    pv_area = 8.0  # m2
    pv_efficiency = 0.2 # -
    pv_tilt_deg = 35 # deg
    pv_azimuth_deg = 180 # deg

    ### Energy Grid Parameters
    grid_contracted_power = 6.75  # in kW
    grid_tariff_export = tariffs.export_none_tariff
    grid_tariff_import = tariffs.import_bi_daily_tariff

    # The following data dictionary has a strange structure that was actually defined in Pyomo as a
    # data object to specify data to an Abstract Model.
    # This None key means that data items are for the top-level model
    data = {
        None: {
            't': {None: [i for i, _ in enumerate(utc_timestamps)]},
            'nodeIndex': {None: ['PV01', 'LOAD01']},
            'grid': get_grid_data(
                utc_timestamps=utc_timestamps,
                contracted_power=grid_contracted_power,
                tariff_export=grid_tariff_export,
                tariff_import=grid_tariff_import,
            ),
            'node': {
                'PV01': get_pv_data(
                    utc_timestamps=utc_timestamps,
                    pv_area=pv_area,
                    efficiency=pv_efficiency,
                    latitude=latitude,
                    longitude=longitude,
                    tilt_deg=pv_tilt_deg,
                    azimuth_deg=pv_azimuth_deg,
                ),
                'LOAD01': get_load_data(
                    utc_timestamps=utc_timestamps,
                    house_area=house_area,
                    num_residents=num_residents,
                    longitude=longitude
                ),
            },
        }
    }

    return data


if __name__ == "__main__":


    data = get_data()

    results, instance = run(data)

    detailed_results = get_detailed_results(results, instance)

    _v = lambda x, i: f"{round(pyo.value(x[i]), 3):7.3f}"

    # Output:
    for ti in instance.t:
        print(f"t={ti:3.0f}, load_energy={_v(instance.node['LOAD01'].energy_to, ti)}, pv_energy_from={_v(instance.node['PV01'].energy_from, ti)}, grid_energy_from={_v(instance.grid.energy_from, ti)}, grid_energy_to={_v(instance.grid.energy_to, ti)}")
