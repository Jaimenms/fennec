from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec import tariffs
from fennec.fennec import run
from fennec.simulators.pv import calculate_pv_energy_timeseries
from fennec.simulators.load import calculate_house_load_energy_timeseries
from fennec.utils import get_utc_timestamps, convert_power_to_energy, get_positions_before_T, get_is_unplugged
from fennec.utils import convert_list_to_dict as convert


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

    # EV Parameters
    ev_index = 'EV01'
    ev_battery_capacity = 40.0
    ev_is_unplugged_from = '09:00'
    ev_is_unplugged_to = '13:00'
    ev_soc_initial = 40
    ev_soc_back_home = 50
    ev_charging_power = 2.0
    ev_charging_efficiency = 0.95
    ev_charging_energy_limit = convert_power_to_energy(ev_charging_power, utc_timestamps)

    # Controller Parameters
    controller_index = 'CONT01'
    controller_t_soc_objective_hour = '08:00'
    controller_soc_objective = 80.0
    controller_soc_min = 40
    controller_max_commands = 4
    controller_charge_objective_penalty = 0.5
    controller_node_index = ['PV01', 'LOAD01']
    controller_vehicle_index = ['EV01']
    controller_command_penalty = [0.001,] * len(utc_timestamps)

    data = {
        None: {  # The key None tells Pyomo that these data items are for the top-level model.
            't': {None: [i for i, _ in enumerate(utc_timestamps)]},
            'nodeIndex': {None: [pv_index, load_index]},
            'vehicleIndex': {None: [ev_index]},
            'vehicleControllerIndex': {None: [controller_index]},
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
            'vehicle': {
                ev_index: {
                    'capacity': {None: ev_battery_capacity},
                    'charging_efficiency': {None: ev_charging_efficiency},
                    'soc_initial': {None: ev_soc_initial},
                    'energy_to_limit': {None: ev_charging_energy_limit},
                    'is_plugged': {i: (1 - v) for i, v in
                                   enumerate(get_is_unplugged(utc_timestamps, ev_is_unplugged_from, ev_is_unplugged_to))},
                    't_soc_back_home': {
                        None: [i + 1 for i in get_positions_before_T(utc_timestamps, ev_is_unplugged_to)]},
                    'soc_back_home': {i + 1: ev_soc_back_home for i in
                                      get_positions_before_T(utc_timestamps, ev_is_unplugged_to)},
                }
            },
            'vehicleController': {
                controller_index: {
                    'nodeIndex': {None: controller_node_index},
                    'vehicleIndex': {None: controller_vehicle_index},
                    'max_commands': {None: controller_max_commands},
                    'command_penalty': convert(controller_command_penalty),
                    'charge_objective_penalty': {None: controller_charge_objective_penalty},
                    'soc_min': {None: controller_soc_min},
                    't_soc_objective': {None: get_positions_before_T(utc_timestamps, controller_t_soc_objective_hour)},
                    'soc_objective': {i: controller_soc_objective for i in
                                      get_positions_before_T(utc_timestamps, controller_t_soc_objective_hour)},
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
        print(f"t={ti:3.0f}, external_from={_v(instance.vehicle['EV01'].external_from, ti)},  fob:grid/pv/bat/cont={_v(instance.grid.fob, ti)}/{_v(instance.node['PV01'].fob, ti)}/{_v(instance.vehicle['EV01'].fob, ti)}/{_v(instance.vehicleController['CONT01'].fob, ti)}, charge_sc={_v(instance.vehicleController['CONT01'].charge, ti)}, soc={_v(instance.vehicle['EV01'].soc, ti)}, load={_v(instance.node['LOAD01'].energy_to, ti)}, bat_to={_v(instance.vehicle['EV01'].energy_to, ti)}, pv_from={_v(instance.node['PV01'].energy_from, ti)}, grid_from={_v(instance.grid.energy_from, ti)}")
