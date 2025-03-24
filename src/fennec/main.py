from datetime import datetime, timezone

import pyomo.environ as pyo
from fennec.tariffs import export_none_tariff, import_bi_daily_tariff
from fennec.utils import calculate_house_load_power, calculate_pv_power
from fennec.house import House



if __name__ == "__main__":

    start_dt = datetime(2025, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2025, 3, 23, 12, 0, 0, tzinfo=timezone.utc)
    delta_t = 15 * 60 # in seconds

    utc_timestamps = [start_dt.timestamp() + i*delta_t for i in range(int((end_dt - start_dt).total_seconds()/delta_t))]
    delta_timestamps = [utc_timestamps[i+1] - utc_timestamps[i] for i in range(len(utc_timestamps)-1)] + [utc_timestamps[-1] - utc_timestamps[-2]]

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
    grid_contracted_power = 6.75  # in kW,
    ev_battery_capacity = 40.0
    ev_plugged = [1.0, ] * len(t)
    ev_threshold_soc = 30
    ev_initial_soc = 20
    ev_final_soc = 80
    ev_charging_power = 2.0
    ev_is_power_variable = False
    ev_charging_efficiency = 0.95

    load_power = [
        calculate_house_load_power(
            utc_timestamp=utc_timestamp,
            area=house_area,
            num_residents=num_residents,
            longitude=longitude
        ) for utc_timestamp in utc_timestamps
    ]

    pv_power = [
        calculate_pv_power(
            utc_timestamp=utc_timestamp,
            area=pv_area,
            efficiency=pv_efficiency,
            latitude=latitude,
            longitude=longitude,
            tilt_deg=pv_tilt_deg,
            azimuth_deg=pv_azimuth_deg
        )
        for utc_timestamp in utc_timestamps
    ]

    model = House.construct_house_with_pv_and_ev(
        name="house",
        utc_timestamps=utc_timestamps,
        delta_timestamps=delta_timestamps,

        load_power=load_power,
        pv_power=pv_power,

        grid_tariff_export=export_none_tariff,
        grid_tariff_import=import_bi_daily_tariff,
        grid_is_settled=grid_is_settled,
        grid_contracted_power=grid_contracted_power,  # in kW,

        ev_plugged=ev_plugged,
        ev_battery_capacity=ev_battery_capacity,
        ev_threshold_soc=ev_threshold_soc,
        ev_initial_soc=ev_initial_soc,
        ev_final_soc=ev_final_soc,
        ev_charging_power=ev_charging_power,
        ev_is_power_variable=ev_is_power_variable,
        ev_charging_efficiency=ev_charging_efficiency,
    )

    solver = pyo.SolverFactory('appsi_highs')

    print(print(solver.available()))
    results = solver.solve(model, tee=False)

    # 6) Display results
    print("Solver Status:", results.solver.status)
    print("Termination Condition:", results.solver.termination_condition)

    print(f"Objective Value = {model.obj():.2f}")
