import pyomo.environ as pyo
from .. import blocks

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
        self.vehicleIndex = pyo.Set()
        self.vehicleControllerIndex = pyo.Set()

        #################### BLOCKS ###############################
        self.grid = blocks.GridBlock(is_settled=is_grid_settled)
        self.node = blocks.NodeBlock(self.nodeIndex)
        self.storage = blocks.Storage(self.storageIndex)
        self.vehicle = blocks.Vehicle(self.vehicleIndex)
        self.storageController = blocks.StorageController(self.storageControllerIndex)
        self.vehicleController = blocks.VehicleController(self.vehicleControllerIndex)

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

            for j in model.vehicleIndex:
                energy_to += model.vehicle[j].energy_to[i]

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
                for j in model.vehicleControllerIndex:
                    fob += model.vehicleController[j].fob[i]

            return fob

        self.obj = pyo.Objective(rule=objective_rule, sense=pyo.minimize)
