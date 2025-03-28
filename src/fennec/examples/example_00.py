from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec import blocks, models, tariffs
from fennec.utils import calculate_house_load_power, calculate_pv_power


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

    grid = blocks.GridBlock(
        timestamps=utc_timestamps,
        tariff_energy_to=tariff_energy_to,
        tariff_energy_from=tariff_energy_from,
        is_settled=grid_is_settled,
        contracted_power=grid_contracted_power,
    )

    pv = blocks.PhotovoltaicBlock(
        timestamps=utc_timestamps,
        pv_power=pv_power  # timestamps in seconds
    )
    model = models.House(
        name="House",
        timestamps=utc_timestamps,
        load_power=load_power,
        grid=grid,
        pv=pv
    )

    solver = pyo.SolverFactory("appsi_highs")

    if not solver.available():
        print("Solver not available")
        exit(1)

    results = solver.solve(model, tee=False)

    print("Solver Status:", results.solver.status)
    print("Termination Condition:", results.solver.termination_condition)
    print(f"Objective Value = {model.obj():.2f}")

    _v = lambda x, i: f"{round(pyo.value(x[i]), 3):7.3f}"

    # Output:
    for ti in model.t:
        print(f"t={ti:3.0f}, load_energy={_v(model.load_energy, ti)}, grid_energy_from={_v(model.grid.energy_from, ti)}, pv_energy_from={_v(model.pv.energy_from, ti)}, grid_energy_to={_v(model.grid.energy_to, ti)}")
