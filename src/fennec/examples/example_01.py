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
    grid_tariff_export = tariffs.export_none
    grid_tariff_import = tariffs.import_bi_daily_tariff
    ev_battery_capacity = 40.0
    ev_plugged = [1.0,] * len(utc_timestamps)
    ev_threshold_soc = 30
    ev_initial_soc = 20
    ev_final_soc = 80
    ev_charging_power = 2.0
    ev_is_power_variable = False
    ev_charging_efficiency = 0.95
    ev_command_penalty = [0.001,] * len(utc_timestamps)
    bat_charging_power = 4.0
    bat_discharging_power = 4.0
    bat_capacity = 6
    bat_initial_soc = 25
    bat_final_soc = 30
    bat_threshold_soc = None
    bat_threshold_index = None
    bat_charging_efficiency = 0.95
    bat_discharging_efficiency = 0.95
    bat_command_penalty = [0.001,] * len(utc_timestamps)
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

    ev = blocks.VehicleBatteryBlock(
        timestamps=utc_timestamps,
        is_available=[True,] * len(utc_timestamps),
        charging_power=ev_charging_power,
        capacity=ev_battery_capacity,
        initial_soc=ev_initial_soc,
        final_soc=ev_final_soc,
        threshold_soc=None,
        threshold_index=None,
        charging_efficiency=ev_charging_efficiency,
        command_penalty=ev_command_penalty,
    )

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

    bat = blocks.FixedBatteryBlock(
        timestamps=utc_timestamps,
        charging_power=bat_charging_power,
        discharging_power=bat_discharging_power,
        capacity=bat_capacity,
        initial_soc=bat_initial_soc,
        final_soc=bat_final_soc,
        threshold_soc=bat_threshold_soc,
        threshold_index=bat_threshold_index,
        charging_efficiency=bat_charging_efficiency,
        discharging_efficiency=bat_discharging_efficiency,
        command_penalty=bat_command_penalty,
    )

    model = models.House(
        timestamps=utc_timestamps,
        load_power=load_power,
        grid=grid,
        pv=pv,
        ev=ev,
        bat=bat
    )

    solver = pyo.SolverFactory("appsi_highs")

    print(print(solver.available()))
    results = solver.solve(model, tee=False)

    # 6) Display results
    print("Solver Status:", results.solver.status)
    print("Termination Condition:", results.solver.termination_condition)

    print(f"Objective Value = {model.obj():.2f}")
