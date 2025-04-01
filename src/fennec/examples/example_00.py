# import logging
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec import models, tariffs
from fennec.utils import calculate_house_load_power, calculate_pv_power, convert_power_to_energy


if __name__ == "__main__":

    start_dt = datetime(2025, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2025, 3, 23, 12, 0, 0, tzinfo=timezone.utc)
    # end_dt = datetime(2025, 3, 22, 6, 0, 0, tzinfo=timezone.utc)
    delta_t = 15 * 60  # in seconds

    utc_timestamps = [
        start_dt.timestamp() + i * delta_t for i in range(int((end_dt - start_dt).total_seconds() / delta_t))
    ]
    n = len(utc_timestamps)
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
    grid_contracted_power = 6.75  # in kW
    grid_tariff_export = tariffs.export_none_tariff
    grid_tariff_import = tariffs.import_bi_daily_tariff
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

    model = models.SmartHome(is_grid_settled=True)

    data = {
        None: {  # The key None tells Pyomo that these data items are for the top-level model.
            't': {None: [i for i, _ in enumerate(utc_timestamps)]},
            'nodeIndex': {None: ['PV01', 'LOAD01']},
            'storageIndex': {None: []},
            'storageControllerIndex': {None: []},
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

    print("Solver Status:", results.solver.status)
    print("Termination Condition:", results.solver.termination_condition)
    print(f"Objective Value = {instance.obj():.2f}")

    _v = lambda x, i: f"{round(pyo.value(x[i]), 3):7.3f}"

    # Output:
    for ti in instance.t:
        print(f"t={ti:3.0f}, load_energy={_v(instance.node['LOAD01'].energy_to, ti)}, pv_energy_from={_v(instance.node['PV01'].energy_from, ti)}, grid_energy_from={_v(instance.grid.energy_from, ti)}, grid_energy_to={_v(instance.grid.energy_to, ti)}")
