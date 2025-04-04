from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec import tariffs
from fennec.fennec import run
from fennec.utils import calculate_house_load_power, calculate_pv_power, convert_power_to_energy, get_positions_before_T, get_is_plugged


def get_data():

    start_dt = datetime(2025, 6, 22, 16, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2025, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    delta_t = 15 * 60  # in seconds

    utc_timestamps = [
        start_dt.timestamp() + i * delta_t for i in range(int((end_dt - start_dt).total_seconds() / delta_t))
    ]
    house_area = 10  # in m²
    num_residents = 1  # number of residents
    latitude = +41.2089  # degrees
    longitude = -8.6143  # degrees
    pv_area = 20.0  # m2
    pv_efficiency = 0.2
    pv_tilt_deg = 35
    pv_azimuth_deg = 180
    grid_contracted_power = 6.75  # in kW
    grid_tariff_export = tariffs.export_none_tariff
    grid_tariff_import = tariffs.import_bi_daily_tariff
    ev_battery_capacity = 40.0
    ev_t_soc_objective_hour = '08:00'
    ev_is_unplugged_from = '09:00'
    ev_is_unplugged_to = '13:00'
    ev_energy_consumed_when_unplugged = 0.2*ev_battery_capacity/(7*4)
    ev_soc_initial = 40
    ev_soc_min = 40
    ev_soc_back_home = 50
    ev_soc_objective = 80
    ev_charging_power = 2.0
    ev_charging_efficiency = 0.95
    ev_command_penalty = [0.001,] * len(utc_timestamps)
    ev_charge_objective_penalty = 0.5
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
    ev_charging_energy_limit = convert_power_to_energy(ev_charging_power, utc_timestamps)

    data = {
        None: {  # The key None tells Pyomo that these data items are for the top-level model.
            't': {None: [i for i, _ in enumerate(utc_timestamps)]},
            'nodeIndex': {None: ['PV01', 'LOAD01']},
            'vehicleIndex': {None: ['EV01']},
            'vehicleControllerIndex': {None: ['CONT01']},
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
            'vehicle': {
                'EV01': {
                    'capacity': {None: ev_battery_capacity},
                    'charging_efficiency': {None: ev_charging_efficiency},
                    'soc_initial': {None: ev_soc_initial},
                    'energy_to_limit': {None: ev_charging_energy_limit},
                    'is_plugged': {i: (1-v) for i, v in enumerate(get_is_plugged(utc_timestamps, ev_is_unplugged_from, ev_is_unplugged_to))},
                    't_soc_back_home': {None: [i+1 for i in get_positions_before_T(utc_timestamps, ev_is_unplugged_to)]},
                    'soc_back_home': {i+1: ev_soc_back_home for i in get_positions_before_T(utc_timestamps, ev_is_unplugged_to)},
                    # 'external_from': {i: (v*ev_energy_consumed_when_unplugged) for i, v in enumerate(get_is_plugged(utc_timestamps, ev_is_unplugged_from, ev_is_unplugged_to))},
                }
            },
            'vehicleController': {
                'CONT01': {
                    'nodeIndex': {None: ['PV01', 'LOAD01']},
                    'vehicleIndex': {None: ['EV01']},
                    'max_commands': {None: 4},
                    'soc_min': {None: ev_soc_min},
                    't_soc_objective': {None: get_positions_before_T(utc_timestamps, ev_t_soc_objective_hour)},
                    'soc_objective': {i: ev_soc_objective for i in get_positions_before_T(utc_timestamps, ev_t_soc_objective_hour)},
                    'charge_objective_penalty': {None: ev_charge_objective_penalty},
                    'command_penalty': {i: v for i, v in enumerate(ev_command_penalty)},
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
