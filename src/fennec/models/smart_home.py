from typing import Optional, List

import pyomo.environ as pyo
from ..blocks import GridBlock, PhotovoltaicBlock, FixedBatteryBlock, VehicleBatteryBlock


class SmartHome(pyo.ConcreteModel):

    def __init__(
        self,
        name: str,
        load_energy: List[float],
        grid: GridBlock = pyo.Block(),
        pv: Optional[PhotovoltaicBlock] = None,
        ev: Optional[List[VehicleBatteryBlock]] = None,
        bat: Optional[List[FixedBatteryBlock]] = None,
        *args,
        **kwargs
    ):

        super().__init__(*args, **kwargs)

        # Constants
        t_index = [i for i in range(len(load_energy))]

        ###################### INDEX #############################
        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])
        self.name = name

        #################### BLOCKS ###############################
        self.grid = grid

        self.pv = pv

        ev = ev if ev is not None else []
        self.ev_index = pyo.RangeSet(0, len(ev) - 1)
        self.ev = pyo.Block(self.ev_index)
        for i, ev_elem in enumerate(ev):
            self.ev[i].transfer_attributes_from(ev_elem.clone())

        bat = bat if bat is not None else []
        self.bat_index = pyo.RangeSet(0, len(bat) - 1)
        self.bat = pyo.Block(self.bat_index)
        for i, bat_elem in enumerate(bat):
            self.bat[i].transfer_attributes_from(bat_elem.clone())

        #################### PARAMETERS ###########################
        self.load_energy = pyo.Param(
            self.t,
            initialize={
                i: load_energy_i
                for i, load_energy_i in enumerate(load_energy)
            },
        )

        #################### CONSTRAINTS ###########################
        def balance_rule(model: pyo.Model, i):
            load = model.load_energy[i]

            energy_to = model.grid.energy_to[i]
            energy_from = model.grid.energy_from[i]

            if model.pv is not None:
                energy_to += model.pv.energy_to[i]
                energy_from += model.pv.energy_from[i]

            for j in model.ev_index:
                energy_to += model.ev[j].energy_to[i]
                energy_from += model.ev[j].energy_from[i]

            for j in model.bat_index:
                energy_to += model.bat[j].energy_to[i]
                energy_from += model.bat[j].energy_from[i]

            return load == energy_from - energy_to

        self.balance_const = pyo.Constraint(self.t, rule=balance_rule)

        #################### OBJECTIVE ###########################
        def objective_rule(model: pyo.Model):
            fob = pyo.summation(model.grid.fob) + pyo.summation(model.pv.fob)

            for j in model.ev_index:
                fob += pyo.summation(model.ev[j].fob)

            for j in model.bat_index:
                fob += pyo.summation(model.bat[j].fob)

            return fob

        self.obj = pyo.Objective(rule=objective_rule, sense=pyo.minimize)
