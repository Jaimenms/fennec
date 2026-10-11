import pytest

from fennec import ElectricVehicle, SmartHome

from .conftest import solve


def make_ev(horizon, **kw) -> ElectricVehicle:
    plugged, returns = ElectricVehicle.daily_trip(horizon, leave="03:00", back="08:00", soc_on_return=30.0)
    params = dict(
        name="car",
        capacity_kwh=20.0,
        max_charge_kw=3.0,  # with the 0.9 kWh/step load this fits under the 6.9 kW contracted power
        plugged=plugged,
        soc_initial=40.0,
        soc_on_return=returns,
        soc_target={horizon.first_steps_at("03:00")[0]: 80.0},
        target_penalty=1.0,
        max_commands=4,
    )
    params.update(kw)
    return ElectricVehicle(**params)


def test_daily_trip_builds_availability_and_return_events(horizon):
    plugged, returns = ElectricVehicle.daily_trip(horizon, "03:00", "08:00", 30.0)
    assert plugged[11] and not plugged[12] and not plugged[31] and plugged[32]
    assert returns == {32: 30.0}


def test_car_only_charges_while_plugged_and_returns_at_the_given_soc(horizon, grid, profiles):
    ev = make_ev(horizon)
    results = solve(SmartHome(horizon, grid, profiles + [ev]))
    energy = results.column("car", "energy_to")
    soc = results.column("car", "soc")
    for t in horizon.index:
        if not ev.plugged[t]:
            assert energy[t] == pytest.approx(0.0, abs=1e-9)
            if t > 0 and not ev.plugged[t - 1]:
                assert soc[t] is None  # away: SOC not tracked
    assert soc[32] == pytest.approx(30.0)
    assert soc[0] == pytest.approx(40.0)
    # 12 plugged steps before leaving at 0.75 kWh each reach the 80 % target (40 % -> ~82 %)
    assert soc[12] >= 80.0 - 1e-6
    assert results.cost("car") == pytest.approx(0.0, abs=1e-6)
    assert results.total("car", "command") <= 4


def test_unreachable_target_is_penalised_not_infeasible(horizon, grid, profiles):
    ev = make_ev(horizon, max_charge_kw=0.4, target_penalty=2.0)
    results = solve(SmartHome(horizon, grid, profiles + [ev]))
    shortfall = 80.0 - results.column("car", "soc")[12]
    assert shortfall > 0
    assert results.cost("car") == pytest.approx(2.0 * shortfall, abs=1e-6)


def test_modulated_charger_can_use_fractions_of_the_power(horizon, grid, profiles):
    ev = make_ev(horizon, modulated=True)
    results = solve(SmartHome(horizon, grid, profiles + [ev]))
    charge = results.column("car", "charge")
    assert all(-1e-9 <= c <= 1 + 1e-9 for c in charge)


def test_missing_soc_on_return_is_rejected(horizon):
    plugged, _ = ElectricVehicle.daily_trip(horizon, "03:00", "08:00", 30.0)
    with pytest.raises(ValueError, match="soc_on_return missing"):
        ElectricVehicle("car", 20.0, 3.0, plugged=plugged).validate(horizon)
    with pytest.raises(ValueError, match="not a return step"):
        ElectricVehicle("car", 20.0, 3.0, plugged=plugged, soc_on_return={5: 30.0, 32: 30.0}).validate(horizon)


def test_charge_on_arrival_profile_fills_the_car_as_soon_as_possible(horizon):
    ev = make_ev(horizon)
    profile = ev.charge_on_arrival(horizon)
    assert len(profile) == horizon.steps
    assert all(e == 0.0 for e, p in zip(profile, ev.plugged) if not p)
    # 40 % -> 100 % of 20 kWh at 0.95 efficiency needs 12.63 kWh: the 12 steps before leaving are all full
    assert profile[:12] == [pytest.approx(0.75)] * 12
    # back at 30 %: 14.7 kWh needed, only 16 steps of 0.75 kWh left, so the charger never stops
    assert profile[32:] == [pytest.approx(0.75)] * 16


def test_charge_on_arrival_respects_a_per_step_cap(horizon):
    ev = make_ev(horizon)
    cap = [0.5] * horizon.steps
    profile = ev.charge_on_arrival(horizon, max_energy=cap)
    assert max(profile) == pytest.approx(0.5)
    assert sum(profile) < sum(ev.charge_on_arrival(horizon))
