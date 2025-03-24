import pyomo.environ as pyo
from typing import List


class ElectricalVehicle(pyo.Block):

    def __init__(
            self,
            t: pyo.Set,
            delta_timestamps: List[float],
            charging_power: float,
            plugged: List[float], # 0 or 1
            battery_capacity: float,
            threshold_soc: float,
            initial_soc: float,
            final_soc: float,
            is_power_variable: bool = False,
            efficiency: float = 0.95,
            start_charging_penalty: float = 1.0, # in $ per charging session
            *args,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

        # Constraint: y_x[t] >= x[t-1] - x[t] for t in T with t > 0
        @staticmethod
        def switching1_rule(b: pyo.Block, t):
            if t == min(b.t):  # assuming the smallest t is 0
                return pyo.Constraint.Skip
            return b.switching[t] >= b.x[t - 1] - b.x[t]

        # Constraint: y_x[t] >= x[t] - x[t-1] for t in T with t > 0
        @staticmethod
        def switching2_rule(b: pyo.Block, t: pyo.Set):
            if t == min(b.t):
                return pyo.Constraint.Skip
            return b.switching[t] >= b.x[t] - b.x[t - 1]

        @staticmethod
        def battery_capacity_rule(b: pyo.Block, t):
            return b.soc[t] == b.soc[t-1] + b.energy_to[t] / battery_capacity

        @staticmethod
        def charging_energy_rule(b: pyo.Block, t):
            return b.charging_energy[t] ==b. charging_energy_limit[t] * b.x[t]

        @staticmethod
        def threshold_soc_rule(b: pyo.Block):
            return b.soc[t] >= threshold_soc * (1 - b.x[t])

        @staticmethod
        def initial_soc_rule(b: pyo.Block):
            return b.soc[0] == initial_soc

        @staticmethod
        def final_soc_rule(b: pyo.Block):
            return b.soc[max(b.t)] == final_soc

        @staticmethod
        def plugged_rule(b: pyo.Block, t):
            return b.x[t] <= b.plugged_param[t]

        @staticmethod
        def fob_rule(b: pyo.Block, t):
            return b.fob[t] == start_charging_penalty * b.switching[t]


        """
        # 9. Linking constraints: Force nonactive controls to zero.

        M = 2.
        # In arbitrage mode (m[t] = 1), force u[t] and v[t] to zero.
        h.addConstrs((u[t] <= (1 - m[t]) for t in time_periods),
                     name=["Link_u_%d" % t for t in time_periods])
        h.addConstrs((v[t] <= (1 - m[t]) for t in time_periods),
                     name=["Link_v_%d" % t for t in time_periods])
        
        # In self consumption mode (m[t] = 0), force arbitrage commands to zero.
        h.addConstrs((x[t] <= m[t] for t in time_periods),
                     name=["Link_x_%d" % t for t in time_periods])
        h.addConstrs((z[t] <= m[t] for t in time_periods),
                     name=["Link_z_%d" % t for t in time_periods])
        """


        if not is_power_variable:
            domain_x = pyo.Binary
        else:
            domain_x = (0, 1)

        self.charging_energy_limit = pyo.Param(t, initialize={t_i: efficiency * charging_power * delta_timestamp_i/3600 for t_i, delta_timestamp_i in enumerate(delta_timestamps)})
        self.plugged_param = pyo.Param(t, initialize={ti: plugged_i for i, (ti, plugged_i) in enumerate(zip(t, plugged))})

        self.x = pyo.Var(t, domain=domain_x)
        self.soc = pyo.Var(t, domain=(0, 100.))
        self.switching = pyo.Var(t, domain=pyo.Binary)
        self.energy_to = pyo.Var(t, domain=pyo.PositiveReals)
        self.fob = pyo.Var(t)

        self.switching1_constraint = pyo.Constraint(t, rule=switching1_rule)
        self.switching2_constraint = pyo.Constraint(t, rule=switching2_rule)
        self.charging_energy_constraint = pyo.Constraint(t, rule=charging_energy_rule)
        self.fob_constraint = pyo.Constraint(t, rule=fob_rule)
        self.battery_capacity_constraint = pyo.Constraint(t, rule=battery_capacity_rule)
        self.initial_soc_constraint = pyo.Constraint(rule=initial_soc_rule)
        self.final_soc_constraint = pyo.Constraint(rule=final_soc_rule)
        self.threshold_soc_constraint = pyo.Constraint(rule=threshold_soc_rule)
        self.plugged_constraint = pyo.Constraint(t, rule=plugged_rule)

