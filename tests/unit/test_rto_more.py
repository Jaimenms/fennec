"""Forecast delivery, the socket transport, the twin's command handling, planning failures and the config."""

import asyncio
import copy
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from fennec import Horizon
from fennec.rto import Daemon, Engine, Health, JsonLinesServer, Observation, Planner, PlanningError, RtoConfig, Twin
from fennec.rto.config import RtoConfig as Config
from fennec.rto.daemon import build_parser
from fennec.rto.forecast import fallback_load, fallback_pv, series_for
from fennec.rto.state import Reading
from fennec.rto.twin import TwinBattery, TwinVehicle
from fennec.tariffs import import_bi_daily_tariff

from .test_rto import CONFIG, LOAD_KW, PV_KWH, T0, battery_msg, by_type, ev_msg

UTC = timezone.utc


def config(**overrides) -> RtoConfig:
    d = copy.deepcopy(CONFIG)
    d.update(overrides)
    return RtoConfig.from_dict(d)


# ---------------------------------------------------------------------- forecasts from the connector


def test_connector_forecast_is_resampled_and_completed_with_the_fallback():
    h = Horizon.segments(T0, [(timedelta(minutes=15), 4), (timedelta(hours=1), 2)])  # 3 h
    fallback = lambda horizon: [9.0] * horizon.steps
    # one hour of 15-min values delivered: covers the four fine steps only
    reading = Reading({"signal": "pv", "start": T0, "step_minutes": 15, "values_kwh": [1, 2, 3, 4]}, T0, T0)
    series, source = series_for(h, reading, fallback)
    assert series == pytest.approx([1, 2, 3, 4, 9, 9]) and source == "connector+fallback"
    # a full delivery, in hourly values, split pro rata onto the fine steps
    reading = Reading({"signal": "pv", "start": T0, "step_minutes": 60, "values_kwh": [4.0, 8.0, 12.0]}, T0, T0)
    series, source = series_for(h, reading, fallback)
    assert series == pytest.approx([1, 1, 1, 1, 8, 12]) and source == "connector"
    assert series_for(h, None, fallback) == ([9.0] * 6, "fallback")


def test_fallback_profiles_from_the_simulators_and_validation():
    h = Horizon.days(datetime(2025, 3, 22, tzinfo=UTC), days=1)
    pv = fallback_pv(
        {"simulate": {"area_m2": 25, "efficiency": 0.2, "latitude": 41.2, "longitude": -8.6}, "factor": 0.5}
    )(h)
    assert len(pv) == h.steps and max(pv) > 0
    load = fallback_load({"simulate": {"area_m2": 100, "residents": 4, "longitude": -8.6}})(h)
    assert len(load) == h.steps and min(load) > 0
    with pytest.raises(ValueError):
        fallback_load({"kw_by_hour": [1.0] * 23})


def test_a_delivered_forecast_triggers_a_replan():
    engine = Engine(config())
    engine.observe(battery_msg(T0), T0)
    engine.observe(ev_msg(T0), T0)
    engine.tick(T0)
    first = engine.plan
    later = T0 + timedelta(minutes=2)
    engine.observe(
        Observation.from_dict(
            {
                "type": "forecast",
                "time": later.isoformat(),
                "signal": "load",
                "start": T0.isoformat(),
                "step_minutes": 15,
                "values_kwh": [0.1] * 40,
            }
        ),
        later,
    )
    engine.tick(later)
    assert engine.plan is not first and engine.plan.notes["load_source"] == "connector"  # 10 h cover the 8 h horizon
    assert engine.plan.results.column("house", "energy")[0] == pytest.approx(0.1)
    engine.observe(Observation.from_dict({"type": "control", "action": "replan"}, received_at=later), later)
    assert engine.replan_requested is not None


# ---------------------------------------------------------------------- planning failures


class FailingPlanner(Planner):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.fail = True

    def plan(self, now, state, budgets=None):
        if self.fail:
            raise PlanningError("boom")
        return super().plan(now, state, budgets)


def test_plan_failure_degrades_sends_safe_commands_and_retries():
    cfg = config(replan={"period_minutes": 15, "event_debounce_s": 30, "retry_s": 60})
    planner = FailingPlanner(cfg)
    engine = Engine(cfg, planner=planner)
    engine.observe(battery_msg(T0), T0)
    engine.observe(ev_msg(T0), T0)
    out = engine.tick(T0)
    assert engine.health == Health.DEGRADED and "boom" in engine.reason
    assert {c["action"] for c in by_type(out, "command")} == {"set_mode", "release"}
    assert engine.failures == 1
    # a second failure does not repeat the safe commands
    out = engine.tick(T0 + timedelta(seconds=61))
    assert engine.failures == 2 and not by_type(out, "command")
    # once planning works again the loop is back to running with real commands
    planner.fail = False
    out = engine.tick(T0 + timedelta(seconds=122))
    assert engine.health == Health.RUNNING and engine.failures == 0
    assert by_type(out, "command")


# ---------------------------------------------------------------------- the socket transport


