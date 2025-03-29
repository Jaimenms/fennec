from typing import List
import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


class GridBlock(pyo.ScalarBlock):

    def __init__(
        self,
        name: str,
        energy_limit: List[float],
        tariff_energy_to: List[float],
        tariff_energy_from: List[float],
        is_settled: bool = True,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # Constants
        t_index = [i for i in range(len(energy_limit))]
        self.name = name

        ###################### INDEX #############################

        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])

        #################### VARIABLES ###########################

        # Energy to grid in kWh
        self.energy_to = pyo.Var(self.t, domain=PositiveReals)

        # Energy from grid in kWh
        self.energy_from = pyo.Var(self.t, domain=PositiveReals)


        #################### PARAMETERS ##########################

        # Energy limit based on contracted power in kWh
        self.energy_limit = pyo.Param(
            self.t,
            initialize={
                i: energy_limit_i for i, energy_limit_i in enumerate(energy_limit)
            },
        )

        # Energy from grid tariff
        self.tariff_energy_from = pyo.Param(self.t, initialize={i: value for i, value in enumerate(tariff_energy_from)})

        # Energy to grid tariff
        self.tariff_energy_to = pyo.Param(self.t, initialize={i: value for i, value in enumerate(tariff_energy_to)})

        #################### CONSTRAINTS ##########################

        # Settling constraints
        if is_settled:
            self.settling = pyo.Var(self.t, domain=Binary)
            self.settlement_const_1 = pyo.Constraint(self.t,
                                                     rule=lambda model, i: model.energy_from[i] <= model.energy_limit[
                                                         i] * model.settling[i])
            self.settlement_const_2 = pyo.Constraint(self.t,
                                                     rule=lambda model, i: model.energy_to[i] <= model.energy_limit[
                                                         i] * (1.0 - model.settling[i]))

        # Energy limit constraints to grid
        self.energy_to_const = pyo.Constraint(
            self.t, rule=lambda model, i: model.energy_to[i] <= model.energy_limit[i]
        )

        # Energy limit constraints from grid
        self.energy_from_const = pyo.Constraint(
            self.t,
            rule=lambda model, i: model.energy_from[i] <= model.energy_limit[i]
        )

        #################### OBJECTIVE ###########################

        self.fob = pyo.Var(self.t)
        self.fob_const = pyo.Constraint(self.t, rule=lambda model, i: model.fob[i] == model.energy_from[i] * model.tariff_energy_from[i] - model.energy_to[i] * model.tariff_energy_to[i])
