from typing import List, Optional
from .battery import BatteryBlock


class VehicleBatteryBlock(BatteryBlock):

    def __init__(
        self,
        timestamps: List[float],
        is_available: List[bool],
        charging_power: float,
        capacity: float,
        initial_soc: Optional[float],
        final_soc: Optional[float],
        threshold_soc: Optional[float],
        threshold_index: Optional[int],
        charging_efficiency: float,
        command_penalty: List[float],  # in $ per command
        *args,
        **kwargs,
    ):

        super().__init__(
            timestamps=timestamps,
            charging_power=charging_power,
            discharging_power=0.0,
            capacity=capacity,
            initial_soc=initial_soc,
            final_soc=final_soc,
            threshold_soc=threshold_soc,
            threshold_index=threshold_index,
            is_available=is_available,
            has_variable_charge_power=False,
            has_selfconsumption_mode=False,
            charging_efficiency=charging_efficiency,
            discharging_efficiency=1.0,
            command_penalty=command_penalty,  # in $ per charging session
            *args,
            **kwargs
        )
