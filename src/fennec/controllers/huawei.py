"""Huawei SUN2000 hybrid inverter with LUNA2000 batteries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

import pyomo.environ as pyo
from pyomo.environ import Binary

from ..commands import Command, group_steps, step_span
from ..horizon import Horizon
from ..results import Results, values
from .base import BatteryController

if TYPE_CHECKING:  # pragma: no cover
    from ..assets.base import BuildContext
    from ..assets.battery import Battery

SELF_CONSUMPTION = "self_consumption"
FORCED = "forced"
OPTIMIZE = "optimize"


@dataclass
class HuaweiLuna2000Controller(BatteryController):
    """
    At every step the inverter is in one of two modes, chosen by the binary ``self_consumption[t]``.

    **Self consumption** (``self_consumption[t] = 1``). The inverter runs its own greedy rule and the
    optimizer has no say on the power: PV surplus charges the battery and load deficit is covered by the
    battery, each saturated by the power limit and by the SOC window. The rule is written as
    complementarity conditions measured at the grid meter, which is what the inverter sees:

    * the battery never charges while the house imports, and never discharges while it exports;
    * the house only imports if the discharge is saturated (power limit, or battery empty at the end of
      the step);
    * the house only exports if the charge is saturated (power limit, or battery full at the end of the
      step).

    **Forced** (``self_consumption[t] = 0``). The setpoints ``charge_setpoint`` / ``discharge_setpoint``
    (fraction of the power limit) are decision variables, as with a forcible charge/discharge command;
    grid charging is allowed.

    Any change of mode or of a setpoint between consecutive steps is one **command**. Commands are
    limited by ``max_commands`` and penalised by ``command_penalty``.

    ``mode`` pins the inverter to one mode for the whole horizon (``"self_consumption"`` reproduces the
    inverter left alone, ``"forced"`` is a fully commanded battery); ``"optimize"`` lets the optimizer
    schedule the modes. ``initial_mode`` is the mode the inverter is in before the first step; when
    given, changing it at the first step counts as a command.
    """

    max_commands: int = 100
    command_penalty: float = 0.0
    mode: str = OPTIMIZE
    initial_mode: Optional[str] = None
    initial_charge_setpoint: Optional[float] = None  # fraction of the power limit in force before step 0
    initial_discharge_setpoint: Optional[float] = None

    def validate(self, battery: "Battery", horizon: Horizon) -> None:
        if self.mode not in (OPTIMIZE, SELF_CONSUMPTION, FORCED):
            raise ValueError(f"mode must be one of {OPTIMIZE!r}, {SELF_CONSUMPTION!r}, {FORCED!r}")
        if self.initial_mode not in (None, SELF_CONSUMPTION, FORCED):
            raise ValueError(f"initial_mode must be None, {SELF_CONSUMPTION!r} or {FORCED!r}")
        if self.max_commands < 0:
            raise ValueError("max_commands must be non-negative")
        for value in (self.initial_charge_setpoint, self.initial_discharge_setpoint):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError("initial setpoints are fractions of the power limit, in [0, 1]")

    def build(self, b: pyo.Block, battery: "Battery", ctx: "BuildContext") -> None:
        h, t = ctx.horizon, ctx.t
        grid = ctx.require_grid(f"{battery.name}: HuaweiLuna2000Controller")
        e_to, e_from = battery.charge_limits(h), battery.discharge_limits(h)
        soc_span = battery.soc_max - battery.soc_min
        import_max = max(grid.energy_from[i].ub for i in h.index)
        export_max = max(grid.energy_to[i].ub for i in h.index)

        # ---------------------------------------------------------------- variables
        b.self_consumption = pyo.Var(t, domain=Binary)
        b.charge_setpoint = pyo.Var(t, bounds=(0, 1))
        b.discharge_setpoint = pyo.Var(t, bounds=(0, 1))
        b.importing = pyo.Var(t, domain=Binary)  # SC indicator: house imports in this step
        b.exporting = pyo.Var(t, domain=Binary)  # SC indicator: house exports in this step
        b.discharge_at_power_limit = pyo.Var(t, domain=Binary)  # which saturation explains the import
        b.charge_at_power_limit = pyo.Var(t, domain=Binary)  # which saturation explains the export
        b.command = pyo.Var(t, domain=Binary)

        if self.mode == SELF_CONSUMPTION:
            for i in h.index:
                b.self_consumption[i].fix(1)
        elif self.mode == FORCED:
            for i in h.index:
                b.self_consumption[i].fix(0)

        sc = b.self_consumption

        # ---------------------------------------------------------------- forced mode
        # setpoints are zero in SC mode; in forced mode the battery follows them
        b.charge_setpoint_mode = pyo.Constraint(t, rule=lambda blk, i: blk.charge_setpoint[i] <= 1 - sc[i])
        b.discharge_setpoint_mode = pyo.Constraint(t, rule=lambda blk, i: blk.discharge_setpoint[i] <= 1 - sc[i])
        b.charge_follows_setpoint_1 = pyo.Constraint(
            t, rule=lambda blk, i: blk.energy_to[i] - e_to[i] * blk.charge_setpoint[i] <= e_to[i] * sc[i]
        )
        b.charge_follows_setpoint_2 = pyo.Constraint(
            t, rule=lambda blk, i: blk.energy_to[i] - e_to[i] * blk.charge_setpoint[i] >= -e_to[i] * sc[i]
        )
        b.discharge_follows_setpoint_1 = pyo.Constraint(
            t, rule=lambda blk, i: blk.energy_from[i] - e_from[i] * blk.discharge_setpoint[i] <= e_from[i] * sc[i]
        )
        b.discharge_follows_setpoint_2 = pyo.Constraint(
            t, rule=lambda blk, i: blk.energy_from[i] - e_from[i] * blk.discharge_setpoint[i] >= -e_from[i] * sc[i]
        )

        # ---------------------------------------------------------------- self consumption mode
        # every constraint is relaxed by a (1 - sc) term so it only binds in SC mode
        b.importing_indicator = pyo.Constraint(
            t, rule=lambda blk, i: grid.energy_from[i] <= import_max * (blk.importing[i] + 1 - sc[i])
        )
        b.exporting_indicator = pyo.Constraint(
            t, rule=lambda blk, i: grid.energy_to[i] <= export_max * (blk.exporting[i] + 1 - sc[i])
        )
        # never charge from the grid, never discharge to the grid
        b.sc_no_grid_charge = pyo.Constraint(
            t, rule=lambda blk, i: blk.energy_to[i] <= e_to[i] * (1 - blk.importing[i] + 1 - sc[i])
        )
        b.sc_no_battery_export = pyo.Constraint(
            t, rule=lambda blk, i: blk.energy_from[i] <= e_from[i] * (1 - blk.exporting[i] + 1 - sc[i])
        )
        # importing  =>  discharge saturated: at the power limit, or battery empty at the end of the step
        b.sc_import_power_saturation = pyo.Constraint(
            t,
            rule=lambda blk, i: e_from[i] - blk.energy_from[i]
            <= e_from[i] * (1 - blk.importing[i] + 1 - blk.discharge_at_power_limit[i] + 1 - sc[i]),
        )
        b.sc_import_soc_saturation = pyo.Constraint(
            t,
            rule=lambda blk, i: blk.soc_end[i] - battery.soc_min
            <= soc_span * (1 - blk.importing[i] + blk.discharge_at_power_limit[i] + 1 - sc[i]),
        )
        # exporting  =>  charge saturated: at the power limit, or battery full at the end of the step
        b.sc_export_power_saturation = pyo.Constraint(
            t,
            rule=lambda blk, i: e_to[i] - blk.energy_to[i]
            <= e_to[i] * (1 - blk.exporting[i] + 1 - blk.charge_at_power_limit[i] + 1 - sc[i]),
        )
        b.sc_export_soc_saturation = pyo.Constraint(
            t,
            rule=lambda blk, i: battery.soc_max - blk.soc_end[i]
            <= soc_span * (1 - blk.exporting[i] + blk.charge_at_power_limit[i] + 1 - sc[i]),
        )
        # symmetry-breaking: indicators are meaningless outside SC mode, choosers when their indicator
        # is off; importing and exporting together is never feasible in SC mode
        b.importing_only_in_sc = pyo.Constraint(t, rule=lambda blk, i: blk.importing[i] <= sc[i])
        b.exporting_only_in_sc = pyo.Constraint(t, rule=lambda blk, i: blk.exporting[i] <= sc[i])
        b.import_export_exclusive = pyo.Constraint(t, rule=lambda blk, i: blk.importing[i] + blk.exporting[i] <= 1)
        b.discharge_chooser_mode = pyo.Constraint(
            t, rule=lambda blk, i: blk.discharge_at_power_limit[i] <= blk.importing[i]
        )
        b.charge_chooser_mode = pyo.Constraint(t, rule=lambda blk, i: blk.charge_at_power_limit[i] <= blk.exporting[i])

        # ---------------------------------------------------------------- commands
        initial_charge, initial_discharge = self.initial_charge_setpoint, self.initial_discharge_setpoint
        if self.initial_mode == SELF_CONSUMPTION:  # no setpoint is in force in self-consumption mode
            initial_charge, initial_discharge = 0.0, 0.0

        def previous(signal, i):
            """Value of a signal at the step before ``i`` (what is in force before the first step)."""
            if i > 0:
                return signal[i - 1]
            if signal is sc and self.initial_mode is not None:
                return 1 if self.initial_mode == SELF_CONSUMPTION else 0
            if signal is b.charge_setpoint:
                return initial_charge
            if signal is b.discharge_setpoint:
                return initial_discharge
            return None

        def command_rule(signal, sign):
            def rule(blk, i):
                prev = previous(signal, i)
                if prev is None:
                    return pyo.Constraint.Skip
                return blk.command[i] >= sign * (signal[i] - prev)

            return rule

        b.command_mode_up = pyo.Constraint(t, rule=command_rule(sc, +1))
        b.command_mode_down = pyo.Constraint(t, rule=command_rule(sc, -1))
        b.command_charge_up = pyo.Constraint(t, rule=command_rule(b.charge_setpoint, +1))
        b.command_charge_down = pyo.Constraint(t, rule=command_rule(b.charge_setpoint, -1))
        b.command_discharge_up = pyo.Constraint(t, rule=command_rule(b.discharge_setpoint, +1))
        b.command_discharge_down = pyo.Constraint(t, rule=command_rule(b.discharge_setpoint, -1))
        b.max_commands_const = pyo.Constraint(expr=sum(b.command[i] for i in h.index) <= self.max_commands)

        b.cost = pyo.Expression(t, rule=lambda blk, i: self.command_penalty * blk.command[i])

    def extract(self, block: pyo.Block, horizon: Horizon) -> Dict[str, List[Optional[float]]]:
        return {
            "self_consumption": values(block.self_consumption, horizon),
            "charge_setpoint": values(block.charge_setpoint, horizon),
            "discharge_setpoint": values(block.discharge_setpoint, horizon),
            "command": values(block.command, horizon),
        }

    def commands(self, results: Results, battery: "Battery") -> List[Command]:
        """
        One command per run of steps with the same intent: ``set_mode`` (self consumption),
        ``force_charge`` / ``force_discharge`` with ``power_kw`` and the duration of the run, or ``hold``
        (forced mode with no power, i.e. the battery kept idle).
        """
        h = results.horizon
        cols = results.data[battery.name]

        def key(t):
            if round(cols["self_consumption"][t] or 0.0) == 1:
                return ("self_consumption", 0.0)
            charge = round((cols["charge_setpoint"][t] or 0.0) * battery.max_charge_kw, 2)
            discharge = round((cols["discharge_setpoint"][t] or 0.0) * battery.max_discharge_kw, 2)
            if charge > 0:
                return ("force_charge", charge)
            if discharge > 0:
                return ("force_discharge", discharge)
            return ("hold", 0.0)

        def make(first, last, k):
            action, power = k
            at, until = step_span(h, first, last)
            if action == "self_consumption":
                return Command(battery.name, "set_mode", at, until, {"mode": SELF_CONSUMPTION})
            if action == "hold":
                return Command(battery.name, "hold", at, until, {})
            return Command(battery.name, action, at, until, {"power_kw": power})

        return group_steps(h, key, make)

    def describe(self) -> str:
        return f"Huawei LUNA2000 (mode={self.mode}, max_commands={self.max_commands})"
