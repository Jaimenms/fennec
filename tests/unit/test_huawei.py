"""
The self-consumption mode of the Huawei controller must reproduce the inverter's greedy rule exactly:
PV surplus charges the battery, load deficit is covered by the battery, each saturated by the power
limit and by the SOC window. The MILP is checked against a step-by-step simulation of that rule.
"""

import pytest

from fennec import Battery, HuaweiLuna2000Controller, IdealController, SmartHome

from .conftest import solve

CAP, POWER, EFF = 5.0, 2.5, 0.95
SOC0, SOC_MIN, SOC_MAX = 50.0, 10.0, 100.0


def battery(controller) -> Battery:
    return Battery(
        "bat",
        capacity_kwh=CAP,
        max_charge_kw=POWER,
        max_discharge_kw=POWER,
        soc_initial=SOC0,
        soc_min=SOC_MIN,
        soc_max=SOC_MAX,
        charge_efficiency=EFF,
        discharge_efficiency=EFF,
        controller=controller,
    )


def simulate_self_consumption(horizon, pv, load):
    e_max = horizon.energy(POWER)
    soc, rows = SOC0, []
    for t in horizon.index:
        surplus, deficit = max(0.0, pv[t] - load[t]), max(0.0, load[t] - pv[t])
        room = (SOC_MAX - soc) / 100 * CAP / EFF
        avail = (soc - SOC_MIN) / 100 * CAP * EFF
        e_to, e_from = min(surplus, e_max, room), min(deficit, e_max, avail)
        rows.append(dict(soc=soc, e_to=e_to, e_from=e_from, g_from=deficit - e_from, g_to=surplus - e_to))
        soc += 100 / CAP * (EFF * e_to - e_from / EFF)
    return rows


def assert_matches_simulation(results, expected, horizon):
    for t in horizon.index:
        assert results.column("bat", "soc")[t] == pytest.approx(expected[t]["soc"], abs=1e-6)
        assert results.column("bat", "energy_to")[t] == pytest.approx(expected[t]["e_to"], abs=1e-6)
        assert results.column("bat", "energy_from")[t] == pytest.approx(expected[t]["e_from"], abs=1e-6)
        assert results.column("grid", "energy_from")[t] == pytest.approx(expected[t]["g_from"], abs=1e-6)
        assert results.column("grid", "energy_to")[t] == pytest.approx(expected[t]["g_to"], abs=1e-6)


def test_scenario_exercises_every_saturation(horizon, pv_energy, load_energy):
    expected = simulate_self_consumption(horizon, pv_energy, load_energy)
    assert any(r["g_to"] > 1e-9 for r in expected), "battery never fills"
    assert any(r["g_from"] > 1e-9 and r["soc"] - SOC_MIN < 1e-6 for r in expected), "battery never empties"
    assert any(abs(r["e_to"] - horizon.energy(POWER)) < 1e-9 for r in expected), "charge power limit never reached"


def test_self_consumption_mode_matches_rule_based_simulation(horizon, grid, profiles, pv_energy, load_energy):
    controller = HuaweiLuna2000Controller(mode="self_consumption")
    results = solve(SmartHome(horizon, grid, profiles + [battery(controller)]))
    assert_matches_simulation(results, simulate_self_consumption(horizon, pv_energy, load_energy), horizon)
    assert results.total("bat", "command") == 0


def test_no_commands_from_self_consumption_keeps_the_inverter_alone(horizon, grid, profiles, pv_energy, load_energy):
    controller = HuaweiLuna2000Controller(max_commands=0, initial_mode="self_consumption")
    results = solve(SmartHome(horizon, grid, profiles + [battery(controller)]))
    assert_matches_simulation(results, simulate_self_consumption(horizon, pv_energy, load_energy), horizon)


def test_optimized_modes_sit_between_ideal_and_self_consumption(horizon, grid, profiles):
    ideal = solve(SmartHome(horizon, grid, profiles + [battery(IdealController())]))
    sc = solve(SmartHome(horizon, grid, profiles + [battery(HuaweiLuna2000Controller(mode="self_consumption"))]))
    optimized = solve(SmartHome(horizon, grid, profiles + [battery(HuaweiLuna2000Controller(max_commands=6))]))
    forced = solve(SmartHome(horizon, grid, profiles + [battery(HuaweiLuna2000Controller(mode="forced"))]))

    assert ideal.objective <= optimized.objective + 1e-6 <= sc.objective + 2e-6
    assert optimized.total("bat", "command") <= 6 + 1e-6
    # a fully commanded battery with unlimited commands is the ideal battery
    assert forced.objective == pytest.approx(ideal.objective, abs=1e-6)

    cols = optimized.data["bat"]
    for t in horizon.index:
        if round(cols["self_consumption"][t]) == 1:
            assert cols["charge_setpoint"][t] == pytest.approx(0.0, abs=1e-6)
            assert cols["discharge_setpoint"][t] == pytest.approx(0.0, abs=1e-6)
        else:
            assert cols["energy_to"][t] == pytest.approx(horizon.energy(POWER) * cols["charge_setpoint"][t], abs=1e-6)


def test_command_penalty_enters_the_battery_cost(horizon, grid, profiles):
    controller = HuaweiLuna2000Controller(max_commands=6, command_penalty=0.05)
    results = solve(SmartHome(horizon, grid, profiles + [battery(controller)]))
    assert results.cost("bat") == pytest.approx(0.05 * results.total("bat", "command"), abs=1e-6)
    assert results.objective == pytest.approx(
        results.cost("grid") + results.cost("bat") + results.terminal_cost("bat"), abs=1e-6
    )


def test_controller_validation(horizon):
    with pytest.raises(ValueError):
        battery(HuaweiLuna2000Controller(mode="tou")).validate(horizon)
    with pytest.raises(ValueError):
        battery(HuaweiLuna2000Controller(initial_mode="idle")).validate(horizon)
