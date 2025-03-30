from typing import List, Optional, Tuple
import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


BIG_M = 10.



class SimpleBatteryBlock(pyo.Block):

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs )

    @staticmethod
    def rule(m: pyo.Block):

        ###################### INDEX #############################
        t = m.parent_block().t

        #################### VARIABLES ###########################

        # Binary variable for charging power (dimensionless) in arbitrage mode.
        m.x = pyo.Var(t, domain=Binary)

        # Binary variable for discharging power (dimensionless) in arbitrage mode.
        m.z = pyo.Var(t, domain=Binary)

        # State of charge
        m.soc = pyo.Var(t, bounds=(0, 100), domain=PositiveReals)

        # Energy to battery (charging)
        m.energy_to = pyo.Var(t, domain=PositiveReals)

        # Energy from battery (discharging)
        m.energy_from = pyo.Var(t, domain=PositiveReals)


        #################### PARAMETERS ###########################

        # Energy limits for charging in kWh
        m.energy_to_limit = pyo.Param(t)

        # Energy limits for discharging in kWh
        m.energy_from_limit = pyo.Param(t)

        #################### CONSTRAINTS ###########################

        # Guarantee that the energy to and from the battery are within the limits.
        m.energy_to_const = pyo.Constraint(
            t, rule=lambda model, i: model.energy_to[i] == model.energy_to_limit[i] * model.x[i]
        )
        m.energy_from_const = pyo.Constraint(
            t, rule=lambda model, i: model.energy_from[i] == model.energy_from_limit[i] * model.z[i]
        )

        # Settlement for x and z
        m.settling = pyo.Var(t, domain=Binary)
        m.settlement_const_1 = pyo.Constraint(
            t, rule=lambda model, i: model.x[i] <= model.settling[i]
        )
        m.settlement_const_2 = pyo.Constraint(
            t, rule=lambda model, i: model.z[i] <= (1.0 - model.settling[i])
        )

        # Guarantee that if the battery is not available, the commands are zero.
        m.is_available_param = pyo.Param(t, initialize=1, mutable=True)
        m.is_available_const_x = pyo.Constraint(t, rule=lambda model, i: model.x[i] <= model.is_available_param[i])
        m.is_available_const_z = pyo.Constraint(t, rule=lambda model, i: model.z[i] <= model.is_available_param[i])

        # Battery energy balance
        m.capacity = pyo.Param()

        def battery_capacity_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip

            # Otherwise, enforce the recursion
            return (
                    model.capacity * model.soc[i]
                    == model.capacity * model.soc[i - 1]
                    + 100 * model.energy_to[i - 1]
                    - 100 * model.energy_from[i - 1]
            )

        m.battery_capacity_const = pyo.Constraint(t,rule=battery_capacity_rule)

        # Battery SOC Initial
        m.soc_0 = pyo.Param()
        m.initial_soc_const = pyo.Constraint(rule=lambda model: model.soc.first() == model.soc_0)

        # Battery SOC Specifications
        m.soc_specifications = pyo.Param(t, initialize=0.0, mutable=True)
        m.soc_specifications_const = pyo.Constraint(rule=lambda model, i: model.soc[i] >= model.soc_specifications[i])

        #################### OBJECTIVE ###########################

        m.fob = pyo.Var(t)

        m.diff_x = pyo.Var(t, domain=Binary)
        def diff_x_const_1_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_x[i] >= model.x[i - 1] - model.x[i]
        m.diff_x_const_1 = pyo.Constraint(t, rule=diff_x_const_1_rule)

        def diff_x_const_2_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_x[i] >= model.x[i] - model.x[i - 1]
        m.diff_x_const_2 = pyo.Constraint(t, rule=diff_x_const_2_rule)

        m.diff_z = pyo.Var(t, domain=Binary)
        def diff_z_const_1_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_z[i] >= model.z[i - 1] - model.z[i]
        m.diff_z_const_1 = pyo.Constraint(t, rule=diff_z_const_1_rule)

        def diff_z_const_2_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_z[i] >= model.z[i] - model.z[i - 1]
        m.diff_z_const_2 = pyo.Constraint(t, rule=diff_z_const_2_rule)

        # Objective function
        m.command_penalty = pyo.Param(initialize=0.0, mutable=True)
        m.fob_const = pyo.Constraint(
            t,
            rule=lambda model, i: model.fob[i] == model.command_penalty * (i+1) * (model.diff_x[i] + model.diff_z[i]),
        )


