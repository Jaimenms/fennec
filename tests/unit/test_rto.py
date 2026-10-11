"""The real-time optimizer: message contract, health state machine, planner and the closed loop with the twin."""

import asyncio
import copy
import time
from datetime import datetime, timedelta, timezone

import pytest

from fennec.rto import Daemon, Engine, Health, MemoryTransport, MessageError, Observation, Planner, RtoConfig, Twin
from fennec.rto.twin import TwinBattery, TwinVehicle
from fennec.tariffs import import_bi_daily_tariff

UTC = timezone.utc
T0 = datetime(2025, 3, 22, 18, 0, tzinfo=UTC)  # the car is back, the evening peak starts

LOAD_KW = [
    0.6,
    0.6,
    0.6,
    0.6,
    0.6,
    0.6,
    1.2,
    1.8,
    1.8,
    1.2,
    1.2,
    1.2,
    1.2,
    1.2,
    1.2,
    1.2,
    1.2,
    1.8,
    3.0,
    3.0,
    3.0,
    3.0,
    1.8,
    0.6,
]
PV_KWH = [0, 0, 0, 0, 0, 0, 0, 0.2, 0.8, 1.6, 2.4, 3.0, 3.2, 3.0, 2.4, 1.6, 0.8, 0.2, 0, 0, 0, 0, 0, 0]

CONFIG = {
    "house": {
        "grid": {"contracted_power_kw": 6.9, "import_tariff": "bi_daily", "export_tariff": "none"},
        "battery": {
            "name": "battery",
            "capacity_kwh": 10,
            "max_charge_kw": 5,
            "max_discharge_kw": 5,
            "soc_min": 10,
            "controller": {"type": "huawei", "command_penalty": 0.01, "max_commands": 4},
        },
        "ev": {
            "name": "car",
            "capacity_kwh": 40,
            "max_charge_kw": 3.7,
            "trip": {"leave": "08:30", "back": "18:00", "soc_on_return": 40},
            "soc_target": {"08:00": 80},
            "command_penalty": 0.001,
            "max_commands": 6,
        },
        "pv": {"name": "pv", "energy_kwh_by_hour": PV_KWH},
        "load": {"name": "house", "kw_by_hour": LOAD_KW},
    },
    "horizon": {"fine_minutes": 15, "fine_hours": 2, "coarse_minutes": 60, "total_hours": 8},
    "deadlines": {
        "battery": {"max_age_s": 600},
        "ev": {"max_age_s": 900},
        "meter": {"max_age_s": 300, "required": False},
    },
    "replan": {"period_minutes": 15, "event_debounce_s": 30, "retry_s": 60},
    "solver": {"time_limit": 20, "mip_rel_gap": 0.01},
}


def config(**overrides) -> RtoConfig:
    d = copy.deepcopy(CONFIG)
    d.update(overrides)
    return RtoConfig.from_dict(d)


def battery_msg(at, soc=50.0, mode="self_consumption"):
    return Observation.from_dict({"type": "battery", "time": at.isoformat(), "soc": soc, "mode": mode})


def ev_msg(at, plugged=True, soc=40.0):
    m = {"type": "ev", "time": at.isoformat(), "plugged": plugged}
    if plugged:
        m["soc"] = soc
    return Observation.from_dict(m)


def by_type(messages, kind):
    return [m for m in messages if m["type"] == kind]


# ---------------------------------------------------------------------- messages


def test_message_contract():
    obs = Observation.from_dict(
        {
            "type": "ev",
            "time": "2025-03-22T18:00:00Z",
            "plugged": True,
            "soc": 40,
            "expected_departure": "2025-03-23T08:30:00+00:00",
        }
    )
    assert (
        obs.signal == "ev" and obs.time == T0 and obs.data["expected_departure"] == T0 + timedelta(hours=14, minutes=30)
    )
    assert (
        Observation.from_dict(
            {"type": "forecast", "time": T0, "signal": "pv", "start": T0, "step_minutes": 15, "values_kwh": [0.1]}
        ).signal
        == "forecast.pv"
    )
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "inverter", "time": T0})
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "battery", "time": "2025-03-22 18:00", "soc": 50})  # no offset
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "ev", "time": T0})  # plugged missing
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "battery", "time": T0, "soc": 50, "mode": "tou"})
    # a control message needs no time: the receipt time is used
    assert Observation.from_dict({"type": "control", "action": "replan"}, received_at=T0).time == T0


