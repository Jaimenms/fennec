"""Warm start, initial setpoints, daily command budgets and learned forecasts."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from fennec import Battery, ElectricVehicle, HuaweiLuna2000Controller, SmartHome
from fennec.rto import Audit, Engine, Health, Learner, Observation, Planner, RtoConfig

from .conftest import solve
from .test_rto import CONFIG, LOAD_KW, PV_KWH, T0, battery_msg, by_type, ev_msg

UTC = timezone.utc


def config(**overrides) -> RtoConfig:
    d = copy.deepcopy(CONFIG)
    d.update(overrides)
    return RtoConfig.from_dict(d)


# ---------------------------------------------------------------------- warm start


def test_warm_start_maps_the_previous_plan_onto_the_shifted_horizon():
    planner = Planner(config())
    engine = Engine(config(), planner=planner)
    engine.observe(battery_msg(T0, soc=47.0), T0)
    engine.observe(ev_msg(T0), T0)
    engine.tick(T0)
    first = engine.plan
    assert first.notes["warm_start_values"] == 0

    later = T0 + timedelta(minutes=15)
    engine.observe(battery_msg(later, soc=first.results.column("battery", "soc_end")[0]), later)
    engine.observe(ev_msg(later, soc=first.results.column("car", "soc")[1]), later)
    engine.tick(later)
    second = engine.plan
    assert second is not first
    assert second.notes["warm_start_values"] > 100
    assert second.results.status == "optimal"
    # the warm-started solve is as good as a cold one
    cold, _ = planner.build(later, engine.state)
    cold_results = cold.solve(**config().solver)
    assert second.results.objective == pytest.approx(cold_results.objective, rel=0.02)


def test_warm_start_from_a_horizon_with_different_step_lengths_stays_inside_bounds(horizon, grid, profiles):
    coarse_home = SmartHome(horizon, grid, profiles + [Battery("bat", 5.0, 2.5, 2.5, soc_initial=50.0, soc_min=10.0)])
    solve(coarse_home)
    from fennec import Horizon

    fine = Horizon(horizon.start, steps=8, delta_t=timedelta(minutes=5))
    fine_home = SmartHome(
        fine,
        grid,
        [
            type(profiles[0])("pv", energy=fine.resample(horizon.start, horizon.delta_t, profiles[0].energy)),
            type(profiles[1])("house", energy=fine.resample(horizon.start, horizon.delta_t, profiles[1].energy)),
            Battery("bat", 5.0, 2.5, 2.5, soc_initial=50.0, soc_min=10.0),
        ],
    )
    n = fine_home.warm_start_from(coarse_home)
    assert n > 0
    import pyomo.environ as pyo

    for v in fine_home.model.component_data_objects(pyo.Var, active=True):
        if v.value is not None:
            assert (v.lb is None or v.value >= v.lb - 1e-9) and (v.ub is None or v.value <= v.ub + 1e-9)
    results = fine_home.solve(warm_start=True, mip_rel_gap=1e-6)
    assert results.status == "optimal"


# ---------------------------------------------------------------------- initial setpoints


def test_initial_forced_setpoint_is_kept_when_no_command_is_allowed(grid, profiles):
    from fennec import Horizon

    h = Horizon(datetime(2025, 3, 22, tzinfo=UTC), steps=4, delta_t=timedelta(minutes=15))
    big = Battery(
        "bat",
        100.0,
        4.0,
        4.0,
        soc_initial=50.0,
        soc_min=10.0,
        controller=HuaweiLuna2000Controller(max_commands=0, initial_mode="forced", initial_charge_setpoint=0.5),
    )
    assets = [type(profiles[0])("pv", energy=[0.0] * 4), type(profiles[1])("house", energy=[0.3] * 4), big]
    results = solve(SmartHome(h, grid, assets))
    assert results.column("bat", "charge_setpoint") == pytest.approx([0.5] * 4)
    assert results.column("bat", "energy_to") == pytest.approx([0.5 * h.energy(4.0)] * 4)
    assert results.total("bat", "command") == 0


def test_initial_charger_state_is_kept_when_no_command_is_allowed(grid, profiles, horizon):
    car = ElectricVehicle(
        "car", 60.0, 3.0, plugged=[True] * horizon.steps, soc_initial=20.0, max_commands=0, initial_charge=1.0
    )
    results = solve(SmartHome(horizon, grid, profiles + [car]))
    assert all(c == pytest.approx(1.0) for c in results.column("car", "charge"))
    assert results.total("car", "command") == 0


def test_planner_passes_reported_setpoint_and_charger_state_to_the_models():
    planner = Planner(config())
    engine = Engine(config(), planner=planner)
    engine.observe(
        Observation.from_dict(
            {"type": "battery", "time": T0.isoformat(), "soc": 50, "mode": "forced", "setpoint_kw": -2.5}
        ),
        T0,
    )
    engine.observe(
        Observation.from_dict({"type": "ev", "time": T0.isoformat(), "plugged": True, "soc": 40, "charging": True}), T0
    )
    home, _ = planner.build(T0, engine.state)
    bat = next(a for a in home.assets if isinstance(a, Battery))
    car = next(a for a in home.assets if isinstance(a, ElectricVehicle))
    assert bat.controller.initial_mode == "forced"
    assert bat.controller.initial_charge_setpoint == 0.0 and bat.controller.initial_discharge_setpoint == 0.5
    assert car.initial_charge == 1.0


# ---------------------------------------------------------------------- daily command budget


def test_daily_command_budget_caps_the_optimizer_and_resets_after_a_day():
    cfg = config(limits={"battery": {"commands_per_day": 1}, "ev": {"commands_per_day": 1}})
    engine = Engine(cfg)
    engine.observe(battery_msg(T0), T0)
    engine.observe(ev_msg(T0), T0)
    out = engine.tick(T0)
    sent = by_type(out, "command")
    assert {c["device"] for c in sent} == {"battery", "car"}
    status = by_type(out, "status")[-1]
    assert status["commands_24h"] == {"battery": 1, "ev": 1}
    assert status["command_budgets"] == {"battery": 0, "ev": 0}

    later = T0 + timedelta(minutes=15)
    engine.observe(battery_msg(later), later)
    engine.observe(ev_msg(later), later)
    out = engine.tick(later)
    plan = engine.plan
    assert plan.notes["command_budgets"] == {"battery": 0, "ev": 0}
    assert plan.results.total("battery", "command") == 0 and plan.results.total("car", "command") == 0
    # a day later the budget is back
    much_later = T0 + timedelta(days=1, minutes=1)
    assert engine.budgets(much_later) == {"battery": 1, "ev": 1}


# ---------------------------------------------------------------------- learned forecasts


def clear_sky_kw(ts: datetime) -> float:
    return PV_KWH[ts.hour]


def feed_days(learner: Learner, start: datetime, days: int, pv_ratio: float = 0.5, measured_load: bool = True):
    t = start
    end = start + timedelta(days=days)
    while t < end:
        weekend = t.weekday() >= 5
        load = 2.0 if weekend else 1.0
        pv = pv_ratio * clear_sky_kw(t)
        battery = 0.3  # charging at a constant 0.3 kW, car never charging
        msgs = [
            {"type": "battery", "time": t.isoformat(), "soc": 50, "pv_kw": pv, "power_kw": battery},
            {"type": "ev", "time": t.isoformat(), "plugged": True, "soc": 40, "power_kw": 0.0},
        ]
        net = load - pv + battery
        meter = {"type": "meter", "time": t.isoformat(), "import_kw": max(0.0, net), "export_kw": max(0.0, -net)}
        if measured_load:
            meter["load_kw"] = load
        msgs.append(meter)
        for m in msgs:
            learner.observe(Observation.from_dict(m))
        t += timedelta(minutes=5)


def test_learner_needs_min_days_then_learns_pv_factor_and_load_profile():
    pv_cfg = {"energy_kwh_by_hour": PV_KWH, "factor": 0.8}
    learner = Learner(pv_cfg, days=14, min_days=3)
    start = datetime(2025, 3, 17, tzinfo=UTC)  # a Monday
    h = Planner(config()).horizon(start + timedelta(days=7))
    assert learner.pv(h) is None and learner.load(h) is None

    feed_days(learner, start, days=7)  # Monday to Sunday
    assert learner.summary()["pv_days"] == 7
    learned_pv = learner.pv(h)
    expected_pv = [0.5 * e for e in learner.clear_sky(h)]
    assert learned_pv == pytest.approx(expected_pv, abs=1e-6)

    learned_load = learner.load(h)  # the horizon starts on a Monday 00:00: weekday profile, 1 kW
    assert learned_load[0] == pytest.approx(1.0 * h.hours_at(0), abs=1e-6)
    saturday = Planner(config()).horizon(start + timedelta(days=12))
    assert learner.load(saturday)[0] == pytest.approx(2.0 * saturday.hours_at(0), abs=1e-6)


def test_learner_derives_the_load_from_the_balance_when_the_meter_does_not_measure_it():
    learner = Learner({"energy_kwh_by_hour": PV_KWH}, min_days=2)
    feed_days(learner, datetime(2025, 3, 17, tzinfo=UTC), days=3, measured_load=False)
    h = Planner(config()).horizon(datetime(2025, 3, 24, tzinfo=UTC))
    # net + pv - battery - car == load == 1 kW on weekdays
    assert learner.load(h)[0] == pytest.approx(1.0 * h.hours_at(0), abs=1e-6)


def test_learner_is_rebuilt_from_the_audit_file(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = Audit(path)
    learner = Learner({"energy_kwh_by_hour": PV_KWH}, min_days=2)
    start = datetime(2025, 3, 17, tzinfo=UTC)
    # write what the engine would write: one audit record per observation
    t = start
    while t < start + timedelta(days=3):
        for m in (
            {"type": "battery", "time": t.isoformat(), "soc": 50, "pv_kw": 0.5 * clear_sky_kw(t), "power_kw": 0.0},
            {"type": "meter", "time": t.isoformat(), "import_kw": 1.0, "export_kw": 0.0, "load_kw": 1.0},
        ):
            audit.write("observation", t, Observation.from_dict(m).to_dict())
        audit.write("health", t, {"health": "running"})
        t += timedelta(minutes=15)
    rebuilt = Learner.from_audit(path, {"energy_kwh_by_hour": PV_KWH}, days=14, min_days=2)
    assert rebuilt.summary()["pv_days"] == 3 and rebuilt.summary()["load_days"] == 3
    h = Planner(config()).horizon(start + timedelta(days=5))
    assert rebuilt.load(h)[0] == pytest.approx(h.hours_at(0), abs=1e-6)
    assert Learner.from_audit(tmp_path / "missing.jsonl", {"energy_kwh_by_hour": PV_KWH}).summary()["pv_days"] == 0


def test_engine_feeds_the_learner_and_uses_it_once_it_has_data():
    pv_cfg = {"energy_kwh_by_hour": PV_KWH, "factor": 0.8}
    learner = Learner(pv_cfg, min_days=2)
    engine = Engine(config(), learner=learner)
    start = datetime(2025, 3, 17, tzinfo=UTC)
    feed_days(learner, start, days=2)
    now = start + timedelta(days=2, hours=12)
    engine.observe(battery_msg(now), now)
    engine.observe(ev_msg(now), now)
    out = engine.tick(now)
    assert engine.plan.notes["learned"]["pv_days"] >= 2
    assert by_type(out, "status")[-1]["learned"]["pv_days"] >= 2
    h = engine.plan.horizon
    assert engine.plan.results.column("pv", "energy") == pytest.approx(
        [0.5 * e for e in learner.clear_sky(h)], abs=1e-6
    )
