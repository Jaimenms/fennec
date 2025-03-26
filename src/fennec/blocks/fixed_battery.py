from typing import List, Optional
from .battery import BatteryBlock


class FixedBatteryBlock(BatteryBlock):

    def __init__(
        self,
        timestamps: List[float],
        charging_power: float,
        discharging_power: float,
        capacity: float,
        initial_soc: Optional[float],
        final_soc: Optional[float],
        threshold_soc: Optional[float],
        threshold_index: Optional[int],
        charging_efficiency: float,
        discharging_efficiency: float,
        command_penalty: List[float],  # in $ per charging session
        *args,
        **kwargs,
    ):

        super().__init__(
            timestamps=timestamps,
            charging_power=charging_power,
            discharging_power=discharging_power,
            capacity=capacity,
            initial_soc=initial_soc,
            final_soc=final_soc,
            threshold_soc=threshold_soc,
            threshold_index=threshold_index,
            is_available=[True for _ in range(len(timestamps))],
            has_variable_charge_power=True,
            has_selfconsumption_mode=True,
            charging_efficiency=charging_efficiency,
            discharging_efficiency=discharging_efficiency,
            command_penalty=command_penalty,  # in $ per charging session
            *args,
            **kwargs
        )