class IntelligentBatteryBlock(pyo.Block):

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs )

    @staticmethod
    def rule(m: pyo.Block):

        ###################### INDEX #############################
        t = m.parent_block().t

        #################### VARIABLES ###########################

        # Mode variable: m[t] = 1 means arbitrage mode; m[t] = 0 means m consumption.
        m.m = pyo.Var(t, domain=Binary)

        # Binary variable for charging power (dimensionless) in arbitrage mode.
        m.x = pyo.Var(t, domain=Binary)

        # Binary variable for discharging power (dimensionless) in arbitrage mode.
        m.z = pyo.Var(t, domain=Binary)

        # Continuous charging power (dimensionless) for m consumption.
        m.u = pyo.Var(t, bounds=(0, 1), domain=PositiveReals)

        # Continuous discharging power (dimensionless) for m consumption.
        m.v = pyo.Var(t, bounds=(0, 1), domain=PositiveReals)

        # State of charge
        m.soc = pyo.Var(t, bounds=(0, 100), domain=PositiveReals)

        # Energy to battery (charging)
        m.energy_to = pyo.Var(t, domain=PositiveReals)

        # Energy from battery (discharging)
        m.energy_from = pyo.Var(t, domain=PositiveReals)

        #################### PARAMETERS ###########################

        # Energy limits for charging in kWh
        m.energy_to_limit = pyo.Param(t)

        # Energy limits for discharging in kWh
        m.energy_from_limit = pyo.Param(t)

        #################### CONSTRAINTS ###########################

        # Guarantee that the energy to and from the battery are within the limits.
        m.energy_to_const = pyo.Constraint(
            t, rule=lambda model, i: model.energy_to[i] == model.energy_to_limit[i] * (model.x[i] + model.u[i])
        )
        m.energy_from_const = pyo.Constraint(
            t, rule=lambda model, i: model.energy_from[i] == model.energy_from_limit[i] * (model.z[i] + model.v[i])
        )

        # Settlement for x and z
        m.settling_1 = pyo.Var(t, domain=Binary)
        m.settlement_const_1 = pyo.Constraint(
            t, rule=lambda model, i: model.x[i] <= model.settling_1[i]
        )
        m.settlement_const_2 = pyo.Constraint(
            t, rule=lambda model, i: model.z[i] <= (1.0 - model.settling_1[i])
        )

        # Settlement for u and v
        m.settling_2 = pyo.Var(t, domain=Binary)
        m.settlement_const_3 = pyo.Constraint(
            t, rule=lambda model, i: model.u[i] <= model.settling_2[i]
        )
        m.settlement_const_4 = pyo.Constraint(
            t, rule=lambda model, i: model.v[i] <= (1.0 - model.settling_2[i])
        )

        # In arbitrage mode (m[t] = 1), force u[t] and v[t] to zero.
        m.m_1_const_u = pyo.Constraint(t, rule=lambda model, i: model.u[i] <= (1 - model.m[i]))
        m.m_1_const_v = pyo.Constraint(t, rule=lambda model, i: model.v[i] <= (1 - model.m[i]))

        # In m consumption mode (m[t] = 0), force arbitrage commands to zero.
        m.m_0_const_x = pyo.Constraint(t, rule=lambda model, i: model.x[i] <= model.m[i])
        m.m_0_const_z = pyo.Constraint(t, rule=lambda model, i: model.z[i] <= model.m[i])

        # Initial condition for m
        m.initial_m_const = pyo.Constraint(rule=lambda model: model.m[max(model.parent_block().t)] == 0)

        # Guarantee that if the battery is not available, the commands are zero.
        m.is_available_param = pyo.Param(t, initialize=1, mutable=True)
        m.is_available_const_u = pyo.Constraint(t, rule=lambda model, i: model.u[i] <= model.is_available_param[i])
        m.is_available_const_v = pyo.Constraint(t, rule=lambda model, i: model.v[i] <= model.is_available_param[i])
        m.is_available_const_x = pyo.Constraint(t, rule=lambda model, i: model.x[i] <= model.is_available_param[i])
        m.is_available_const_z = pyo.Constraint(t, rule=lambda model, i: model.z[i] <= model.is_available_param[i])

        # Solar Surplus condition in m-consumption mode will force battery charge
        m.solar_surplus = pyo.Param(t)
        m.solar_surplus_const_1 = pyo.Constraint(
            t,
            rule=lambda model, i: model.u[i] * model.energy_to_limit[i] <= model.solar_surplus[i] + BIG_M * model.m[i]
        )
        m.solar_surplus_const_2 = pyo.Constraint(
            t,
            rule=lambda model, i: model.u[i] * model.energy_to_limit[i] >= model.solar_surplus[i] - BIG_M * model.m[i]
        )

        # Solar Deficit condition in m-consumption mode will force battery discharge
        m.solar_deficit = pyo.Param(t, initialize=0.0, mutable=True)
        m.solar_deficit_const_1 = pyo.Constraint(
            t,
            rule=lambda model, i: model.v[i] * model.energy_from_limit[i] <= model.solar_deficit[i] + BIG_M * model.m[i]
        )
        m.solar_deficit_const_2 = pyo.Constraint(
            t,
            rule=lambda model, i: model.v[i] * model.energy_from_limit[i] >= model.solar_deficit[i] - BIG_M * model.m[i]
        )

        # Battery energy balance
        m.capacity = pyo.Param()

        def battery_capacity_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip

            # Otherwise, enforce the recursion
            return (
                    model.capacity * model.soc[i]
                    == model.capacity * model.soc[i - 1]
                    + 100 * model.energy_to[i - 1]
                    - 100 * model.energy_from[i - 1]
            )

        m.battery_capacity_const = pyo.Constraint(t,rule=battery_capacity_rule)

        # Battery SOC Initial
        m.soc_0 = pyo.Param()
        m.initial_soc_const = pyo.Constraint(rule=lambda model: model.soc[model.parent_block().t.first()] == model.soc_0)

        # Battery SOC Specifications
        m.soc_specifications = pyo.Param(t, initialize=0, mutable=True)
        # m.soc_specifications_const = pyo.Constraint(rule=lambda model, i:
        #     model.soc[i] >= model.soc_specifications[i]
        # )


        # Objective function
        m.command_penalty = pyo.Param(t, initialize=0.0, mutable=True)
        m.fob = pyo.Var(t, domain=PositiveReals)

        m.diff_x = pyo.Var(t, domain=Binary)
        def diff_x_const_1_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_x[i] >= model.x[i - 1] - model.x[i]
        m.diff_x_const_1 = pyo.Constraint(t, rule=diff_x_const_1_rule)

        def diff_x_const_2_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_x[i] >= model.x[i] - model.x[i - 1]
        m.diff_x_const_2 = pyo.Constraint(t, rule=diff_x_const_2_rule)

        m.diff_z = pyo.Var(t, domain=Binary)
        def diff_z_const_1_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_z[i] >= model.z[i - 1] - model.z[i]
        m.diff_z_const_1 = pyo.Constraint(t, rule=diff_z_const_1_rule)

        def diff_z_const_2_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_z[i] >= model.z[i] - model.z[i - 1]
        m.diff_z_const_2 = pyo.Constraint(t, rule=diff_z_const_2_rule)

        m.fob_const = pyo.Constraint(
            t,
            rule=lambda model, i: model.fob[i] == model.command_penalty[i] * (
                        model.diff_x[i] + model.diff_z[i]),
        )
