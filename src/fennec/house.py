from typing import Optional, List
from datetime import datetime, timezone

import pyomo.environ as pyo
from .blocks import Grid, ElectricalVehicle, PhotovoltaicPanel, Battery
from . import tariffs


class House(pyo.ConcreteModel):

    def __init__(
            self,
            t_set: pyo.Set,
            delta_timestamps: List[float],
            load_power: List[float],
            name: str = "house",
            grid: Optional[Grid] = pyo.Block(),
            pv: Optional[PhotovoltaicPanel] = pyo.Block(),
            ev: Optional[ElectricalVehicle] = pyo.Block(),
            bat: Optional[Battery] = pyo.Block(),

    ):

        model = super().__init__(name=name)

        model.t = t_set
        model.grid = grid
        model.pv = pv
        model.ev = ev
        model.bat = bat

        def balance_rule(m: pyo.Model, t):

            energy_to_grid = m.grid.energy_to[t] if m.grid else 0
            load = m.load[t]
            energy_from_grid = m.grid.energy_from[t] if m.grid else 0
            energy_from_pv = m.pv.energy_from[t] if m.pv else 0
            energy_to_ev = m.ev.energy_to[t] if m.ev else 0

            return energy_to_grid + load + energy_to_ev == energy_from_grid + energy_from_pv


        def objective_rule(m: pyo.Model, t):

            grid_fob = m.grid.fob[t] if hasattr(m.grid, 'fob') else 0
            pv_fob = m.pv.fob[t] if hasattr(m.pv, 'fob') else 0
            ev_fob = m.ev.fob[t] if hasattr(m.ev, 'fob') else 0
            bat_fob = m.bat.fob[t] if hasattr(m.bat, 'fob') else 0

            return grid_fob + pv_fob + ev_fob + bat_fob

        """
        M = 10.0
        
        # Pre-calculate delta[t] = max(0, forecast_load[t] - forecast_solar[t])
        solar_surplus = [max(0, forecast_solar[t] - forecast_load[t] ) for t in time_periods]
        solar_deficit = [max(0, forecast_load[t] - forecast_solar[t]) for t in time_periods]
        
        for t in time_periods[0:]:
            h.addConstr(u[t] * (eta * P_charge * delta_t) <= solar_surplus[t] + M * m[t],
                        name="u_control_1_%d" % t)
            h.addConstr(v[t] * (inv_eta * P_discharge * delta_t) <= solar_deficit[t] + M * m[t],
                        name="v_control_1_%d" % t)
        
            h.addConstr(u[t] * (eta * P_charge * delta_t) >= solar_surplus[t] - M * m[t],
                        name="u_control_3_%d" % t)
            h.addConstr(v[t] * (inv_eta * P_discharge * delta_t) >= solar_deficit[t] - M * m[t],
                        name="v_control_3_%d" % t)
        
        """


        model.load = pyo.Param(t_set, initialize={i: load_power_i * delta_timestamp_i/3600 for i, (delta_timestamp_i, load_power_i) in enumerate(zip(delta_timestamps, load_power))})
        model.obj = pyo.Objective(rule=objective_rule, sense=pyo.minimize)
        model.balance = pyo.Constraint(model.t, rule=balance_rule)



    @staticmethod
    def construct_house_with_pv_and_ev(
            name: str,
            utc_timestamps: List[float],  # t index
            delta_timestamps: List[float],  # in seconds

            load_power: List[float],
            pv_power: List[float],

            grid_tariff_export: tariffs.Tariff,
            grid_tariff_import: tariffs.Tariff,
            grid_is_settled: bool,
            grid_contracted_power: float,  # in kW,

            ev_plugged: List[float],
            ev_battery_capacity: float,
            ev_threshold_soc: float,
            ev_initial_soc: float,
            ev_final_soc: float,
            ev_charging_power: float,
            ev_is_power_variable: bool,
            ev_charging_efficiency: float,

    ):

        assert len(utc_timestamps) == len(load_power), "The length of t and load_power must be the same."
        assert len(utc_timestamps) == len(pv_power), "The length of t and pv_power must be the same."

        t = [i for i in range(len(utc_timestamps))]

        t_set = pyo.Set(initialize=t)

        ev = ElectricalVehicle(
            t=t_set,
            delta_timestamps=delta_timestamps,
            name="ev",
            plugged=ev_plugged,
            charging_power=ev_charging_power,
            is_power_variable=ev_is_power_variable,
            battery_capacity=ev_battery_capacity,
            threshold_soc=ev_threshold_soc,
            initial_soc=ev_initial_soc,
            final_soc=ev_final_soc,
            efficiency=ev_charging_efficiency
        )

        tariff_energy_to = [grid_tariff_export(datetime.fromtimestamp(ti, tz=timezone.utc)) for ti in t]
        tariff_energy_from = [grid_tariff_import(datetime.fromtimestamp(ti, tz=timezone.utc)) for ti in t]

        grid = Grid(
            t=t_set,
            delta_timestamps=delta_timestamps,
            name="grid",
            tariff_energy_to=tariff_energy_to,
            tariff_energy_from=tariff_energy_from,
            is_settled=grid_is_settled,
            contracted_power=grid_contracted_power
        )

        pv = PhotovoltaicPanel(
            name="pv",
            t=t_set, # timestamps in seconds
            delta_timestamps=delta_timestamps,
            pv_power=pv_power
        )

        m = House(
            name=name,
            t_set=t_set,
            delta_timestamps=delta_timestamps,
            load_power=load_power,
            grid=grid,
            pv=pv,
            ev=ev
        )

        return m
