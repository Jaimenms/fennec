from typing import List, Optional, Tuple
from .battery import BatteryBlock


class VehicleBatteryBlock(BatteryBlock):

    def __init__(
        self,
        name: str,
        is_available: List[bool],
        charging_energy_limit: List[float],
        capacity: float,
        soc_0: Optional[float],
        soc_specifications: Optional[List[Tuple[int, float, ]]],
        charging_efficiency: float,
        command_penalty: List[float],  # in $ per command
        *args,
        **kwargs,
    ):

        super().__init__(
            name=name,
            charging_energy_limit=charging_energy_limit,
            discharging_energy_limit=[0.0,] * len(charging_energy_limit),
            capacity=capacity,
            soc_0=soc_0,
            soc_specifications=soc_specifications,
            is_available=is_available,
            has_variable_charge_power=False,
            has_self_consumption_mode=False,
            charging_efficiency=charging_efficiency,
            discharging_efficiency=1.0,
            command_penalty=command_penalty,  # in $ per charging session
            *args,
            **kwargs
        )
