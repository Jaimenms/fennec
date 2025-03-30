import pyomo.environ as pyo


class NodeBlock(pyo.Block):
    """
    Node block
    """

    def __init__(self, *args, **kwargs):
        super().__init__(rule=self.rule, *args, **kwargs )


    @staticmethod
    def rule(m: pyo.Model):

        ###################### INDEX #############################
        t = m.parent_block().t

        #################### PARAMETERS ##########################

        # Energy from the photovoltaic panels in kWh
        m.energy_from = pyo.Param(t, initialize=0.0, mutable=True)

        # Energy to the photovoltaic panels in kWh (ONLY FOR SYMMETRY WITH THE BATTERY BLOCK)
        m.energy_to = pyo.Param(t, initialize=0.0, mutable=True)

        #################### OBJECTIVE ###########################

        m.fob = pyo.Var(t)
        m.fob_const = pyo.Constraint(
            t,
            rule=lambda model, i: model.fob[i] == 0.0,
        )
