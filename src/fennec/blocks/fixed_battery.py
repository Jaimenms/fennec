from typing import List, Optional, Tuple
from .battery import BatteryBlock


class FixedBatteryBlock(BatteryBlock):

    def __init__(
        self,
        timestamps: List[float],
        charging_power: float,
        discharging_power: float,
        capacity: float,
        soc_0: Optional[float],
        soc_specifications: Optional[List[Tuple[int, float]]],
        charging_efficiency: float,
        discharging_efficiency: float,
        command_penalty: List[float],  # in $ per charging session
        load_power: List[float] = None,
        pv_power: List[float] = None,
        *args,
        **kwargs,
    ):

        super().__init__(
            timestamps=timestamps,
            charging_power=charging_power,
            discharging_power=discharging_power,
            capacity=capacity,
            soc_0=soc_0,
            soc_specifications=soc_specifications,
            is_available=[True for _ in range(len(timestamps))],
            has_variable_charge_power=True,
            has_self_consumption_mode=True,
            charging_efficiency=charging_efficiency,
            discharging_efficiency=discharging_efficiency,
            command_penalty=command_penalty,  # in $ per charging session
            load_power=load_power,
            pv_power=pv_power,
            *args,
            **kwargs
        )

