import pyomo.environ as pyo
from ..blocks import GridBlock, NodeBlock, IntelligentBatteryBlock, SimpleBatteryBlock


class SmartHome(pyo.AbstractModel):

    def __init__(
            self,
            is_grid_settled=True,
            *args, **kwargs):

        super(SmartHome, self).__init__(*args, **kwargs)

        ###################### INDEX #############################
        self.t = pyo.Set()

        self.node_index = pyo.Set()
        self.intelligent_bat_index = pyo.Set()
        self.simple_bat_index = pyo.Set()

        #################### BLOCKS ###############################
        self.grid = GridBlock(is_settled=is_grid_settled)
        self.node = NodeBlock(self.node_index)
        self.intelligent_bat = IntelligentBatteryBlock(self.intelligent_bat_index)
        self.simple_bat = SimpleBatteryBlock(self.simple_bat_index)

        #################### CONSTRAINTS ##########################
        def balance_rule(model: pyo.Model, i):

            energy_to = model.grid.energy_to[i]
            energy_from = model.grid.energy_from[i]

            for j in model.node_index:
                energy_to += model.node[j].energy_to[i]
                energy_from += model.node[j].energy_from[i]

            for j in model.simple_bat_index:
                energy_to += model.simple_bat[j].energy_to[i]
                energy_from += model.simple_bat[j].energy_from[i]

            for j in model.intelligent_bat_index:
                energy_to += model.intelligent_bat[j].energy_to[i]
                energy_from += model.intelligent_bat[j].energy_from[i]

            return energy_from == energy_to

        self.balance_const = pyo.Constraint(self.t, rule=balance_rule)

        #################### OBJECTIVE ###########################
        def objective_rule(model: pyo.Model):

            fob = 0.0

            for j in model.simple_bat_index:
                for i in model.t:
                    fob += model.simple_bat[j].fob[i]

            for j in model.intelligent_bat_index:
                for i in model.t:
                    fob += model.intelligent_bat[j].fob[i]

            for j in model.node_index:
                for i in model.t:
                    fob += model.node[j].fob[i]

            return fob

        self.obj = pyo.Objective(rule=objective_rule, sense=pyo.minimize)
