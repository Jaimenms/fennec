from typing import List

import pyomo.environ as pyo


class PhotovoltaicBlock(pyo.ScalarBlock):
    """
    Photovoltaic block
    """

    def __init__(
            self,
            timestamps: List[float],
            pv_power: List[float],
            *args, **kwargs
    ):
        """
        Constructor
        :param timestamps:
        :param delta_timestamps:
        :param pv_power:
        :param args:
        :param kwargs:
        """
        super().__init__(*args, **kwargs)

        # Constants
        n_index = len(timestamps)
        t_index = [i for i in range(n_index)]
        delta_timestamps = [timestamps[i + 1] - timestamps[i] for i in range(n_index - 1)] + [
            timestamps[-1] - timestamps[-2]
        ]

        ###################### INDEX #############################
        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])

        #################### PARAMETERS ##########################

        # Energy from the photovoltaic panels in kWh
        self.energy_from = pyo.Param(self.t, initialize={i: max(0, pv_power_i * delta_timestamps_i / 3600) for i, (pv_power_i, delta_timestamps_i) in enumerate(zip(pv_power, delta_timestamps))})

        #################### OBJECTIVE ###########################

        self.fob = pyo.Var(self.t)
        self.fob_const = pyo.Constraint(
            self.t,
            rule=lambda model, i: model.fob[i] == 0.0,
        )
