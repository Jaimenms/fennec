from typing import List

import pyomo.environ as pyo


class PhotovoltaicBlock(pyo.Block):
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

        t_index = [i for i in range(len(timestamps))]

        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])

        self.energy_from = None
        self.set_parameters(timestamps, pv_power)

        self.fob = None
        self.fob_const = None
        self.set_objective()

    def set_parameters(self, timestamps: List[float], pv_power: List[float]):
        """
        Set parameters
        :param timestamps:
        :param pv_power:
        :return:
        """

        delta_timestamps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)] + [
            timestamps[-1] - timestamps[-2]
        ]

        self.energy_from = pyo.Param(self.t, initialize={i: max(0, pv_power_i * delta_i) for i, (pv_power_i, delta_i) in enumerate(zip(pv_power, delta_timestamps))})

    def set_objective(self):
        self.fob = pyo.Var(self.t)
        self.fob_const = pyo.Constraint(self.t, rule=lambda model, i: model.fob[i] == 0.0 )
