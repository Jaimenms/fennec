from typing import List
import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


class UnsettledGridBlock(pyo.ScalarBlock):

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs)

    @staticmethod
    def rule(m: pyo.Model):

        ###################### INDEX #############################

        m.t = m.parent_block().t

        #################### PARAMETERS ##########################

        # Energy limit based on contracted power in kWh
        m.energy_limit = pyo.Param(m.t)

        # Energy from grid tariff
        m.tariff_energy_from = pyo.Param(m.t)

        # Energy to grid tariff
        m.tariff_energy_to = pyo.Param(m.t)

        #################### VARIABLES ###########################

        # Energy to grid in kWh
        m.energy_to = pyo.Var(m.t, domain=PositiveReals)

        # Energy from grid in kWh
        m.energy_from = pyo.Var(m.t, domain=PositiveReals)

        #################### CONSTRAINTS ##########################

        # Energy limit constraints to grid
        m.energy_to_const = pyo.Constraint(m.t, rule=lambda model, i: model.energy_to[i] <= model.energy_limit[i])

        # Energy limit constraints from grid
        m.energy_from_const = pyo.Constraint(m.t, rule=lambda model, i: model.energy_from[i] <= model.energy_limit[i])

        #################### OBJECTIVE ###########################

        m.fob = pyo.Var(m.t)
        m.fob_const = pyo.Constraint(m.t, rule=lambda model, i: model.fob[i] == model.energy_from[i] * model.tariff_energy_from[i] - model.energy_to[i] * model.tariff_energy_to[i])



class SettledGridBlock(pyo.ScalarBlock):

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs )

    @staticmethod
    def rule(m: pyo.Block):

        ###################### INDEX #############################
        t = m.parent_block().t

        #################### PARAMETERS ##########################

        # Energy limit based on contracted power in kWh
        m.energy_limit = pyo.Param(t)

        # Energy from grid tariff
        m.tariff_energy_from = pyo.Param(t, initialize=0.0, mutable=True)

        # Energy to grid tariff
        m.tariff_energy_to = pyo.Param(t, initialize=0.0, mutable=True)

        #################### VARIABLES ###########################

        # Energy to grid in kWh
        m.energy_to = pyo.Var(t, domain=PositiveReals)

        # Energy from grid in kWh
        m.energy_from = pyo.Var(t, domain=PositiveReals)

        #################### CONSTRAINTS ##########################

        # Settling constraints
        m.settling = pyo.Var(t, domain=Binary)
        m.settlement_const_1 = pyo.Constraint(t,
                                                 rule=lambda model, i: model.energy_from[i] <= model.energy_limit[
                                                     i] * model.settling[i])
        m.settlement_const_2 = pyo.Constraint(t,
                                                 rule=lambda model, i: model.energy_to[i] <= model.energy_limit[
                                                     i] * (1.0 - model.settling[i]))

        # Energy limit constraints to grid
        m.energy_to_const = pyo.Constraint(t, rule=lambda model, i: model.energy_to[i] <= model.energy_limit[i])

        # Energy limit constraints from grid
        m.energy_from_const = pyo.Constraint(t, rule=lambda model, i: model.energy_from[i] <= model.energy_limit[i])

        #################### OBJECTIVE ###########################

        m.fob = pyo.Var(t)
        m.fob_const = pyo.Constraint(t, rule=lambda model, i: model.fob[i] == model.energy_from[i] * model.tariff_energy_from[i] - model.energy_to[i] * model.tariff_energy_to[i])


class GridBlock(pyo.ScalarBlock):

    def __init__(self, is_settled=True, *args, **kwargs):
        if is_settled:
            self.rule = SettledGridBlock.rule
        else:
            self.rule = UnsettledGridBlock.rule
        super().__init__(rule=self.rule, *args, **kwargs)
