from typing import List
import pyomo.environ as pyo


class Grid(pyo.Block):

    def __init__(
            self,
            t: pyo.Set,
            delta_timestamps: List[float],
            tariff_energy_to: List[float],
            tariff_energy_from: List[float],
            is_settled: bool = True,
            contracted_power: float = 6.75,
            *args,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

        def fob_rule(b: pyo.Block, t):
            return b.fob[t] == b.energy_from[t] * b.tariff_energy_from[t] - b.energy_to[t] * b.tariff_energy_to[t]

        def settlement1_rule(b: pyo.Block, t):
            return b.energy_from[t] <= b.energy_limit[t] * b.settling[t]

        def settlement2_rule(b: pyo.Block, t):
            return b.energy_to[t] <= b.energy_limit[t] * (1.0 - b.settling[t])

        self.t = t
        self.fob = pyo.Var(t)
        self.energy_to = pyo.Var(t, domain=pyo.PositiveReals)
        self.energy_from = pyo.Var(t, domain=pyo.PositiveReals)
        self.settling = pyo.Var(t, domain=pyo.Binary)

        self.energy_limit = pyo.Param(t, initialize={i: delta_timestamp_i * contracted_power for i, delta_timestamp_i in enumerate(delta_timestamps)})
        self.tariff_energy_from = pyo.Param(t, initialize={i: value for i, value in tariff_energy_from})
        self.tariff_energy_to = pyo.Param(t, initialize={i: value for i, value in tariff_energy_to})

        if is_settled:
            self.settlement1_constraint = pyo.Constraint(self.t, rule=settlement1_rule)
            self.settlement2_constraint = pyo.Constraint(self.t, rule=settlement2_rule)

        self.fob_constraint = pyo.Constraint(self.t, rule=fob_rule)