# ---------------------------------------------------------------------- engine state machine


def test_engine_waits_for_required_signals_then_plans_and_commands():
    engine = Engine(config())
    assert engine.tick(T0) == [] and engine.health == Health.STARTING
    engine.observe(battery_msg(T0), T0)
    assert engine.tick(T0) == []  # the car is still missing
    engine.observe(ev_msg(T0), T0)
    out = engine.tick(T0 + timedelta(seconds=5))
    assert engine.health == Health.RUNNING
    assert engine.plan is not None and engine.plan.horizon.start == T0
    commands = by_type(out, "command")
    assert {c["device"] for c in commands} == {"battery", "car"}
    assert by_type(out, "plan") and by_type(out, "status")[-1]["health"] == "running"
    # ticking again inside the same period plans nothing new and repeats no command
    assert engine.tick(T0 + timedelta(seconds=10)) == []


def test_stale_required_signal_enters_fault_with_safe_commands_and_recovers():
    engine = Engine(config())
    engine.observe(battery_msg(T0), T0)
    engine.observe(ev_msg(T0), T0)
    engine.tick(T0)
    assert engine.health == Health.RUNNING

    later = T0 + timedelta(minutes=12)  # battery deadline is 10 min, the car's 15 min
    out = engine.tick(later)
    assert engine.health == Health.FAULT and "battery" in engine.reason
    safe = by_type(out, "command")
    assert {(c["device"], c["action"]) for c in safe} == {("battery", "set_mode"), ("car", "release")}
    assert [c for c in safe if c["device"] == "battery"][0]["mode"] == "self_consumption"
    assert by_type(out, "status")[-1]["stale"] == ["battery"]
    # while in fault nothing else is sent, however often we tick
    assert engine.tick(later + timedelta(seconds=30)) == []

    engine.observe(battery_msg(later + timedelta(minutes=1), soc=42.0), later + timedelta(minutes=1))
    out = engine.tick(later + timedelta(minutes=1, seconds=5))
    assert engine.health == Health.RUNNING
    assert by_type(out, "command"), "commands are re-sent after a fault"
    assert engine.plan is not None and engine.plan.results.column("battery", "soc")[0] == pytest.approx(42.0)


def test_replans_on_settlement_boundary_and_on_plug_events():
    engine = Engine(config())
    engine.observe(battery_msg(T0), T0)
    engine.observe(ev_msg(T0, plugged=True), T0)
    engine.tick(T0)
    first = engine.plan
    # inside the period: no replan
    engine.observe(battery_msg(T0 + timedelta(minutes=5)), T0 + timedelta(minutes=5))
    engine.tick(T0 + timedelta(minutes=5))
    assert engine.plan is first
    # the car leaves: an immediate event replan (the last plan is older than the 30 s debounce) without the car
    engine.observe(ev_msg(T0 + timedelta(minutes=6), plugged=False), T0 + timedelta(minutes=6))
    out = engine.tick(T0 + timedelta(minutes=6))
    assert engine.plan is not first and engine.plan.created_at == T0 + timedelta(minutes=6)
    assert all(c["device"] != "car" for c in by_type(out, "command"))
    # it comes back 10 s later: the replan is debounced until 30 s after the previous one
    second = engine.plan
    engine.observe(ev_msg(T0 + timedelta(minutes=6, seconds=10), plugged=True), T0 + timedelta(minutes=6, seconds=10))
    engine.tick(T0 + timedelta(minutes=6, seconds=10))
    assert engine.plan is second
    engine.tick(T0 + timedelta(minutes=6, seconds=31))
    assert engine.plan is not second
    # next settlement boundary: a plan again, even without events
    second = engine.plan
    engine.observe(battery_msg(T0 + timedelta(minutes=15)), T0 + timedelta(minutes=15))
    engine.observe(ev_msg(T0 + timedelta(minutes=15), plugged=True), T0 + timedelta(minutes=15))
    engine.tick(T0 + timedelta(minutes=15, seconds=2))
    assert engine.plan is not second and engine.plan.horizon.start == T0 + timedelta(minutes=15)


