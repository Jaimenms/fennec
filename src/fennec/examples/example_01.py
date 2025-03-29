from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec import blocks, models, tariffs
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
    bat_soc_specifications = [(len(utc_timestamps) - 1, 50)]
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
    grid = blocks.GridBlock(
        name="Grid",
        energy_limit=grid_energy_limit,
        tariff_energy_to=tariff_energy_to,
        tariff_energy_from=tariff_energy_from,
        is_settled=grid_is_settled,
    )

    pv = blocks.PhotovoltaicBlock(
        name="Photovoltaic",
        pv_energy=pv_energy  # timestamps in seconds
    )

    bat_charging_energy_limit = convert_power_to_energy([bat_charging_power,] * len(utc_timestamps), utc_timestamps)
    bat_discharging_energy_limit = convert_power_to_energy([bat_discharging_power,] * len(utc_timestamps), utc_timestamps)
    bat = blocks.FixedBatteryBlock(
        name="Battery",
        charging_energy_limit=bat_charging_energy_limit,
        discharging_energy_limit=bat_discharging_energy_limit,
        capacity=bat_capacity,
        soc_0=bat_soc_0,
        soc_specifications=bat_soc_specifications,
        charging_efficiency=bat_charging_efficiency,
        discharging_efficiency=bat_discharging_efficiency,
        command_penalty=bat_command_penalty,
        load_energy=load_energy,
        pv_energy=pv_energy
    )

    model = models.SmartHome(
        name="House",
        load_energy=load_energy,
        grid=grid,
        pv=pv,
        bat=[bat,]
    )

    model.display()

    solver = pyo.SolverFactory("appsi_highs")
    solver.options["mip_abs_gap"] = 0.0001
    solver.options["mip_rel_gap"] = 0.001
    solver.options["time_limit"] = 20
    # solver.options["log_file"] = 'output.log'

    print(print(solver.available()))
    results = solver.solve(model, tee=False)

    # 6) Display results
    print("Solver Status:", results.solver.status)
    print("Termination Condition:", results.solver.termination_condition)
    print(f"Objective Value = {model.obj():.2f}")

    def _v(x, i):
        try:
            return f"{round(pyo.value(x[i]), 3):5.3f}"
        except:
            return "  N/A"

    # Output:
    for ti in model.t:
        print(f"t={ti:3.0f}, fob:grid/pv/bat={_v(model.grid.fob, ti)}/{_v(model.pv.fob, ti)}/{_v(model.bat[0].fob, ti)},  m/u/v/x/z={_v(model.bat[0].m, ti)}/{_v(model.bat[0].u, ti)}/{_v(model.bat[0].v, ti)}/{_v(model.bat[0].x, ti)}/{_v(model.bat[0].z, ti)}, soc={_v(model.bat[0].soc, ti)}, load={_v(model.load_energy, ti)}, grid_to={_v(model.grid.energy_to, ti)}, bat_to={_v(model.bat[0].energy_to, ti)}, grid_from={_v(model.grid.energy_from, ti)}, pv_from={_v(model.pv.energy_from, ti)}, bat_from={_v(model.bat[0].energy_from, ti)}")
