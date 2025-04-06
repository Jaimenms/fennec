from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec import tariffs
from fennec.utils import get_utc_timestamps
from fennec.utils import convert_list_to_dict as convert
from fennec.fennec import run
from fennec.utils import convert_power_to_energy, get_detailed_results
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
    pv_efficiency = 0.2 # -
    pv_tilt_deg = 35 # deg
    pv_azimuth_deg = 180 # deg
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

    # Battery Parameters
    bat_index = 'BAT01'
    bat_charging_power = 4.0
    bat_discharging_power = 4.0
    bat_capacity = 6
    bat_soc_initial = 75
    bat_charging_efficiency = 0.95
    bat_discharging_efficiency = 0.95
    bat_charging_energy_limit = convert_power_to_energy(bat_charging_power, delta_t=delta_t)
    bat_discharging_energy_limit = convert_power_to_energy(bat_discharging_power, delta_t=delta_t)

    # Battery Controller Parameters
    controller_index = 'CONT01'
    controller_max_commands = 1
    controller_command_penalty = 0.01
    controller_soc_specifications = ([0.0] * len(utc_timestamps)) [:-1] + [80.0]
    controller_node_index = ['PV01', 'LOAD01']
    controller_battery_index = ['BAT01']
    controller_solar_surplus = [max(0.0, + pv_energy_i - load_energy_i) for pv_energy_i, load_energy_i in zip(pv_energy_timeseries, house_load_energy_timeseries)],
    controller_solar_deficit = [max(0.0, - pv_energy_i + load_energy_i) for pv_energy_i, load_energy_i in zip(pv_energy_timeseries, house_load_energy_timeseries)],

    data = {
        None: {  # The key None tells Pyomo that these data items are for the top-level model.
            't': {None: [i for i, _ in enumerate(utc_timestamps)]},
            'nodeIndex': {None: [pv_index, load_index]},
            'storageIndex': {None: [bat_index]},
            'storageControllerIndex': {None: [controller_index]},
            'grid': {
                'energy_limit': {None: grid_energy_limit},
                'tariff_energy_from': convert(tariff_energy_from_timeseries),
                'tariff_energy_to': convert(tariff_energy_to_timeseries),
            },
            'node': {
                pv_index: {
                    'energy_from': convert(pv_energy_timeseries)
                },
                load_index: {
                    'energy_to': convert(house_load_energy_timeseries)
                }
            },
            'storage': {
                bat_index: {
                    'capacity': {None: bat_capacity},
                    'charging_efficiency': {None: bat_charging_efficiency},
                    'discharging_efficiency': {None: bat_discharging_efficiency},
                    'soc_initial': {None: bat_soc_initial},
                    'energy_to_limit': {None: bat_charging_energy_limit},
                    'energy_from_limit': {None: bat_discharging_energy_limit},
                }
            },
            'storageController': {
                controller_index: {
                    'max_commands': {None: controller_max_commands},
                    'command_penalty': {None: controller_command_penalty},
                    'nodeIndex': {None: controller_node_index},
                    'storageIndex': {None: controller_battery_index},
                    'soc_specifications': convert(controller_soc_specifications),
                    'solar_surplus': convert(controller_solar_surplus),
                    'solar_deficit': convert(controller_solar_deficit),
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


    detailed_results = get_detailed_results(results, instance)

    # Output:
    for ti in instance.t:
        print(f"t={ti:3.0f}, ch={_v(instance.storage['BAT01'].charge, ti)}, dch={_v(instance.storage['BAT01'].discharge, ti)}, ss={_v(instance.storageController['CONT01'].solar_surplus, ti)}, sd={_v(instance.storageController['CONT01'].solar_deficit, ti)} fob:grid/pv/bat/cont={_v(instance.grid.fob, ti)}/{_v(instance.node['PV01'].fob, ti)}/{_v(instance.storage['BAT01'].fob, ti)}/{_v(instance.storageController['CONT01'].fob, ti)},  flag_arbitrage={_v(instance.storageController['CONT01'].flag_arbitrage, ti)}, charge_sc={_v(instance.storageController['CONT01'].charge_sc, ti)},discharge_sc={_v(instance.storageController['CONT01'].discharge_sc, ti)}, charge_arbitrage={_v(instance.storageController['CONT01'].charge_arbitrage, ti)}, discharge_arbitrage={_v(instance.storageController['CONT01'].discharge_arbitrage, ti)}, soc={_v(instance.storage['BAT01'].soc, ti)}, load={_v(instance.node['LOAD01'].energy_to, ti)}, bat_to={_v(instance.storage['BAT01'].energy_to, ti)}, pv_from={_v(instance.node['PV01'].energy_from, ti)}, grid_from={_v(instance.grid.energy_from, ti)}, bat_from={_v(instance.storage['BAT01'].energy_from, ti)}")
