import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


class Vehicle(pyo.Block):

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs )

    @staticmethod
    def rule(m: pyo.Block):

        ###################### INDEX #############################
        t = m.parent_block().t

        m.t_soc_back_home = pyo.Set()

        #################### VARIABLES ###########################

        # Variable for charging (dimensionless).
        m.charge = pyo.Var(t, bounds=(0, 1))

        # State of charge
        m.soc = pyo.Var(t, bounds=(0, 100), domain=PositiveReals)

        # Energy to battery (charging)
        m.energy_to = pyo.Var(t, domain=PositiveReals)

        # External charging in kWh
        m.external_to = pyo.Var(t, domain=PositiveReals)

        # External discharging in kWh
        m.external_from = pyo.Var(t, domain=PositiveReals)

        #################### PARAMETERS ###########################

        m.soc_back_home = pyo.Param(m.t_soc_back_home)

        # Energy limits for charging in kWh
        m.energy_to_limit = pyo.Param()

        # Battery energy capacity in kWh
        m.capacity = pyo.Param()

        #################### CONSTRAINTS ###########################

        # Guarantee that the energy to and from the battery are within the limits.
        m.energy_to_const = pyo.Constraint(
            t, rule=lambda model, i: model.energy_to[i] == model.energy_to_limit * model.charge[i]
        )

        # Guarantee that if the battery is not available, the commands are zero.
        m.is_plugged = pyo.Param(t, initialize=1, mutable=True)
        m.is_plugged_charge_const = pyo.Constraint(t, rule=lambda model, i: model.charge[i] <= model.is_plugged[i])

        m.external_energy_to_const = pyo.Constraint(
            t, rule=lambda model, i: model.external_to[i] <= 100 * (1 - model.is_plugged[i])
        )

        m.external_energy_from_const = pyo.Constraint(
            t, rule=lambda model, i: model.external_from[i] <= 100 * (1 - model.is_plugged[i])
        )


        def battery_capacity_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip

            # Otherwise, enforce the recursion
            return (
                    model.capacity * model.soc[i - 1] - model.capacity * model.soc[i] ==
                    - 100 * model.energy_to[i - 1]
                    - 100 * model.external_to[i - 1]
                    + 100 * model.external_from[i - 1]
            )
        m.battery_capacity_const = pyo.Constraint(t, rule=battery_capacity_rule)

        # Battery SOC Initial
        m.soc_initial = pyo.Param()
        m.soc_initial_const = pyo.Constraint(rule=lambda model: model.soc[min(model.parent_block().t)] == model.soc_initial)

        def soc_back_home_rule(model, i):
            for i_ in model.t_soc_back_home:
                if i_ == i:
                    return model.soc[i] == model.soc_back_home[i]
            return pyo.Constraint.Skip
        m.soc_back_home_const = pyo.Constraint(t, rule=soc_back_home_rule)

        #################### OBJECTIVE ###########################

        m.fob = pyo.Var(t)

        # Objective function
        m.fob_const = pyo.Constraint(
            t,
            rule=lambda model, i: model.fob[i] == 0.0,
        )
