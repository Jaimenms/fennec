from typing import List, Optional, Tuple
import pyomo.environ as pyo
from pyomo.environ import Binary, PositiveReals


class BatteryBlock(pyo.ScalarBlock):

    def __init__(
        self,
        charging_energy_limit: List[float],
        discharging_energy_limit: List[float],
        capacity: float,
        soc_0: Optional[float],
        soc_specifications: Optional[List[Tuple[int, float, ]]],
        is_available: List[bool],
        has_variable_charge_power: bool,
        has_self_consumption_mode: bool,
        charging_efficiency: float,
        discharging_efficiency: float,
        command_penalty: List[float],
        load_energy: List[float] = None,
        pv_energy: List[float] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # Constants
        t_index = [i for i in range(len(charging_energy_limit))]

        ###################### INDEX #############################
        self.t = pyo.Set(initialize=t_index)
        self.t_shifted = pyo.Set(initialize=t_index[1:])

        #################### VARIABLES ###########################

        # Mode variable: m[t] = 1 means arbitrage mode; m[t] = 0 means self consumption.
        self.m = pyo.Var(self.t, domain=Binary)

        # Binary variable for charging power (dimensionless) in arbitrage mode.
        self.x = pyo.Var(self.t, domain=Binary)

        # Binary variable for discharging power (dimensionless) in arbitrage mode.
        self.z = pyo.Var(self.t, domain=Binary)

        # Continuous charging power (dimensionless) for self consumption.
        self.u = pyo.Var(self.t, bounds=(0, 1), domain=PositiveReals if has_variable_charge_power else Binary)

        # Continuous discharging power (dimensionless) for self consumption.
        self.v = pyo.Var(self.t, bounds=(0, 1), domain=PositiveReals if has_variable_charge_power else Binary)

        # State of charge
        self.soc = pyo.Var(self.t, bounds=(0, 100), domain=PositiveReals)

        # Energy to battery (charging)
        self.energy_to = pyo.Var(self.t, domain=PositiveReals)

        # Energy from battery (discharging)
        self.energy_from = pyo.Var(self.t, domain=PositiveReals)


        #################### PARAMETERS ###########################

        # Energy limits for charging in kWh
        self.energy_to_limit = pyo.Param(self.t, initialize={
            i: charging_efficiency * charging_energy_limit_i
            for i, charging_energy_limit_i in enumerate(charging_energy_limit)
        })

        # Energy limits for discharging in kWh
        self.energy_from_limit = pyo.Param(self.t, initialize={
            i: (1/discharging_efficiency) * discharging_energy_limit_i
            for i, discharging_energy_limit_i in enumerate(discharging_energy_limit)
        })

        #################### CONSTRAINTS ###########################

        # If the battery does not have self consumption mode, force m[t] to be always 1.
        if not has_self_consumption_mode:
            self.force_m_const = pyo.Constraint(self.t, rule=lambda model, i: model.m[i] == 1)

        # Guarantee that the energy to and from the battery are within the limits.
        self.energy_to_const = pyo.Constraint(
            self.t, rule=lambda model, i: model.energy_to[i] == model.energy_to_limit[i] * (model.x[i] + model.u[i])
        )
        self.energy_from_const = pyo.Constraint(
            self.t, rule=lambda model, i: model.energy_from[i] == model.energy_from_limit[i] * (model.z[i] + model.v[i])
        )

        # Settlement for x and z
        self.settling_1 = pyo.Var(self.t, domain=Binary)
        self.settlement_const_1 = pyo.Constraint(
            self.t, rule=lambda model, i: model.x[i] <= model.settling_1[i]
        )
        self.settlement_const_2 = pyo.Constraint(
            self.t, rule=lambda model, i: model.z[i] <= (1.0 - model.settling_1[i])
        )

        # Settlement for u and v
        self.settling_2 = pyo.Var(self.t, domain=Binary)
        self.settlement_const_3 = pyo.Constraint(
            self.t, rule=lambda model, i: model.u[i] <= model.settling_2[i]
        )
        self.settlement_const_4 = pyo.Constraint(
            self.t, rule=lambda model, i: model.v[i] <= (1.0 - model.settling_2[i])
        )

        # In arbitrage mode (m[t] = 1), force u[t] and v[t] to zero.
        self.m_1_const_u = pyo.Constraint(self.t, rule=lambda model, i: model.u[i] <= (1 - model.m[i]))
        self.m_1_const_v = pyo.Constraint(self.t, rule=lambda model, i: model.v[i] <= (1 - model.m[i]))

        # In self consumption mode (m[t] = 0), force arbitrage commands to zero.
        self.m_0_const_x = pyo.Constraint(self.t, rule=lambda model, i: model.x[i] <= model.m[i])
        self.m_0_const_z = pyo.Constraint(self.t, rule=lambda model, i: model.z[i] <= model.m[i])

        # Initial condition for m
        self.initial_m_const = pyo.Constraint(rule=lambda model: model.m[t_index[0]] == 0)

        # Guarantee that if the battery is not available, the commands are zero.
        if is_available is not None:
            self.is_available_param = pyo.Param(
                self.t, initialize={i: is_available_i * 1 for i, is_available_i in enumerate(is_available)}
            )
            self.is_available_const_u = pyo.Constraint(self.t, rule=lambda model, i: model.u[i] <= model.is_available_param[i])
            self.is_available_const_v = pyo.Constraint(self.t, rule=lambda model, i: model.v[i] <= model.is_available_param[i])
            self.is_available_const_x = pyo.Constraint(self.t, rule=lambda model, i: model.x[i] <= model.is_available_param[i])
            self.is_available_const_z = pyo.Constraint(self.t, rule=lambda model, i: model.z[i] <= model.is_available_param[i])

        # Solar surplus and deficit conditions for self consumption mode
        if has_self_consumption_mode:

            big_m = max(max(load_energy), max(pv_energy))

            # Solar Surplus condition in self-consumption mode will force battery charge
            self.solar_surplus = pyo.Param(self.t, initialize={
                i: max(0, pv_energy_i - load_energy_i)
                for i, (load_energy_i, pv_energy_i) in
                enumerate(zip(load_energy, pv_energy))
            })
            self.solar_surplus_const_1 = pyo.Constraint(
                self.t,
                rule=lambda model, i: model.u[i] * model.energy_to_limit[i] <= model.solar_surplus[i] + big_m * model.m[i]
            )
            self.solar_surplus_const_2 = pyo.Constraint(
                self.t,
                rule=lambda model, i: model.u[i] * model.energy_to_limit[i] >= model.solar_surplus[i] - big_m * model.m[i]
            )

            # Solar Deficit condition in self-consumption mode will force battery discharge
            self.solar_deficit = pyo.Param(self.t, initialize={
                i: max(0, load_energy_i - pv_energy_i)
                for i, (load_energy_i, pv_energy_i) in
                enumerate(zip(load_energy, pv_energy))
            })
            self.solar_deficit_const_1 = pyo.Constraint(
                self.t,
                rule=lambda model, i: model.v[i] * model.energy_from_limit[i] <= model.solar_deficit[i] + big_m * model.m[i]
            )
            self.solar_deficit_const_2 = pyo.Constraint(
                self.t,
                rule=lambda model, i: model.v[i] * model.energy_from_limit[i] >= model.solar_deficit[i] - big_m * model.m[i]
            )

        # Battery energy balance
        self.battery_capacity_const = pyo.Constraint(
            self.t_shifted,
            rule=lambda model, i: capacity * model.soc[i] == capacity * model.soc[i-1] + 100 * model.energy_to[i-1] - 100 * model.energy_from[i-1]
        )

        # Battery SOC Initial
        if soc_0 is not None:
            self.initial_soc_const = pyo.Constraint(rule=lambda model: model.soc[t_index[0]] == soc_0)

        # Battery SOC Specifications
        self.soc_specification_const = []
        for soc_index, soc_value in soc_specifications:
            self.soc_specification_const.append(pyo.Constraint(rule=lambda model: model.soc[t_index[soc_index]] >= soc_value))

        #################### OBJECTIVE ###########################

        self.fob = pyo.Var(self.t)

        # Calculate the differential between the binary variable m.
        self.diff_m = pyo.Var(self.t, domain=Binary)
        self.diff_m_const_1 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_m[i] >= model.m[i - 1] - model.m[i]
        )
        self.diff_m_const_2 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_m[i] >= model.m[i] - model.m[i - 1]
        )

        # Calculate the differential between the binary variable x.
        self.diff_x = pyo.Var(self.t, domain=Binary)
        self.diff_x_const_1 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_x[i] >= model.x[i - 1] - model.x[i]
        )
        self.diff_x_const_2 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_x[i] >= model.x[i] - model.x[i - 1]
        )

        # Calculate the differential between the binary variable z.
        self.diff_z = pyo.Var(self.t, domain=Binary)
        self.diff_z_const_1 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_z[i] >= model.z[i - 1] - model.z[i]
        )
        self.diff_z_const_2 = pyo.Constraint(
            self.t_shifted, rule=lambda model, i: model.diff_z[i] >= model.z[i] - model.z[i - 1]
        )

        # Objective function
        self.fob_const = pyo.Constraint(
            self.t,
            rule=lambda model, i: model.fob[i] == command_penalty[i] * (i+1) * (
                        model.diff_m[i] + model.diff_x[i] + model.diff_z[i]),
        )















