from typing import List
import pyomo.environ as pyo


class Battery(pyo.Block):

    def __init__(
            self,
            t: pyo.Set,
            delta_timestamps: List[float],
            charging_power: float,
            discharging_power: float,
            battery_capacity: float,
            initial_soc: float,
            final_soc: float,
            charging_efficiency: float = 0.95,
            discharging_efficiency: float = 0.95,
            start_charging_penalty: float = 1.0, # in $ per charging session
            *args,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

        @staticmethod
        def initial_soc_rule(b: pyo.Block):
            return b.soc[0] == initial_soc

        @staticmethod
        def final_soc_rule(b: pyo.Block):
            return b.soc[max(b.t)] == final_soc

        @staticmethod
        def fob_rule(b: pyo.Block, t):
            return b.fob[t] == start_charging_penalty * b.switching[t]

        def settlement1_rule(b: pyo.Block, t):
            return b.energy_from[t] <= b.energy_limit[t] * b.settling[t]

        def settlement2_rule(b: pyo.Block, t):
            return b.energy_to[t] <= b.energy_limit[t] * (1.0 - b.settling[t])

        @staticmethod
        def battery_capacity_rule(b: pyo.Block, t):
            if t == min(b.t):  # assuming the smallest t is 0
                return pyo.Constraint.Skip
            return b.soc[t] == b.soc[t-1] + b.energy_to[t] / battery_capacity - b.energy_from[t] / battery_capacity

        @staticmethod
        def energy_to_rule(b: pyo.Block, t):
            return b.energy_to[t] ==b.energy_to_limit[t] * (b.x[t] + b.u[t])

        @staticmethod
        def energy_from_rule(b: pyo.Block, t):
            return b.energy_from[t] ==b.energy_from_limit[t] * (b.z[t] + b.v[t])


        @staticmethod
        def switching_mode_rule_1(b: pyo.Block, t):
            if t == min(b.t):  # assuming the smallest t is 0
                return pyo.Constraint.Skip
            return b.switching_mode[t] >= b.mode[t - 1] - b.mode[t]

        @staticmethod
        def switching_mode_rule_2(b: pyo.Block, t: pyo.Set):
            if t == min(b.t):
                return pyo.Constraint.Skip
            return b.switching_mode[t] >= b.mode[t] - b.mode[t - 1]

        @staticmethod
        def switching_x_rule_1(b: pyo.Block, t):
            if t == min(b.t):  # assuming the smallest t is 0
                return pyo.Constraint.Skip
            return b.switching_x[t] >= b.x[t - 1] - b.x[t]

        @staticmethod
        def switching_x_rule_2(b: pyo.Block, t: pyo.Set):
            if t == min(b.t):
                return pyo.Constraint.Skip
            return b.switching_x[t] >= b.x[t] - b.x[t - 1]

        @staticmethod
        def switching_z_rule_1(b: pyo.Block, t):
            if t == min(b.t):  # assuming the smallest t is 0
                return pyo.Constraint.Skip
            return b.switching_z[t] >= b.z[t - 1] - b.z[t]

        @staticmethod
        def switching_z_rule_2(b: pyo.Block, t: pyo.Set):
            if t == min(b.t):
                return pyo.Constraint.Skip
            return b.switching_z[t] >= b.z[t] - b.z[t - 1]


        # Mode variable: m[t] = 1 means arbitrage mode; m[t] = 0 means self consumption.
        self.mode = pyo.Var(t, domain=pyo.Binary)

        # Binary variable for charging power (dimensionless) in arbitrage mode.
        self.x = pyo.Var(t, domain=pyo.Binary)

        # Binary variable for discharging power (dimensionless) in arbitrage mode.
        self.z = pyo.Var(t, domain=pyo.Binary)

        # Continuous charging power (dimensionless) for self consumption.
        self.u = pyo.Var(t, domain=(0, 1))

        # Continuous discharging power (dimensionless) for self consumption.
        self.v = pyo.Var(t, domain=(0, 1))

        # swiching identifiers.
        self.switching_mode = pyo.Var(t, domain=pyo.Binary)
        self.switching_x = pyo.Var(t, domain=pyo.Binary)
        self.switching_z = pyo.Var(t, domain=pyo.Binary)

        # limits
        self.energy_to_limit = pyo.Param(t, initialize={t_i: charging_efficiency * charging_power * delta_timestamp_i/3600 for t_i, delta_timestamp_i in enumerate(delta_timestamps)})
        self.energy_from_limit = pyo.Param(t, initialize={t_i: discharging_efficiency * discharging_power * delta_timestamp_i/3600 for t_i, delta_timestamp_i in enumerate(delta_timestamps)})


        # state of charge in %
        self.soc = pyo.Var(t, domain=(0, 100.))

        self.fob = pyo.Var(t)

        # energies
        self.energy_to = pyo.Var(t, domain=pyo.PositiveReals)
        self.energy_from = pyo.Var(t, domain=pyo.PositiveReals)

        self.switching_mode_constraint_1 = pyo.Constraint(t, rule=switching_mode_rule_1)
        self.switching_mode_constraint_2 = pyo.Constraint(t, rule=switching_mode_rule_2)
        self.switching_x_constraint_1 = pyo.Constraint(t, rule=switching_x_rule_1)
        self.switching_x_constraint_2 = pyo.Constraint(t, rule=switching_x_rule_2)
        self.switching_z_constraint_1 = pyo.Constraint(t, rule=switching_z_rule_1)
        self.switching_z_constraint_2 = pyo.Constraint(t, rule=switching_z_rule_2)

        self.energy_to_constraint = pyo.Constraint(t, rule=energy_to_rule)
        self.energy_from_constraint = pyo.Constraint(t, rule=energy_from_rule)

        self.fob_constraint = pyo.Constraint(t, rule=fob_rule)

        self.battery_capacity_constraint = pyo.Constraint(t, rule=battery_capacity_rule)
        self.initial_soc_constraint = pyo.Constraint(rule=initial_soc_rule)
        self.final_soc_constraint = pyo.Constraint(rule=final_soc_rule)

        self.settlement1_constraint = pyo.Constraint(self.t, rule=settlement1_rule)
        self.settlement2_constraint = pyo.Constraint(self.t, rule=settlement2_rule)
