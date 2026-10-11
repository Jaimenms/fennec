from datetime import datetime, timedelta, timezone

import pytest

from fennec import (
    Battery,
    ElectricVehicle,
    Grid,
    Horizon,
    HuaweiLuna2000Controller,
    Load,
    PVProduction,
    SmartHome,
    Tariff,
)
from fennec.tariffs import import_bi_daily_tariff

from .conftest import solve

UTC = timezone.utc


def test_rolling_horizon_is_aligned_fine_then_coarse():
    now = datetime(2025, 3, 22, 18, 3, 27, tzinfo=UTC)
    h = Horizon.rolling(now, fine=timedelta(minutes=15), fine_hours=6, coarse=timedelta(hours=1), total_hours=36)
    assert h.start == datetime(2025, 3, 22, 18, 15, tzinfo=UTC)
    fine = [d for d in h.durations if d == timedelta(minutes=15)]
    coarse = [d for d in h.durations if d == timedelta(hours=1)]
    assert len(fine) + len(coarse) == h.steps
    # fine steps run past 6 h up to the next full hour (01:00), then hourly until 06:15 + ... = 36 h
    assert h.at(len(fine)) == datetime(2025, 3, 23, 1, 0, tzinfo=UTC)
    assert h.start + timedelta(hours=36) <= h.end < h.start + timedelta(hours=37)
    assert not h.uniform
    with pytest.raises(ValueError):
        _ = h.delta_t
    assert h.hours_at(0) == 0.25 and h.hours_at(h.steps - 1) == 1.0
    assert h.step_at(datetime(2025, 3, 23, 3, 30, tzinfo=UTC)) == len(fine) + 2
    assert h.step_at(now) is None


def test_segments_resample_and_integrate():
    start = datetime(2025, 3, 22, tzinfo=UTC)
    h = Horizon.segments(start, [(timedelta(minutes=15), 4), (timedelta(hours=1), 2)])
    assert h.steps == 6 and h.end == start + timedelta(hours=3)
    # a 15-min series of 1 kWh per step covering 2 h: the hourly step collects four of them, the last is uncovered
    series = h.resample(start, timedelta(minutes=15), [1.0] * 8, fill=0.0)
    assert series == pytest.approx([1, 1, 1, 1, 4, 0])
    # a constant 2 kW integrates to 0.5 kWh per quarter and 2 kWh per hour
    assert h.integrate(lambda ts: 2.0) == pytest.approx([0.5, 0.5, 0.5, 0.5, 2.0, 2.0])
    assert h.energies([2.0] * 6) == pytest.approx([0.5, 0.5, 0.5, 0.5, 2.0, 2.0])


def test_tariff_is_averaged_inside_coarse_steps():
    # an hourly step from 07:30 to 08:30 straddles the 08:00 change of the bi-hourly tariff
    h = Horizon(datetime(2025, 3, 22, 7, 30, tzinfo=UTC), durations=[timedelta(hours=1)])
    price = import_bi_daily_tariff.series(h)[0]
    assert price == pytest.approx((0.112617 + 0.186337) / 2)


def test_solve_on_a_rolling_horizon_with_battery_and_car(grid):
    now = datetime(2025, 3, 22, 18, 3, tzinfo=UTC)
    h = Horizon.rolling(now, fine_hours=6, total_hours=36)
    pv = [0.0] * h.steps
    load = h.energies([1.2] * h.steps)
    plugged, returns = ElectricVehicle.daily_trip(h, "08:30", "18:00", 40.0)
    car = ElectricVehicle(
        "car",
        40.0,
        3.7,
        plugged=plugged,
        soc_initial=40.0,
        soc_on_return=returns,
        soc_target={t: 80.0 for t in h.first_steps_at("08:00")},
        max_commands=6,
    )
    bat = Battery(
        "bat",
        10.0,
        5.0,
        5.0,
        soc_initial=30.0,
        soc_min=10.0,
        controller=HuaweiLuna2000Controller(max_commands=4, command_penalty=0.01, initial_mode="self_consumption"),
    )
    home = SmartHome(
        h,
        Grid(import_tariff=import_bi_daily_tariff, export_tariff=Tariff.none()),
        [PVProduction("pv", energy=pv), Load("house", energy=load), bat, car],
    )
    results = solve(home, mip_rel_gap=1e-3)
    assert home.statistics()["binaries"] < 600  # ~1250 on a uniform 15-min horizon of the same length
    # per-step limits follow the step length: an hourly step can charge four times a quarter-hour one
    to = results.column("bat", "energy_to")
    assert max(to) <= 5.0 + 1e-6
    # commands come out in the device vocabulary, in time order, covering the horizon without gaps
    cmds = bat.controller.commands(results, bat)
    assert cmds[0].at == h.start and cmds[-1].until == h.end
    assert all(a.until == b.at for a, b in zip(cmds, cmds[1:]))
    assert {c.action for c in cmds} <= {"set_mode", "force_charge", "force_discharge", "hold"}
    car_cmds = car.commands(results)
    assert all(c.action == "charge" and "on" in c.params for c in car_cmds)
    assert all(plugged[h.step_at(c.at)] for c in car_cmds)
