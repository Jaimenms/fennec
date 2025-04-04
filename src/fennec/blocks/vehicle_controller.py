from typing import List, Optional, Tuple
import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


BIG_M = 10.


class VehicleController(pyo.Block):

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs)

    @staticmethod
    def rule(m: pyo.Block):

        ###################### INDEX #############################
        t = m.parent_block().t

        m.t_soc_objective = pyo.Set()
        m.nodeIndex = pyo.Set()
        m.vehicleIndex = pyo.Set()

        ###################### PARAMETERS ########################

        # Minimum SOC charging before arbitrage
        m.soc_min = pyo.Param(initialize=100)

        # SOC objective
        m.soc_objective = pyo.Param(m.t_soc_objective)

        # Maximum number of arbitrage commands
        m.max_commands = pyo.Param(initialize=100)

        # Penalty for not reaching the SOC objective
        m.charge_objective_penalty = pyo.Param(initialize=0.5)

        # Command penalty
        m.command_penalty = pyo.Param(t, initialize=0.0, mutable=True)


        #################### VARIABLES ###########################

        # Binary variable for charging power (dimensionless) in arbitrage mode.
        # m.charge = pyo.Var(t, domain=PositiveReals)
        m.charge = pyo.Var(t, domain=Binary)

        # Energy charged by the battery in kWh
        m.energy_to = pyo.Var(t, domain=PositiveReals)


        #################### CONSTRAINTS ###########################

        m.objective_deviation = pyo.Var(m.t_soc_objective, domain=PositiveReals)
        m.flag_deviation = pyo.Var(m.t_soc_objective, domain=Binary)
        def objective_deviation_rule_1(model, i):
            deviations = 0
            for si in m.vehicleIndex:
                deviations += model.soc_objective[i] - model.parent_block().vehicle[si].soc[i]
            return model.objective_deviation[i] >= deviations
        m.objective_deviation_const_1 = pyo.Constraint(m.t_soc_objective, rule=objective_deviation_rule_1)

        def objective_deviation_rule_2(model, i):
            deviations = 0
            for si in m.vehicleIndex:
                deviations += model.soc_objective[i] - model.parent_block().vehicle[si].soc[i]
            return model.objective_deviation[i] <= deviations + 100 * (1 - model.flag_deviation[i])
        m.objective_deviation_const_2 = pyo.Constraint(m.t_soc_objective, rule=objective_deviation_rule_2)

        def objective_deviation_rule_3(model, i):
            return model.objective_deviation[i] <= 100 * (1 - model.flag_deviation[i])
        m.objective_deviation_const_3 = pyo.Constraint(m.t_soc_objective, rule=objective_deviation_rule_3)

        # Calculate the energy charged and discharged by the battery
        def energy_to_rule(model, i):
            energy_to = 0
            for si in m.vehicleIndex:
                energy_to += model.parent_block().vehicle[si].energy_to[i]
            return energy_to == model.energy_to[i]
        m.energy_to_const = pyo.Constraint(t, rule=energy_to_rule)


        # Calculate the energy charged and discharged by the battery
        def charge_rule(model, i, si):
            return model.parent_block().vehicle[si].charge[i] == model.charge[i]
        m.charge_const = pyo.Constraint(t, m.vehicleIndex, rule=charge_rule)



        # Objective function
        m.fob = pyo.Var(t, domain=PositiveReals)

        m.diff_charge = pyo.Var(t, domain=Binary)
        def diff_charge_const_1_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_charge[i] >= model.charge[i - 1] - model.charge[i]
        m.diff_charge_const_1 = pyo.Constraint(t, rule=diff_charge_const_1_rule)

        def diff_charge_const_2_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_charge[i] >= model.charge[i] - model.charge[i - 1]
        m.diff_charge_const_2 = pyo.Constraint(t, rule=diff_charge_const_2_rule)

        def fob_rule(model, i):
            deviation_penalties = 0
            for i in model.t_soc_objective:
                deviation_penalties += model.objective_deviation[i]
            return model.fob[i] == model.command_penalty[i] * model.diff_charge[i] + model.charge_objective_penalty * deviation_penalties
        m.fob_const = pyo.Constraint( t, rule=fob_rule)

        # Maximum number of arbitrage commands
        m.max_commands_const = pyo.Constraint(
             rule=lambda model: sum(model.diff_charge[i] for i in t) <= model.max_commands
        )