def test_pause_and_resume():
    engine = Engine(config())
    engine.observe(battery_msg(T0), T0)
    engine.observe(ev_msg(T0), T0)
    engine.tick(T0)
    out = engine.observe(Observation.from_dict({"type": "control", "action": "pause"}, received_at=T0), T0)
    assert engine.health == Health.PAUSED and by_type(out, "command")
    assert engine.tick(T0 + timedelta(minutes=15)) == []
    later = T0 + timedelta(minutes=16)
    engine.observe(battery_msg(later), later)
    engine.observe(ev_msg(later), later)
    engine.observe(Observation.from_dict({"type": "control", "action": "resume"}, received_at=later), later)
    out = engine.tick(later)
    assert engine.health == Health.RUNNING and by_type(out, "command")


def test_optional_signal_only_degrades():
    engine = Engine(config())
    engine.observe(battery_msg(T0), T0)
    engine.observe(ev_msg(T0), T0)
    engine.observe(
        Observation.from_dict({"type": "meter", "time": T0.isoformat(), "import_kw": 1.0, "export_kw": 0.0}), T0
    )
    out = engine.tick(T0)
    assert engine.health == Health.RUNNING
    assert "meter" not in by_type(out, "status")[-1]["never_received"]
    # the meter goes quiet past its 5-minute deadline: degraded, but still planning at the next boundary
    later = T0 + timedelta(minutes=15, seconds=1)
    engine.observe(battery_msg(later), later)
    engine.observe(ev_msg(later), later)
    out = engine.tick(later)
    assert engine.health == Health.DEGRADED and "meter" in engine.reason
    assert by_type(out, "plan")
    assert not any(c["action"] == "release" for c in by_type(out, "command"))


# ---------------------------------------------------------------------- planner


def test_planner_availability_follows_the_reported_state():
    planner = Planner(config(horizon={"fine_minutes": 15, "fine_hours": 2, "coarse_minutes": 60, "total_hours": 30}))
    now = datetime(2025, 3, 23, 7, 0, tzinfo=UTC)
    h = planner.horizon(now)
    from fennec.rto.state import Reading

    # plugged with an announced early departure at 07:30
    plugged, returns = planner.availability(
        h, Reading({"plugged": True, "expected_departure": now + timedelta(minutes=30)}, now, now)
    )
    assert plugged[:2] == [True, True] and not plugged[2]
    assert not plugged[h.step_at(datetime(2025, 3, 23, 12, 0, tzinfo=UTC))]  # still away at noon
    assert plugged[h.step_at(datetime(2025, 3, 23, 18, 0, tzinfo=UTC))]  # back at the scheduled time
    # away now at 07:00 (left early): back at the scheduled 18:00 unless told otherwise
    plugged, returns = planner.availability(h, Reading({"plugged": False}, now, now))
    assert not plugged[0] and not any(plugged[: h.step_at(datetime(2025, 3, 23, 17, 59, tzinfo=UTC)) + 1])
    assert returns == {h.step_at(datetime(2025, 3, 23, 18, 0, tzinfo=UTC)): 40.0}
    # away with an announced return at 09:00 and a different SOC
    back = datetime(2025, 3, 23, 9, 0, tzinfo=UTC)
    plugged, returns = planner.availability(
        h, Reading({"plugged": False, "expected_return": back, "soc_on_return": 55}, now, now)
    )
    assert plugged[h.step_at(back)] and returns == {h.step_at(back): 55.0}


