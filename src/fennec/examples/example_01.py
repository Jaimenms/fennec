# import logging
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec import models, tariffs
from fennec.utils import calculate_house_load_power, calculate_pv_power, convert_power_to_energy


if __name__ == "__main__":

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
    bat_soc_0 = 50
    bat_soc_specifications = [0.0] * len(utc_timestamps)
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

    grid_energy_limit = convert_power_to_energy([grid_contracted_power,] * len(utc_timestamps), utc_timestamps)
    bat_charging_energy_limit = convert_power_to_energy([bat_charging_power,] * len(utc_timestamps), utc_timestamps)
    bat_discharging_energy_limit = convert_power_to_energy([bat_discharging_power,] * len(utc_timestamps), utc_timestamps)

    # Solar Surplus condition in self-consumption mode will force battery charge
    solar_surplus = [max(0, pv_energy_i - load_energy_i) for load_energy_i, pv_energy_i in zip(load_energy, pv_energy)]
    solar_deficit = [max(0, load_energy_i - pv_energy_i) for load_energy_i, pv_energy_i in zip(load_energy, pv_energy)]


    model = models.SmartHome(is_grid_settled=True)

    data = {
        None: {  # The key None tells Pyomo that these data items are for the top-level model.
            't': {None: [i for i, _ in enumerate(utc_timestamps)]},
            'node_index': {None: ['PV', 'LOAD']},
            'intelligent_bat_index': {None: ['BAT']},
            'grid': {
                'energy_limit': {i: v for i, v in enumerate(grid_energy_limit)},
                'tariff_energy_from': {i: v for i, v in enumerate(tariff_energy_from)},
                'tariff_energy_to': {i: v for i, v in enumerate(tariff_energy_to)},
            },
            'node': {
                'PV': {
                    'energy_from': {i: v for i, v in enumerate(pv_energy)},
                },
                'LOAD': {
                    'energy_to': {i: v for i, v in enumerate(load_energy)},
                },
            },
            'intelligent_bat': {
                'BAT': {
                    'energy_to_limit': {i: v for i, v in enumerate(bat_charging_energy_limit)},
                    'energy_from_limit': {i: v for i, v in enumerate(bat_discharging_energy_limit)},
                    'capacity': {None: bat_capacity},
                    'soc_0': {None: bat_soc_0},
                    'soc_specifications': {i: v for i, v in enumerate(bat_soc_specifications)},
                    'charging_efficiency': {None: bat_charging_efficiency},
                    'discharging_efficiency': {None: bat_discharging_efficiency},
                    'command_penalty': {i: v for i, v in enumerate(bat_command_penalty)},
                    'solar_surplus': {i: v for i, v in enumerate(solar_surplus)},
                    'solar_deficit': {i: v for i, v in enumerate(solar_deficit)},
                }
            }
        }
    }

    instance = model.create_instance(data)

    solver = pyo.SolverFactory("appsi_highs")
    solver.options["mip_abs_gap"] = 0.0001
    solver.options["mip_rel_gap"] = 0.001
    solver.options["time_limit"] = 20

    if not solver.available():
        print("Solver not available")
        exit(1)

    results = solver.solve(instance, tee=False)

    # 6) Display results
    print("Solver Status:", results.solver.status)
    print("Termination Condition:", results.solver.termination_condition)
    print(f"Objective Value = {instance.obj():.2f}")

    def _v(x, i):
        try:
            return f"{round(pyo.value(x[i]), 3):5.3f}"
        except:
            return "  N/A"

    # Output:
    for ti in instance.t:
        print(f"t={ti:3.0f}, fob:grid/pv/bat={_v(instance.grid.fob, ti)}/{_v(instance.node['PV'].fob, ti)}/{_v(instance.intelligent_bat['BAT'].fob, ti)},  m/u/v/x/z={_v(instance.intelligent_bat['BAT'].m, ti)}/{_v(instance.intelligent_bat['BAT'].u, ti)}/{_v(instance.intelligent_bat['BAT'].v, ti)}/{_v(instance.intelligent_bat['BAT'].x, ti)}/{_v(instance.intelligent_bat['BAT'].z, ti)}, soc={_v(instance.intelligent_bat['BAT'].soc, ti)}, load={_v(instance.node['LOAD'].energy_from, ti)}, grid_to={_v(instance.grid.energy_to, ti)}, bat_to={_v(instance.intelligent_bat['BAT'].energy_to, ti)}, pv_from={_v(instance.node['PV'].energy_from, ti)}, bat_from={_v(instance.intelligent_bat['BAT'].energy_from, ti)}")
