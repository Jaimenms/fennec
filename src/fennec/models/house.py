from typing import Optional, List

import pyomo.environ as pyo
from ..blocks import GridBlock, PhotovoltaicBlock, FixedBatteryBlock, VehicleBatteryBlock


class House(pyo.ConcreteModel):

    def __init__(
        self,
        timestamps: List[float],
        load_power: List[float],
        grid: Optional[GridBlock] = pyo.Block(),
        pv: Optional[PhotovoltaicBlock] = pyo.Block(),
        ev: Optional[VehicleBatteryBlock] = pyo.Block(),
        bat: Optional[FixedBatteryBlock] = pyo.Block(),
        *args,
        **kwargs
    ):

        super().__init__(*args, **kwargs)

        t_index = [i for i in range(len(timestamps))]

        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])

        # Blocks
        self.grid = grid
        self.pv = pv
        self.ev = ev
        self.bat = bat

        self.load_energy = None
        self.set_parameters(timestamps, load_power)

        self.balance_const = None
        self.set_balance_const()

        self.fob = None
        self.fob_const = None
        self.set_objective()

    def set_parameters(self, timestamps, load_power):

        delta_timestamps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)] + [
            timestamps[-1] - timestamps[-2]
        ]

        self.load_energy = pyo.Param(
            self.t,
            initialize={
                i: load_power_i * delta_timestamp_i / 3600
                for i, (delta_timestamp_i, load_power_i) in enumerate(zip(delta_timestamps, load_power))
            },
        )

    def set_objective(self):

        def objective_rule(model: pyo.Model, i):

            fob_grid = model.grid.fob[i] if model.grid else 0
            fob_pv = model.pv.fob[i] if model.pv else 0
            fob_ev = model.ev.fob[i] if model.ev else 0
            fob_bat = model.bat.fob[i] if model.bat else 0

            return model.fob == fob_grid + fob_pv + fob_ev + fob_bat

        self.fob = pyo.Var(self.t)
        self.fob_const = pyo.Constraint(self.t, rule=objective_rule)

    def set_balance_const(self):

        def balance_rule(model: pyo.Model, i):

            energy_to_grid = model.grid.energy_to[i] if model.grid else 0
            load = model.load_energy[i]
            energy_from_grid = model.grid.energy_from[i] if model.grid else 0
            energy_from_pv = model.pv.energy_from[i] if model.pv else 0
            energy_to_ev = model.ev.energy_to[i] if model.ev else 0

            return energy_to_grid + load + energy_to_ev == energy_from_grid + energy_from_pv

        self.balance_const = pyo.Constraint(self.t, rule=balance_rule)

