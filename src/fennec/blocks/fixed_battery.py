from typing import List, Optional, Tuple
from .battery import BatteryBlock


class FixedBatteryBlock(BatteryBlock):

    def __init__(
        self,
        name: str,
        charging_energy_limit: List[float],
        discharging_energy_limit: List[float],
        capacity: float,
        soc_0: Optional[float],
        soc_specifications: Optional[List[Tuple[int, float]]],
        charging_efficiency: float,
        discharging_efficiency: float,
        command_penalty: List[float],  # in $ per charging session
        load_energy: List[float] = None,
        pv_energy: List[float] = None,
        *args,
        **kwargs,
    ):

        super().__init__(
            name=name,
            charging_energy_limit=charging_energy_limit,
            discharging_energy_limit=discharging_energy_limit,
            capacity=capacity,
            soc_0=soc_0,
            soc_specifications=soc_specifications,
            is_available=[True for _ in range(len(charging_energy_limit))],
            has_variable_charge_power=True,
            has_self_consumption_mode=True,
            charging_efficiency=charging_efficiency,
            discharging_efficiency=discharging_efficiency,
            command_penalty=command_penalty,  # in $ per charging session
            load_energy=load_energy,
            pv_energy=pv_energy,
            *args,
            **kwargs
        )

