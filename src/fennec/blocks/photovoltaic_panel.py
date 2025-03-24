from typing import List

import pyomo.environ as pyo


class PhotovoltaicPanel(pyo.Block):

    def __init__(
            self,
            name: str,
            t: pyo.Set,  # timestamps in seconds
            pv_power: List[float],  # in kW
            *args,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.name = name

        delta_t = []
        for i, ti in enumerate(t):
            delta_t.append(t[i+1] - ti if i+1 < len(t) else t[i] - t[i-1])

        self.energy_from = pyo.Param(t, initialize={ti: max(0, pv_power[i]*delta_t[i]) for i, ti in enumerate(t)})
