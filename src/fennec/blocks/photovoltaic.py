from typing import List

import pyomo.environ as pyo


class PhotovoltaicBlock(pyo.ScalarBlock):
    """
    Photovoltaic block
    """

    def __init__(
            self,
            name: str,
            pv_energy: List[float],
            *args, **kwargs
    ):
        """
        Constructor
        :param timestamps:
        :param delta_timestamps:
        :param pv_energy:
        :param args:
        :param kwargs:
        """
        super().__init__(*args, **kwargs)

        # Constants
        t_index = [i for i in range(len(pv_energy))]
        self.name = name

        ###################### INDEX #############################
        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])

        #################### PARAMETERS ##########################

        # Energy from the photovoltaic panels in kWh
        self.energy_from = pyo.Param(self.t, initialize={i: pv_energy_i for i, pv_energy_i in enumerate(pv_energy)})

        # Energy to the photovoltaic panels in kWh (ONLY FOR SYMMETRY WITH THE BATTERY BLOCK)
        self.energy_to = pyo.Param(self.t, initialize={i: 0 for i in t_index})

        #################### OBJECTIVE ###########################

        self.fob = pyo.Var(self.t)
        self.fob_const = pyo.Constraint(
            self.t,
            rule=lambda model, i: model.fob[i] == 0.0,
        )
