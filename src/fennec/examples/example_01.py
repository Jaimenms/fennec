from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec import tariffs
from fennec.fennec import run
from fennec.utils import calculate_house_load_power, calculate_pv_power, convert_power_to_energy


def get_data():

    start_dt = datetime(2025, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2025, 3, 23, 12, 0, 0, tzinfo=timezone.utc)
    delta_t = 15 * 60  # in seconds

    utc_timestamps = [
        start_dt.timestamp() + i * delta_t for i in range(int((end_dt - start_dt).total_seconds() / delta_t))
    ]
    house_area = 100  # in m²
    num_residents = 4  # number of residents
    latitude = +41.2089  # degrees
    longitude = -8.6143  # degrees
    pv_irradiance = 1.0
    pv_area = 8.0  # m2
    pv_efficiency = 0.2
    pv_tilt_deg = 35
    pv_azimuth_deg = 180
    grid_is_settled = True
    grid_contracted_power = 13  # in kW
    grid_tariff_export = tariffs.export_none_tariff
    grid_tariff_import = tariffs.import_bi_daily_tariff
    bat_charging_power = 4.0
    bat_discharging_power = 4.0
    bat_capacity = 6
    bat_soc_intial = 50
    bat_soc_specifications = ([0.0] * len(utc_timestamps)) [:-1] + [80.0]
    bat_charging_efficiency = 0.95
    bat_discharging_efficiency = 0.95
    bat_command_penalty = [0.1,] * len(utc_timestamps)
    tariff_energy_to = [grid_tariff_export(datetime.fromtimestamp(ti, tz=timezone.utc)) for ti in utc_timestamps]
    tariff_energy_from = [grid_tariff_import(datetime.fromtimestamp(ti, tz=timezone.utc)) for ti in utc_timestamps]

    load_power = [
        calculate_house_load_power(
            utc_timestamp=utc_timestamp, area=house_area, num_residents=num_residents, longitude=longitude
        )
        for utc_timestamp in utc_timestamps
    ]
    load_energy = convert_power_to_energy(load_power, utc_timestamps)

    pv_power = [
        calculate_pv_power(
            utc_timestamp=utc_timestamp,
            area=pv_area,
            efficiency=pv_efficiency,
            latitude=latitude,
            longitude=longitude,
            tilt_deg=pv_tilt_deg,
            azimuth_deg=pv_azimuth_deg,
        )
        for utc_timestamp in utc_timestamps
    ]
    pv_energy = convert_power_to_energy(pv_power, utc_timestamps)

    grid_energy_limit = convert_power_to_energy(grid_contracted_power, utc_timestamps)
    bat_charging_energy_limit = convert_power_to_energy(bat_charging_power, utc_timestamps)
    bat_discharging_energy_limit = convert_power_to_energy(bat_discharging_power, utc_timestamps)

    data = {
        None: {  # The key None tells Pyomo that these data items are for the top-level model.
            't': {None: [i for i, _ in enumerate(utc_timestamps)]},
            'nodeIndex': {None: ['PV01', 'LOAD01']},
            'storageIndex': {None: ['BAT01']},
            'storageControllerIndex': {None: ['CONT01']},
            'grid': {
                'energy_limit': {None: grid_energy_limit},
                'tariff_energy_from': {i: v for i, v in enumerate(tariff_energy_from)},
                'tariff_energy_to': {i: v for i, v in enumerate(tariff_energy_to)},
            },
            'node': {
                'PV01': {
                    'energy_from': {i: v for i, v in enumerate(pv_energy)},
                },
                'LOAD01': {
                    'energy_to': {i: v for i, v in enumerate(load_energy)},
                },
            },
            'storage': {
                'BAT01': {
                    'capacity': {None: bat_capacity},
                    'charging_efficiency': {None: bat_charging_efficiency},
                    'discharging_efficiency': {None: bat_discharging_efficiency},
                    'soc_initial': {None: bat_soc_intial},
                    'energy_to_limit': {None: bat_charging_energy_limit},
                    'energy_from_limit': {None: bat_discharging_energy_limit},
                }
            },
            'storageController': {
                'CONT01': {
                    'max_commands': {None: 4},
                    'nodeIndex': {None: ['PV01', 'LOAD01']},
                    'storageIndex': {None: ['BAT01']},
                    'command_penalty': {i: v for i, v in enumerate(bat_command_penalty)},
                    'soc_specifications': {i: v for i, v in enumerate(bat_soc_specifications)},
                }
            }
        }
    }

    return data


if __name__ == "__main__":

    data = get_data()

    results, instance = run(data)

    def _v(x, i):
        try:
            return f"{round(pyo.value(x[i]), 3):5.3f}"
        except:
            return "  N/A"

    # Output:
    for ti in instance.t:
        print(f"t={ti:3.0f}, ch={_v(instance.storage['BAT01'].charge, ti)}, dch={_v(instance.storage['BAT01'].discharge, ti)}, ss={_v(instance.storageController['CONT01'].solar_surplus, ti)}({_v(instance.storageController['CONT01'].flag_surplus, ti)}), sd={_v(instance.storageController['CONT01'].solar_deficit, ti)} fob:grid/pv/bat/cont={_v(instance.grid.fob, ti)}/{_v(instance.node['PV01'].fob, ti)}/{_v(instance.storage['BAT01'].fob, ti)}/{_v(instance.storageController['CONT01'].fob, ti)},  flag_arbitrage={_v(instance.storageController['CONT01'].flag_arbitrage, ti)}, charge_sc={_v(instance.storageController['CONT01'].charge_sc, ti)},discharge_sc={_v(instance.storageController['CONT01'].discharge_sc, ti)}, charge_arbitrage={_v(instance.storageController['CONT01'].charge_arbitrage, ti)}, discharge_arbitrage={_v(instance.storageController['CONT01'].discharge_arbitrage, ti)}, soc={_v(instance.storage['BAT01'].soc, ti)}, load={_v(instance.node['LOAD01'].energy_to, ti)}, bat_to={_v(instance.storage['BAT01'].energy_to, ti)}, pv_from={_v(instance.node['PV01'].energy_from, ti)}, grid_from={_v(instance.grid.energy_from, ti)}, bat_from={_v(instance.storage['BAT01'].energy_from, ti)}")