# ---------------------------------------------------------------------- closed loop with the twin


def test_closed_loop_with_delayed_observations_keeps_running():
    cfg = config()
    engine = Engine(cfg)
    twin = Twin(
        start=T0,
        pv_kw=lambda ts: PV_KWH[ts.hour],
        load_kw=lambda ts: LOAD_KW[ts.hour],
        tariff=import_bi_daily_tariff,
        battery=TwinBattery(soc=35.0),
        vehicle=TwinVehicle(soc=40.0, plugged=True),
        delays={"battery": timedelta(seconds=40), "ev": timedelta(seconds=90)},
    )
    for msg in twin.snapshot():
        engine.observe(Observation.from_dict(msg, received_at=T0), T0)

    pending, applied, healths = [], [], []
    now, end = T0, T0 + timedelta(hours=4)
    started = time.perf_counter()
    while now < end:
        pending += twin.advance(now)
        due = [p for p in pending if p[0] <= now]
        pending = [p for p in pending if p[0] > now]
        for _, msg in sorted(due, key=lambda p: p[0]):
            engine.observe(Observation.from_dict(msg, received_at=now), now)
        for m in engine.tick(now):
            if m["type"] == "command":
                twin.apply(m)
                applied.append(m)
        healths.append(engine.health)
        now += timedelta(seconds=60)
    elapsed = time.perf_counter() - started

    assert engine.health == Health.RUNNING
    assert Health.FAULT not in healths
    assert sum(1 for r in engine.audit.records if r["kind"] == "plan") >= 15
    assert applied and {m["device"] for m in applied} == {"battery", "car"}
    assert twin.cost > 0
    assert elapsed < 120, f"closed loop too slow for the test suite: {elapsed:.0f}s"


# ---------------------------------------------------------------------- daemon


def test_daemon_round_trip_over_the_memory_transport():
    async def scenario():
        transport = MemoryTransport()
        engine = Engine(config())
        daemon = Daemon(engine, transport, tick_seconds=0.05, status_seconds=0.3)
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.run(stop))
        now = datetime.now(UTC)
        transport.push({"type": "battery", "time": now.isoformat(), "soc": 50, "mode": "self_consumption"})
        transport.push({"type": "ev", "time": now.isoformat(), "plugged": True, "soc": 40})
        transport.push({"type": "bogus"})
        await asyncio.sleep(4.0)
        stop.set()
        await task
        return transport.outbox

    outbox = asyncio.run(scenario())
    assert by_type(outbox, "error"), "a bad message is answered with an error, not a crash"
    assert by_type(outbox, "command")
    assert by_type(outbox, "status")[-1]["health"] in ("running", "degraded")


def test_more_invalid_messages_are_rejected():
    with pytest.raises(MessageError):
        Observation.from_dict(
            {"type": "forecast", "time": T0, "signal": "wind", "start": T0, "step_minutes": 15, "values_kwh": []}
        )
    with pytest.raises(MessageError):
        Observation.from_dict(
            {"type": "forecast", "time": T0, "signal": "pv", "start": "soon", "step_minutes": 15, "values_kwh": []}
        )
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "control", "time": T0, "action": "reboot"})
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "battery", "time": T0, "soc": "half"})
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "battery", "time": T0, "soc": 50, "pv_kw": "lots"})
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "ev", "time": T0, "plugged": True, "charging": "yes"})
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "ev", "time": T0, "plugged": True, "power_kw": "3"})
    with pytest.raises(MessageError):
        Observation.from_dict(["not", "an", "object"])
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "battery", "soc": 50})  # no time and no receipt time
    with pytest.raises(MessageError):
        Observation.from_dict({"type": "battery", "time": "2025-99-99T00:00:00+00:00", "soc": 50})
    obs = Observation.from_dict({"type": "meter", "time": T0, "power_kw": -0.5})
    assert obs.to_dict()["power_kw"] == -0.5
