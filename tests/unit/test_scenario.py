import json

import pytest

from fennec import Battery, ElectricVehicle, HuaweiLuna2000Controller
from fennec.cli import main
from fennec.scenario import results_to_dict, smart_home_from_dict

from .conftest import solve


def scenario_dict(pv_energy, load_energy):
    return {
        "horizon": {"start": "2025-03-22T00:00:00+00:00", "steps": len(pv_energy), "step_minutes": 15},
        "grid": {"contracted_power_kw": 6.9, "import_tariff": "bi_daily", "export_tariff": {"flat": 0.05}},
        "assets": [
            {"type": "pv", "name": "pv", "energy": pv_energy},
            {"type": "load", "name": "house", "energy": load_energy},
            {
                "type": "battery",
                "name": "bat",
                "capacity_kwh": 5,
                "max_charge_kw": 2.5,
                "max_discharge_kw": 2.5,
                "soc_initial": 50,
                "soc_min": 10,
                "controller": {"type": "huawei", "max_commands": 4, "command_penalty": 0.01},
            },
            {
                "type": "ev",
                "name": "car",
                "capacity_kwh": 20,
                "max_charge_kw": 4,
                "daily_trip": {"leave": "03:00", "back": "08:00", "soc_on_return": 30},
                "soc_target": {"03:00": 80},
                "soc_initial": 40,
            },
        ],
        "solver": {"time_limit": 30},
    }


def test_dict_round_trip_builds_the_expected_assets(pv_energy, load_energy):
    home = smart_home_from_dict(scenario_dict(pv_energy, load_energy))
    kinds = {a.name: a.kind for a in home.all_assets}
    assert kinds == {"grid": "grid", "pv": "pv", "house": "load", "bat": "battery", "car": "ev"}
    bat = next(a for a in home.assets if isinstance(a, Battery))
    assert isinstance(bat.controller, HuaweiLuna2000Controller) and bat.controller.max_commands == 4
    car = next(a for a in home.assets if isinstance(a, ElectricVehicle))
    assert car.soc_target == {12: 80.0} and car.soc_on_return == {32: 30.0}


def test_unknown_keys_are_reported(pv_energy, load_energy):
    d = scenario_dict(pv_energy, load_energy)
    d["grid"]["voltage"] = 230
    with pytest.raises(ValueError, match="unknown keys"):
        smart_home_from_dict(d)


def test_results_serialise_to_json(pv_energy, load_energy):
    home = smart_home_from_dict(scenario_dict(pv_energy, load_energy))
    results = solve(home, mip_rel_gap=1e-3)
    payload = json.loads(json.dumps(results_to_dict(results)))
    assert payload["status"] == "optimal"
    assert len(payload["timestamps"]) == len(pv_energy)
    assert set(payload["series"]) == {"grid", "pv", "house", "bat", "car"}


def test_cli_runs_a_json_scenario(tmp_path, pv_energy, load_energy, capsys):
    pytest.importorskip("highspy")
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario_dict(pv_energy, load_energy)))
    out = tmp_path / "results.json"
    code = main([str(path), "-o", str(out), "--gap", "0.01"])
    assert code == 0
    assert "grid_cost" in capsys.readouterr().out
    assert json.loads(out.read_text())["status"] in ("optimal", "time_limit")


def test_tariff_horizon_and_asset_parsing_variants(pv_energy, load_energy):
    from datetime import timedelta

    from fennec import IdealController, Tariff
    from fennec.scenario import asset_from_dict, horizon_from_dict, smart_home_from_dict, tariff_from_value

    assert tariff_from_value("bi_daily").name == "import-bi-daily"
    assert tariff_from_value(0.2)(horizon_from_dict({"start": "2025-03-22T00:00:00+00:00", "steps": 4}).start) == 0.2
    assert tariff_from_value({"flat": 0.3, "name": "x"}).name == "x"
    custom = tariff_from_value({"prices": {"p": 0.1}, "schedules": [{"start": "00:00", "end": "24:00", "price": "p"}]})
    assert custom.name == "custom"
    assert tariff_from_value(custom) is custom
    with pytest.raises(ValueError, match="preset"):
        tariff_from_value("quad_hourly")

    h = horizon_from_dict(
        {"start": "2025-03-22T00:00:00+00:00", "end": "2025-03-22T06:00:00+00:00", "step_minutes": 30}
    )
    assert h.steps == 12 and h.delta_t == timedelta(minutes=30)
    assert horizon_from_dict({"start": "2025-03-22T00:00:00+00:00", "days": 0.5}).steps == 48
    with pytest.raises(ValueError):
        horizon_from_dict({"start": "2025-03-22T00:00:00+00:00"})

    h = horizon_from_dict({"start": "2025-03-22T00:00:00+00:00", "steps": len(pv_energy)})
    load = asset_from_dict(
        {"type": "load", "name": "house", "simulate": {"area_m2": 80, "residents": 2, "longitude": -8.6}}, h
    )
    assert load.kind == "load" and len(load.energy) == h.steps
    ev = asset_from_dict(
        {
            "type": "ev",
            "name": "car",
            "capacity_kwh": 20,
            "max_charge_kw": 3,
            "plugged": [1] * 10 + [0] * 10 + [1] * (h.steps - 20),
            "soc_on_return": {20: 30},
        },
        h,
    )
    assert ev.plugged[10] is False and ev.soc_on_return == {20: 30.0}
    bat = asset_from_dict(
        {"type": "battery", "name": "b", "capacity_kwh": 5, "max_charge_kw": 2, "max_discharge_kw": 2}, h
    )
    assert isinstance(bat.controller, IdealController)
    with pytest.raises(ValueError, match="controller type"):
        asset_from_dict(
            {
                "type": "battery",
                "name": "b",
                "capacity_kwh": 5,
                "max_charge_kw": 2,
                "max_discharge_kw": 2,
                "controller": {"type": "tesla"},
            },
            h,
        )
    with pytest.raises(ValueError, match="asset type"):
        asset_from_dict({"type": "boiler", "name": "x"}, h)
    with pytest.raises(ValueError, match="unknown keys"):
        asset_from_dict({"type": "pv", "name": "pv", "energy": pv_energy, "tilt": 30}, h)
    with pytest.raises(ValueError, match="unknown keys"):
        smart_home_from_dict({"horizon": {"start": "2025-03-22T00:00:00+00:00", "steps": 4}, "weather": {}})


def test_cli_runs_a_built_in_example_and_saves_a_figure(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    pytest.importorskip("highspy")
    figure = tmp_path / "dispatch.png"
    code = main(["--example", "baseline", "--plot", str(figure), "--time-limit", "30"])
    assert code == 0 and figure.exists() and figure.stat().st_size > 1000
    assert "figure written" in capsys.readouterr().out
