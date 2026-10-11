import pytest

from fennec import Battery, IdealController, SmartHome

from .conftest import solve


def make_battery(**kw) -> Battery:
    params = dict(
        name="bat",
        capacity_kwh=5.0,
        max_charge_kw=2.5,
        max_discharge_kw=2.5,
        soc_initial=50.0,
        soc_min=10.0,
        soc_max=100.0,
        controller=IdealController(),
    )
    params.update(kw)
    return Battery(**params)


def test_ideal_battery_never_costs_more_than_no_battery(horizon, grid, profiles):
    baseline = solve(SmartHome(horizon, grid, profiles))
    with_battery = solve(SmartHome(horizon, grid, profiles + [make_battery()]))
    assert with_battery.objective <= baseline.objective + 1e-9
    assert with_battery.cost("bat") == 0.0


def test_soc_window_and_no_simultaneous_charge_discharge(horizon, grid, profiles):
    results = solve(SmartHome(horizon, grid, profiles + [make_battery(soc_final_min=60.0)]))
    soc, soc_end = results.column("bat", "soc"), results.column("bat", "soc_end")
    assert all(10.0 - 1e-6 <= s <= 100.0 + 1e-6 for s in soc + soc_end)
    assert soc[0] == pytest.approx(50.0)
    assert soc_end[-1] >= 60.0 - 1e-6
    for t in horizon.index[1:]:
        assert soc[t] == pytest.approx(soc_end[t - 1], abs=1e-6)
    charge, discharge = results.column("bat", "energy_to"), results.column("bat", "energy_from")
    assert all(not (c > 1e-6 and d > 1e-6) for c, d in zip(charge, discharge))


def test_soc_required_is_honoured(horizon, grid, profiles):
    results = solve(SmartHome(horizon, grid, profiles + [make_battery(soc_required={20: 90.0})]))
    assert results.column("bat", "soc")[20] >= 90.0 - 1e-6


def test_validation_errors(horizon):
    with pytest.raises(ValueError):
        make_battery(soc_initial=5.0).validate(horizon)  # below soc_min
    with pytest.raises(ValueError):
        make_battery(charge_efficiency=1.2).validate(horizon)
    with pytest.raises(ValueError):
        make_battery(soc_required={999: 50.0}).validate(horizon)


def test_without_terminal_value_the_ideal_battery_is_drained_at_the_end(horizon, grid, profiles):
    drained = solve(SmartHome(horizon, grid, profiles + [make_battery(terminal_value=None)]))
    assert drained.column("bat", "soc_end")[-1] == pytest.approx(10.0, abs=1e-6)
    assert drained.terminal == {}
    assert drained.objective == pytest.approx(drained.cost(), abs=1e-6)


def test_terminal_value_pays_for_the_energy_left_in_the_battery(horizon, grid, profiles):
    results = solve(SmartHome(horizon, grid, profiles + [make_battery()]))  # default: cheapest import price
    bat = make_battery()
    price = min(grid.import_tariff.series(horizon))
    final_soc = results.column("bat", "soc_end")[-1]
    expected = -price * (bat.usable_kwh(final_soc) - bat.usable_kwh(bat.soc_initial))
    assert results.terminal_cost("bat") == pytest.approx(expected, abs=1e-6)
    assert results.objective == pytest.approx(results.cost() + results.terminal_cost(), abs=1e-6)
    assert results.notes["terminal_price"]["bat"] == pytest.approx(price)
    assert results.summary()["bat_stored_value"] == pytest.approx(-expected, abs=1e-6)
    # the valued plan is never worse than the drained plan scored with the same valuation
    drained = solve(SmartHome(horizon, grid, profiles + [make_battery(terminal_value=None)]))
    drained_final = drained.column("bat", "soc_end")[-1]
    drained_scored = drained.cost() - price * (bat.usable_kwh(drained_final) - bat.usable_kwh(bat.soc_initial))
    assert results.objective <= drained_scored + 1e-6


def test_numeric_and_mean_terminal_values(horizon, grid, profiles):
    numeric = solve(SmartHome(horizon, grid, profiles + [make_battery(terminal_value=0.5)]))
    assert numeric.notes["terminal_price"]["bat"] == 0.5
    # at 0.5 EUR/kWh stored energy is worth far more than any import price: the battery ends full
    assert numeric.column("bat", "soc_end")[-1] == pytest.approx(100.0, abs=1e-6)

    mean = solve(SmartHome(horizon, grid, profiles + [make_battery(terminal_value="mean_import_price")]))
    prices = grid.import_tariff.series(horizon)
    assert mean.notes["terminal_price"]["bat"] == pytest.approx(sum(prices) / len(prices))


def test_terminal_value_validation(horizon):
    with pytest.raises(ValueError):
        make_battery(terminal_value="market").validate(horizon)
    with pytest.raises(ValueError):
        make_battery(terminal_value=-1.0).validate(horizon)


def test_ideal_controller_commands_are_signed_powers_covering_the_horizon(horizon, grid, profiles):
    bat = make_battery()
    results = solve(SmartHome(horizon, grid, profiles + [bat]))
    cmds = bat.controller.commands(results, bat)
    assert cmds[0].at == horizon.start and cmds[-1].until == horizon.end
    assert all(c.action == "set_power" for c in cmds)
    assert all(a.until == b.at for a, b in zip(cmds, cmds[1:]))
    first = cmds[0]
    assert first.to_dict()["minutes"] == first.minutes
    assert bat.controller.describe().startswith("ideal")


def test_examples_build_and_the_baseline_solves():
    from fennec.examples import SCENARIOS, porto_vehicle, default_horizon

    homes = {name: build() for name, build in SCENARIOS.items()}
    assert set(homes) == {"baseline", "huawei_battery", "electric_vehicle", "battery_and_vehicle"}
    assert homes["battery_and_vehicle"].statistics()["binaries"] > homes["huawei_battery"].statistics()["binaries"]
    results = solve(homes["baseline"])
    assert results.objective > 0
    car = porto_vehicle(default_horizon(), leave="07:00", back="19:00", soc_on_return=35.0)
    assert car.soc_on_return and all(v == 35.0 for v in car.soc_on_return.values())
