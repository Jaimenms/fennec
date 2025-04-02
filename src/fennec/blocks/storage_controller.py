from typing import List, Optional, Tuple
import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


BIG_M = 10.


class StorageController(pyo.Block):

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs)

    @staticmethod
    def rule(m: pyo.Block):

        ###################### INDEX #############################
        t = m.parent_block().t

        m.nodeIndex = pyo.Set()
        m.storageIndex = pyo.Set()

        ###################### PARAMETERS ########################

        # Maximum number of arbitrage commands
        m.max_commands = pyo.Param(initialize=100)

        # Command penalty
        m.command_penalty = pyo.Param(t, initialize=0.0, mutable=True)


        #################### VARIABLES ###########################

        # Mode variable: flag_arbitrage[t] = 1 means arbitrage mode; flag_arbitrage[t] = 0 means self consumption mode.
        m.flag_arbitrage = pyo.Var(t, domain=Binary)

        # Binary variable for charging power (dimensionless) in arbitrage mode.
        m.charge_arbitrage = pyo.Var(t, domain=Binary)

        # Binary variable for discharging power (dimensionless) in arbitrage mode.
        m.discharge_arbitrage = pyo.Var(t, domain=Binary)

        # Continuous charging power (dimensionless) for m consumption.
        m.charge_sc = pyo.Var(t, bounds=(0, 1), domain=PositiveReals)

        # Continuous discharging power (dimensionless) for m consumption.
        m.discharge_sc = pyo.Var(t, bounds=(0, 1), domain=PositiveReals)

        # Binary variable for surplus positive
        m.flag_surplus = pyo.Var(t, domain=Binary)

        # Solar surplus energy in kWh
        m.solar_surplus = pyo.Var(t, domain=PositiveReals)

        # Solar deficit energy in kWh
        m.solar_deficit = pyo.Var(t, domain=PositiveReals)

        # Energy charged by the battery in kWh
        m.energy_to = pyo.Var(t, domain=PositiveReals)

        # Energy discharged by the battery in kWh
        m.energy_from = pyo.Var(t, domain=PositiveReals)

        #################### CONSTRAINTS ###########################

        # In self-consumption mode (m[t] = 0), force arbitrage commands to zero.
        m.flag_arbitrage_0_const_x = pyo.Constraint(t, rule=lambda model, i: model.charge_arbitrage[i] <= model.flag_arbitrage[i])
        m.flag_arbitrage_0_const_z = pyo.Constraint(t, rule=lambda model, i: model.discharge_arbitrage[i] <= model.flag_arbitrage[i])

        # In arbitrage mode (m[t] = 1), force u[t] and v[t] to zero.
        m.flag_arbitrage_1_const_u = pyo.Constraint(t, rule=lambda model, i: model.charge_sc[i] <= (1 - model.flag_arbitrage[i]))
        m.flag_arbitrage_1_const_v = pyo.Constraint(t, rule=lambda model, i: model.discharge_sc[i] <= (1 - model.flag_arbitrage[i]))

        # Initial condition for m
        m.initial_m_const = pyo.Constraint(rule=lambda model: model.flag_arbitrage[min(model.parent_block().t)] == 0)

        # Calculate the energy charged and discharged by the battery
        def energy_to_rule(model, i):
            energy_to = 0
            for si in model.storageIndex:
                energy_to += model.parent_block().storage[si].energy_to[i]
            return energy_to == model.energy_to[i]
        m.energy_to_const = pyo.Constraint(t, rule=energy_to_rule)

        def energy_from_rule(model, i):
            energy_from = 0
            for si in model.storageIndex:
                energy_from += model.parent_block().storage[si].energy_from[i]
            return energy_from == model.energy_from[i]
        m.energy_from_const = pyo.Constraint(t, rule=energy_from_rule)

        # Calculate the energy consumed and produced by the nodes

        # Control
        def solar_surplus_rule_1(model, i):
            produced_energy = 0
            consumed_energy = 0
            for ind in model.nodeIndex:
                consumed_energy += model.parent_block().node[ind].energy_to[i]
                produced_energy += model.parent_block().node[ind].energy_from[i]
            return model.solar_surplus[i] >= produced_energy - consumed_energy
        m.solar_surplus_const_1 = pyo.Constraint(t, rule=solar_surplus_rule_1)

        def solar_surplus_rule_2(model, i):
            produced_energy = 0
            consumed_energy = 0
            for ind in model.nodeIndex:
                consumed_energy += model.parent_block().node[ind].energy_to[i]
                produced_energy += model.parent_block().node[ind].energy_from[i]
            return model.solar_surplus[i] <= produced_energy - consumed_energy + BIG_M * (1-model.flag_surplus[i])
        m.solar_surplus_const_2 = pyo.Constraint(t, rule=solar_surplus_rule_2)

        m.solar_surplus_const_3 = pyo.Constraint(t, m.storageIndex, rule=lambda model, i, si: model.charge_sc[i] * model.parent_block().storage[si].energy_to_limit <= model.solar_surplus[i] + model.parent_block().storage[si].energy_to_limit * model.flag_arbitrage[i])
        m.solar_surplus_const_4 = pyo.Constraint(t, m.storageIndex, rule=lambda model, i, si: model.charge_sc[i] * model.parent_block().storage[si].energy_to_limit >= model.solar_surplus[i] - model.parent_block().storage[si].energy_to_limit * model.flag_arbitrage[i])

        def solar_deficit_rule_1(model, i):
            produced_energy = 0
            consumed_energy = 0
            for ind in model.nodeIndex:
                consumed_energy += model.parent_block().node[ind].energy_to[i]
                produced_energy += model.parent_block().node[ind].energy_from[i]
            return model.solar_deficit[i] >= consumed_energy - produced_energy
        m.solar_deficit_const_1 = pyo.Constraint(t, rule=solar_deficit_rule_1)

        def solar_deficit_rule_2(model, i):
            produced_energy = 0
            consumed_energy = 0
            for ind in model.nodeIndex:
                consumed_energy += model.parent_block().node[ind].energy_to[i]
                produced_energy += model.parent_block().node[ind].energy_from[i]
            return model.solar_deficit[i] <= consumed_energy - produced_energy + BIG_M * model.flag_surplus[i]
        m.solar_deficit_const_2 = pyo.Constraint(t, rule=solar_deficit_rule_2)

        m.solar_deficit_const_3 = pyo.Constraint(t, m.storageIndex, rule=lambda model, i, si: model.discharge_sc[i] * model.parent_block().storage[si].energy_from_limit <= model.solar_deficit[i] + model.parent_block().storage[si].energy_from_limit * model.flag_arbitrage[i])
        m.solar_deficit_const_4 = pyo.Constraint(t, m.storageIndex, rule=lambda model, i, si: model.discharge_sc[i] * model.parent_block().storage[si].energy_from_limit >= model.solar_deficit[i] - model.parent_block().storage[si].energy_from_limit * model.flag_arbitrage[i])

        def charge_rule(model, i, si):
            return model.parent_block().storage[si].charge[i] == model.charge_arbitrage[i] + model.charge_sc[i]
        m.charge_const = pyo.Constraint(t, m.storageIndex, rule=charge_rule)

        def discharge_rule(model, i, si):
            return model.parent_block().storage[si].discharge[i] == model.discharge_arbitrage[i] + model.discharge_sc[i]
        m.controller_discharge_const = pyo.Constraint(t, m.storageIndex, rule=discharge_rule)


        # Objective function
        m.fob = pyo.Var(t, domain=PositiveReals)

        m.diff_flag_arbitrage = pyo.Var(t, domain=Binary)
        def diff_flag_arbitrage_const_1_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_flag_arbitrage[i] >= model.flag_arbitrage[i - 1] - model.flag_arbitrage[i]
        m.diff_flag_arbitrage_const_1 = pyo.Constraint(t, rule=diff_flag_arbitrage_const_1_rule)

        def diff_flag_arbitrage_const_2_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_flag_arbitrage[i] >= model.flag_arbitrage[i] - model.flag_arbitrage[i - 1]
        m.diff_flag_arbitrage_const_2 = pyo.Constraint(t, rule=diff_flag_arbitrage_const_2_rule)

        m.diff_charge_arbitrage = pyo.Var(t, domain=Binary)
        def diff_charge_arbitrage_const_1_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_charge_arbitrage[i] >= model.charge_arbitrage[i - 1] - model.charge_arbitrage[i]
        m.diff_charge_arbitrage_const_1 = pyo.Constraint(t, rule=diff_charge_arbitrage_const_1_rule)

        def diff_charge_arbitrage_const_2_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_charge_arbitrage[i] >= model.charge_arbitrage[i] - model.charge_arbitrage[i - 1]
        m.diff_charge_arbitrage_const_2 = pyo.Constraint(t, rule=diff_charge_arbitrage_const_2_rule)

        m.diff_discharge_arbitrage = pyo.Var(t, domain=Binary)
        def diff_discharge_arbitrage_const_1_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_discharge_arbitrage[i] >= model.discharge_arbitrage[i - 1] - model.discharge_arbitrage[i]
        m.diff_discharge_arbitrage_const_1 = pyo.Constraint(t, rule=diff_discharge_arbitrage_const_1_rule)

        def diff_discharge_arbitrage_const_2_rule(model, i):
            # If i is the first time in model.t, skip the constraint
            if i == model.parent_block().t.first():
                return pyo.Constraint.Skip
            return model.diff_discharge_arbitrage[i] >= model.discharge_arbitrage[i] - model.discharge_arbitrage[i - 1]
        m.diff_discharge_arbitrage_const_2 = pyo.Constraint(t, rule=diff_discharge_arbitrage_const_2_rule)

        m.fob_const = pyo.Constraint(
            t,
            rule=lambda model, i: model.fob[i] == model.command_penalty[i] * (model.diff_flag_arbitrage[i] + model.diff_charge_arbitrage[i] + model.diff_discharge_arbitrage[i]),
        )

        # Maximum number of arbitrage commands
        m.max_commands_const = pyo.Constraint(
             rule=lambda model: sum(model.diff_charge_arbitrage[i] + model.diff_discharge_arbitrage[i] for i in t) <= model.max_commands
        )

        # Battery SOC Specifications
        m.soc_specifications = pyo.Param(t, initialize=0.0, mutable=True)
        m.soc_specifications_const = pyo.Constraint(t, m.storageIndex, rule=lambda model, i, si: model.parent_block().storage[si].soc[i] >= model.soc_specifications[i])