def test_json_lines_server_over_tcp_and_unix(tmp_path):
    async def exercise(server: JsonLinesServer, open_connection):
        await server.start()
        engine = Engine(config())
        daemon = Daemon(engine, server, tick_seconds=0.05, status_seconds=0.2)
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.run(stop))
        reader, writer = await open_connection(server)
        now = datetime.now(UTC).isoformat()
        writer.write(b"this is not json\n")
        for msg in (
            {"type": "battery", "time": now, "soc": 50, "mode": "self_consumption"},
            {"type": "ev", "time": now, "plugged": True, "soc": 40},
            {"type": "meter", "time": now},  # invalid: answered with an error
        ):
            writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()
        seen = []
        try:
            while (
                len([m for m in seen if m["type"] == "command"]) < 2
                or len([m for m in seen if m["type"] == "error"]) < 2
            ):
                line = await asyncio.wait_for(reader.readline(), timeout=20)
                if not line:
                    break
                seen.append(json.loads(line))
        finally:
            writer.close()
            stop.set()
            await task
            await server.close()
        return seen

    async def tcp():
        server = JsonLinesServer(host="127.0.0.1", port=0)

        async def connect(s):
            port = s.server.sockets[0].getsockname()[1]
            return await asyncio.open_connection("127.0.0.1", port)

        return await exercise(server, connect)

    async def unix():
        # a Unix socket path must be short (104 bytes on macOS): the pytest tmp_path is too long for it
        path = str(Path(tempfile.mkdtemp(prefix="fennec-")) / "rto.sock")
        server = JsonLinesServer(unix_path=path)
        try:
            return await exercise(server, lambda s: asyncio.open_unix_connection(path))
        finally:
            shutil.rmtree(Path(path).parent, ignore_errors=True)

    for seen in (asyncio.run(tcp()), asyncio.run(unix())):
        errors = [m for m in seen if m["type"] == "error"]
        assert any("bad JSON" in e["error"] for e in errors)
        assert any("meter" in e["error"] for e in errors)
        assert {m["device"] for m in seen if m["type"] == "command"} == {"battery", "car"}
        assert any(m["type"] == "status" for m in seen)


def test_command_line_parser():
    args = build_parser().parse_args(["cfg.json", "--unix", "/tmp/x.sock", "--tick", "2"])
    assert args.config == "cfg.json" and args.unix == "/tmp/x.sock" and args.tick == 2.0
    assert build_parser().parse_args(["cfg.json"]).tcp == "127.0.0.1:7777"


# ---------------------------------------------------------------------- the twin


def test_twin_applies_every_command_and_moves_the_car():
    twin = Twin(
        start=datetime(2025, 3, 22, 8, 0, tzinfo=UTC),
        pv_kw=lambda ts: 2.0,
        load_kw=lambda ts: 1.0,
        tariff=import_bi_daily_tariff,
        battery=TwinBattery(soc=50.0),
        vehicle=TwinVehicle(soc=60.0, plugged=True, leave="08:30", back="09:30", soc_on_return=20.0),
        report_every=timedelta(minutes=15),
    )
    now = twin.now

    def cmd(device, action, **params):
        return {"type": "command", "device": device, "action": action, **params}

    twin.apply(cmd("battery", "force_discharge", power_kw=2.0, minutes=30))
    assert twin.battery.mode == "forced" and twin.battery.forced_kw == -2.0
    twin.apply(cmd("car", "charge", on=False))
    assert not twin.vehicle.charger_on and not twin.vehicle.released
    pending = twin.advance(now + timedelta(minutes=15))
    assert twin.battery.soc < 50.0  # discharged although PV exceeds the load
    kinds = [m["type"] for _, m in pending]
    assert kinds.count("meter") == 1 and "battery" in kinds and "ev" in kinds

    twin.apply(cmd("battery", "hold", minutes=15))
    twin.advance(now + timedelta(minutes=30))
    assert twin.battery.forced_kw == 0.0
    twin.apply(cmd("battery", "set_power", power_kw=1.0, minutes=15))
    twin.apply(cmd("battery", "set_mode", mode="self_consumption"))
    assert twin.battery.mode == "self_consumption"
    twin.apply(cmd("car", "release"))
    assert twin.vehicle.released and twin.vehicle.charger_on

    # the car leaves at 08:30 and is back at 09:30 with 20 %
    twin.advance(now + timedelta(minutes=45))
    assert not twin.vehicle.plugged
    assert all("soc" not in m for _, m in twin.advance(now + timedelta(hours=1)) if m["type"] == "ev")
    twin.advance(now + timedelta(hours=1, minutes=45))
    assert twin.vehicle.plugged and twin.vehicle.soc > 20.0  # charging again since the return
    assert twin.cost == 0.0  # PV always exceeds the load here: the house only exports, which earns nothing
    assert len(twin.log) == 6  # six commands applied, the status message is ignored
    twin.apply({"type": "status"})  # ignored


# ---------------------------------------------------------------------- configuration


def test_config_validation_and_defaults(tmp_path):
    cfg = config()
    assert (
        cfg.period == timedelta(minutes=15) and cfg.fine == timedelta(minutes=15) and cfg.coarse == timedelta(hours=1)
    )
    assert cfg.has_battery and cfg.has_ev and cfg.device_names() == {"battery": "battery", "ev": "car"}
    assert "forecast.pv" in cfg.deadlines and not cfg.deadlines["forecast.pv"].required

    d = copy.deepcopy(CONFIG)
    d["house"].pop("ev")
    only_battery = Config.from_dict(d)
    assert "ev" not in only_battery.deadlines and only_battery.device_names() == {"battery": "battery"}

    with pytest.raises(ValueError, match="unknown keys"):
        Config.from_dict({**copy.deepcopy(CONFIG), "typo": 1})
    with pytest.raises(ValueError, match="grid"):
        Config.from_dict({"house": {"pv": {}, "load": {}}})
    with pytest.raises(ValueError, match="fallback"):
        Config.from_dict({"house": {"grid": {}}})
    with pytest.raises(ValueError, match="device kind"):
        config(limits={"heater": {"commands_per_day": 1}})
    with pytest.raises(ValueError, match="non-negative"):
        config(limits={"battery": {"commands_per_day": -1}})

    path = tmp_path / "rto.json"
    path.write_text(json.dumps(CONFIG))
    assert Config.load(path).solver["time_limit"] == 20
