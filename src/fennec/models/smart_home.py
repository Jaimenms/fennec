import pyomo.environ as pyo
from ..blocks import GridBlock, NodeBlock, Storage, StorageController


class SmartHome(pyo.AbstractModel):

    def __init__(
            self,
            is_grid_settled=True,
            *args, **kwargs):

        super(SmartHome, self).__init__(*args, **kwargs)

        ###################### INDEX #############################
        self.t = pyo.Set()

        self.nodeIndex = pyo.Set()
        self.storageIndex = pyo.Set()
        self.storageControllerIndex = pyo.Set()

        #################### BLOCKS ###############################
        self.grid = GridBlock(is_settled=is_grid_settled)
        self.node = NodeBlock(self.nodeIndex)
        self.storage = Storage(self.storageIndex)
        self.storageController = StorageController(self.storageControllerIndex)

        #################### CONSTRAINTS ##########################
        def balance_rule(model: pyo.Model, i):

            energy_to = model.grid.energy_to[i]
            energy_from = model.grid.energy_from[i]

            for j in model.nodeIndex:
                energy_to += model.node[j].energy_to[i]
                energy_from += model.node[j].energy_from[i]

            for j in model.storageIndex:
                energy_to += model.storage[j].energy_to[i]
                energy_from += model.storage[j].energy_from[i]

            return energy_from == energy_to

        self.balance_const = pyo.Constraint(self.t, rule=balance_rule)

        #################### OBJECTIVE ###########################
        def objective_rule(model: pyo.Model):

            fob = 0.0
            for i in model.t:
                fob += model.grid.fob[i]
                for j in model.storageIndex:
                    fob += model.storage[j].fob[i]
                for j in model.nodeIndex:
                    fob += model.node[j].fob[i]
                for j in model.storageControllerIndex:
                    fob += model.storageController[j].fob[i]

            return fob

        self.obj = pyo.Objective(rule=objective_rule, sense=pyo.minimize)
