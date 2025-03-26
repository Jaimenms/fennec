from typing import List, Optional
import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


class BatteryBlock(pyo.Block):

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
        is_available: List[bool],
        has_variable_charge_power: bool,
        has_selfconsumption_mode: bool,
        charging_efficiency: float,
        discharging_efficiency: float,
        command_penalty: List[float],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        t_index = [i for i in range(len(timestamps))]

        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])

        self.m = None
        self.x = None
        self.z = None
        self.u = None
        self.v = None
        self.soc = None
        self.energy_to = None
        self.energy_from = None
        self.set_variables(has_variable_charge_power, has_selfconsumption_mode)

        self.diff_m = None
        self.energy_to_limit = None
        self.energy_from_limit = None
        self.is_available_param = None
        self.command_penalty = None
        self.set_parameters(
            timestamps, has_selfconsumption_mode, charging_efficiency, discharging_efficiency, charging_power, discharging_power, is_available, command_penalty
        )

        self.diff_x = None
        self.diff_z = None
        self.diff_m_const_1 = None
        self.diff_m_const_2 = None
        self.diff_x_const_1 = None
        self.diff_x_const_2 = None
        self.diff_z_const_1 = None
        self.diff_z_const_2 = None
        self.set_diff_consts()

        self.energy_to_const = None
        self.energy_from_const = None
        self.set_energy_consts()

        self.settlement_const_1 = None
        self.settlement_const_2 = None
        self.set_settlement_consts()

        self.m_1_const_u = None
        self.m_1_const_v = None
        self.m_0_const_x = None
        self.m_0_const_z = None
        self.set_arbitrage_consts()

        self.is_available_const_u = None
        self.is_available_const_v = None
        self.is_available_const_x = None
        self.is_available_const_z = None
        self.set_availability_consts()

        self.battery_capacity_const = None
        self.is_available_const = None
        self.initial_soc_const = None
        self.final_soc_const = None
        self.threshold_soc_const = None
        self.set_battery_consts(capacity, initial_soc, final_soc, threshold_soc, threshold_index)

        self.fob = None
        self.fob_const = None
        self.set_objective()

    def set_variables(self, has_variable_charge_power, has_selfconsumption_mode):
        """
        Set the variables for the battery block.
        :return:
        """

        # Mode variable: m[t] = 1 means arbitrage mode; m[t] = 0 means self consumption.
        if has_selfconsumption_mode:
            self.m = pyo.Var(self.t, domain=Binary)

        # Binary variable for charging power (dimensionless) in arbitrage mode.
        self.x = pyo.Var(self.t, domain=Binary)

        # Binary variable for discharging power (dimensionless) in arbitrage mode.
        self.z = pyo.Var(self.t, domain=Binary)

        # Continuous charging power (dimensionless) for self consumption.
        self.u = pyo.Var(self.t, domain=(0, 1) if has_variable_charge_power else Binary)

        # Continuous discharging power (dimensionless) for self consumption.
        self.v = pyo.Var(self.t, domain=(0, 1) if has_variable_charge_power else Binary)

        # State of charge in %
        self.soc = pyo.Var(self.t, domain=(0, 100.0))

        # Energy to battery (charging)
        self.energy_to = pyo.Var(self.t, domain=PositiveReals)

        # Energy from battery (discharging)
        self.energy_from = pyo.Var(self.t, domain=PositiveReals)


    def set_parameters(
        self, timestamps, has_selfconsumption_mode, charging_efficiency, discharging_efficiency, charging_power, discharging_power, is_available, command_penalty
    ):

        delta_timestamps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)] + [
            timestamps[-1] - timestamps[-2]
        ]

        if not has_selfconsumption_mode:
            self.m = pyo.Param(self.t, initialize={i: 1 for i, _ in enumerate(timestamps)})


        # Energy limits for charging
        _to_map = {
            t_i: charging_efficiency * charging_power * delta_timestamp_i / 3600
            for t_i, delta_timestamp_i in zip(self.t, delta_timestamps)
        }
        self.energy_to_limit = pyo.Param(self.t, initialize=_to_map)

        # Energy limits for discharging
        _from_map = {
            t_i: (1/discharging_efficiency) * discharging_power * delta_timestamp_i / 3600
            for t_i, delta_timestamp_i in zip(self.t, delta_timestamps)
        }
        self.energy_from_limit = pyo.Param(self.t, initialize=_from_map)

        self.is_available_param = pyo.Param(
            self.t, initialize={i: is_available * 1  for i, is_available_i in enumerate(is_available)}
        )

        self.command_penalty = pyo.Param(self.t, initialize={i: p for i, p in enumerate(command_penalty)})


    def set_diff_consts(self):
        """
        Set the constraints for the Switching variables.
        :return:
        """

        self.diff_m = pyo.Var(self.t, domain=Binary)
        self.diff_x = pyo.Var(self.t, domain=Binary)
        self.diff_z = pyo.Var(self.t, domain=Binary)

        self.diff_m_const_1 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_m[i] >= model.m[i - 1] - model.m[i]
        )
        self.diff_m_const_2 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_m[i] >= model.m[i] - model.m[i - 1]
        )
        self.diff_x_const_1 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_x[i] >= model.x[i - 1] - model.x[i]
        )
        self.diff_x_const_2 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_x[i] >= model.x[i] - model.x[i - 1]
        )
        self.diff_z_const_1 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_z[i] >= model.z[i - 1] - model.z[i]
        )
        self.diff_z_const_2 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_z[i] >= model.z[i] - model.z[i - 1]
        )

    def set_settlement_consts(self):
        """
        Set the constraints for the settlement variables.
        :return:
        """
        self.settlement_const_1 = pyo.Constraint(
            self.t, rule=lambda model, i: model.energy_from[i] <= model.energy_from_limit[i] * model.settling[i]
        )
        self.settlement_const_2 = pyo.Constraint(
            self.t, rule=lambda model, i: model.energy_to[i] <= model.energy_to_limit[i] * (1.0 - model.settling[i])
        )

    def set_energy_consts(self):
        """
        Set the constraints for the energy variables.
        :return:
        """
        self.energy_to_const = pyo.Constraint(
            self.t, rule=lambda model, i: model.energy_to[i] == model.energy_to_limit[i] * (model.x[i] + model.u[i])
        )
        self.energy_from_const = pyo.Constraint(
            self.t, rule=lambda model, i: model.energy_from[i] == model.energy_from_limit[i] * (model.z[i] + model.v[i])
        )

    def set_arbitrage_consts(self):

        # In arbitrage mode (m[t] = 1), force u[t] and v[t] to zero.
        self.m_1_const_u = pyo.Constraint(self.t, rule=lambda model, i: model.u[i] <= (1 - model.m[i]))
        self.m_1_const_v = pyo.Constraint(self.t, rule=lambda model, i: model.v[i] <= (1 - model.m[i]))

        # In self consumption mode (m[t] = 0), force arbitrage commands to zero.
        self.m_0_const_x = pyo.Constraint(self.t, rule=lambda model, i: model.x[i] <= model.m[i])
        self.m_0_const_z = pyo.Constraint(self.t, rule=lambda model, i: model.z[i] <= model.m[i])

    def set_availability_consts(self):

        self.is_available_const_u = pyo.Constraint(self.t, rule=lambda model, i: model.u[i] <= model.is_available_param[i])
        self.is_available_const_v = pyo.Constraint(self.t, rule=lambda model, i: model.v[i] <= model.is_available_param[i])
        self.is_available_const_x = pyo.Constraint(self.t, rule=lambda model, i: model.x[i] <= model.is_available_param[i])
        self.is_available_const_z = pyo.Constraint(self.t, rule=lambda model, i: model.z[i] <= model.is_available_param[i])

    def set_battery_consts(self, capacity, initial_soc, final_soc, threshold_soc, threshold_index):

        self.battery_capacity_const = pyo.Constraint(
            self.t_shifted,
            rule=lambda model, i: model.soc[i]
            == model.soc[i - 1] + model.energy_to[i] / capacity - model.energy_from[i] / capacity,
        )

        self.is_available_const = pyo.Constraint(self.t, rule=lambda model, i: model.x[i] <= model.is_available_param[i])

        if initial_soc is not None:
            self.initial_soc_const = pyo.Constraint(rule = lambda model: model.soc[0] == initial_soc)
        if final_soc is not None:
            self.final_soc_const = pyo.Constraint(rule = lambda model: model.soc[-1] == final_soc)
        if threshold_soc is not None:
            self.threshold_soc_const = pyo.Constraint(rule=lambda model: model.soc[threshold_index] >= threshold_soc)

    def set_objective(self):
        """
        Set the objective function for the battery block.
        :param start_charging_penalty:
        :return:
        """
        self.fob = pyo.Var(self.t)
        self.fob_const = pyo.Constraint(
            self.t,
            rule=lambda model, i: model.fob[i]
            == self.command_penalty[i] * (model.diff_m[i] + model.diff_x[i] + model.diff_z[i]),
        )


