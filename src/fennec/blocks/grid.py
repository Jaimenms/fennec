from typing import List
import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


class GridBlock(pyo.Block):

    def __init__(
        self,
        timestamps: List[float],
        tariff_energy_to: List[float],
        tariff_energy_from: List[float],
        is_settled: bool = True,
        contracted_power: float = 6.75,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        t_index = [i for i in range(len(timestamps))]

        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])

        self.set_parameters(timestamps, contracted_power, tariff_energy_from, tariff_energy_to)

        self.energy_to = None
        self.energy_from = None
        self.energy_limit = None
        self.tariff_energy_from = None
        self.tariff_energy_to = None
        self.set_variables()

        self.settling = None
        self.settlement_const_1 = None
        self.settlement_const_2 = None
        if is_settled:
            self.set_settlement_const()

        self.fob = None
        self.fob_const = None
        self.set_objective()

        self.energy_to_const = None
        self.energy_from_const = None
        self.set_energy_consts()

    def set_variables(self):
        self.energy_to = pyo.Var(self.t, domain=PositiveReals)
        self.energy_from = pyo.Var(self.t, domain=PositiveReals)

    def set_parameters(self, timestamps: List[float], contracted_power: float, tariff_energy_from: List[float], tariff_energy_to: List[float]):

        delta_timestamps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)] + [
            timestamps[-1] - timestamps[-2]
        ]

        _energy_limit = {
            i: delta_timestamp_i * contracted_power for i, delta_timestamp_i in enumerate(delta_timestamps)
        }
        self.energy_limit = pyo.Param(
            self.t,
            initialize=_energy_limit,
        )
        self.tariff_energy_from = pyo.Param(self.t, initialize={i: value for i, value in tariff_energy_from})
        self.tariff_energy_to = pyo.Param(self.t, initialize={i: value for i, value in tariff_energy_to})

    def set_objective(self):
        self.fob = pyo.Var(self.t)
        self.fob_const = pyo.Constraint(self.t, rule=lambda model, i: model.fob[i] == model.energy_from[i] * model.tariff_energy_from[i] - model.energy_to[i] * model.tariff_energy_to[i])

    def set_settlement_const(self):
        self.settling = pyo.Var(self.t, domain=Binary)
        self.settlement_const_1 = pyo.Constraint(self.t, rule=lambda model, i: model.energy_from[i] <= model.energy_limit[i] * model.settling[i])
        self.settlement_const_2 = pyo.Constraint(self.t, rule=lambda model, i: model.energy_to[i] <= model.energy_limit[i] * (1.0 - model.settling[i]))

    def set_energy_consts(self, ):
        """
        Set the constraints for the energy variables.
        :return:
        """
        self.energy_to_const = pyo.Constraint(
            self.t, rule=lambda model, i: model.energy_to[i] <= model.energy_limit[i]
        )
        self.energy_from_const = pyo.Constraint(
            self.t,
            rule=lambda model, i: model.energy_from[i] <= model.energy_limit[i]
        )
