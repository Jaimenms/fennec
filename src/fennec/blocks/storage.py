import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


class Storage(pyo.Block):

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs )

    @staticmethod
    def rule(m: pyo.Block):

        ###################### INDEX #############################
        t = m.parent_block().t

        #################### VARIABLES ###########################

        # Variable for charging (dimensionless).
        m.charge = pyo.Var(t, bounds=(0, 1))

        # Variable for discharging (dimensionless).
        m.discharge = pyo.Var(t, bounds=(0, 1))

        # State of charge
        m.soc = pyo.Var(t, bounds=(0, 100), domain=PositiveReals)

        # Energy to battery (charging)
        m.energy_to = pyo.Var(t, domain=PositiveReals)

        # Energy from battery (discharging)
        m.energy_from = pyo.Var(t, domain=PositiveReals)

        m.soc_upper_flag = pyo.Var(t, domain=Binary)
        m.soc_lower_flag = pyo.Var(t,  domain=Binary)


        #################### PARAMETERS ###########################

        # Energy limits for charging in kWh
        m.energy_to_limit = pyo.Param()

        # Energy limits for discharging in kWh
        m.energy_from_limit = pyo.Param()

        # Battery energy capacity in kWh
        m.capacity = pyo.Param()

        # External charging in kWh
        m.external_to = pyo.Param(t, mutable=True, initialize=0)

        # External discharging in kWh
        m.external_from = pyo.Param(t, mutable=True, initialize=0)

        m.charging_efficiency = pyo.Param(initialize=0, mutable=True)

        m.discharging_efficiency = pyo.Param(initialize=0, mutable=True)


        #################### CONSTRAINTS ###########################

        m.settling = pyo.Var(t, domain=Binary)
        m.settlement_const_1 = pyo.Constraint(t,
                                                 rule=lambda model, i: model.energy_from[i] + model.external_from[i] <= model.energy_from_limit * model.settling[i])
        m.settlement_const_2 = pyo.Constraint(t,
                                                 rule=lambda model, i: model.energy_to[i] + model.external_to[i] <= model.energy_to_limit * (1.0 - model.settling[i]))


        # Guarantee that the energy to and from the battery are within the limits.
        m.energy_to_const_1 = pyo.Constraint(
            t, rule=lambda model, i: model.energy_to[i] == model.energy_to_limit * model.charge[i]
        )
        m.energy_to_const_2 = pyo.Constraint(
            t, rule=lambda model, i: model.energy_to[i] + model.external_to[i] <= model.energy_to_limit
        )
        m.energy_from_const_1 = pyo.Constraint(
            t, rule=lambda model, i: model.energy_from[i] == model.energy_from_limit * model.discharge[i]
        )
        m.energy_from_const_2 = pyo.Constraint(
            t, rule=lambda model, i: model.energy_from[i] + model.external_from[i] <= model.energy_from_limit
        )

        def battery_capacity_rule(model, i):
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip

            return (
                    model.capacity * model.soc[i - 1] - model.capacity * model.soc[i] ==
                    - 100 * model.charging_efficiency * (model.energy_to[i - 1] + model.external_to[i - 1] )
                    + 100 / model.discharging_efficiency * (model.energy_from[i - 1] + model.external_from[i - 1])
            )
        m.battery_capacity_const = pyo.Constraint(t, rule=battery_capacity_rule)

        # Battery SOC Initial
        m.soc_initial = pyo.Param()
        m.soc_initial_const = pyo.Constraint(rule=lambda model: model.soc[min(model.parent_block().t)] == model.soc_initial)

        #################### OBJECTIVE ###########################

        m.fob = pyo.Var(t)

        # Objective function
        m.fob_const = pyo.Constraint(
            t,
            rule=lambda model, i: model.fob[i] == 0.0,
        )
