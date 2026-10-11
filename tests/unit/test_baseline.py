import pytest

from fennec import Grid, PVProduction, SmartHome, Tariff

from .conftest import solve


def test_without_flexible_assets_the_cost_is_the_direct_computation(horizon, grid, profiles, pv_energy, load_energy):
    home = SmartHome(horizon, grid, profiles)
    results = solve(home)

    buy = grid.import_tariff.series(horizon)
    sell = grid.export_tariff.series(horizon)
    expected = sum(
        buy[t] * max(0.0, load_energy[t] - pv_energy[t]) - sell[t] * max(0.0, pv_energy[t] - load_energy[t])
        for t in horizon.index
    )
    assert results.objective == pytest.approx(expected, abs=1e-6)
    assert results.cost("grid") == pytest.approx(expected, abs=1e-6)
    assert results.summary()["grid_import_kwh"] == pytest.approx(
        sum(max(0.0, l - p) for l, p in zip(load_energy, pv_energy)), abs=1e-6
    )


def test_settling_binaries_are_only_added_when_export_can_beat_import(horizon, import_tariff, profiles):
    cheap_export = Grid(import_tariff=import_tariff, export_tariff=Tariff.flat(0.05))
    assert SmartHome(horizon, cheap_export, profiles).statistics()["binaries"] == 0

    rich_export = Grid(import_tariff=import_tariff, export_tariff=Tariff.flat(0.5))
    assert SmartHome(horizon, rich_export, profiles).statistics()["binaries"] == horizon.steps

    forced = Grid(import_tariff=import_tariff, export_tariff=Tariff.flat(0.05), settled=True)
    assert SmartHome(horizon, forced, profiles).statistics()["binaries"] == horizon.steps


def test_duplicate_or_invalid_asset_names_are_rejected(horizon, grid, profiles):
    with pytest.raises(ValueError):
        SmartHome(horizon, grid, profiles + [profiles[0]])
    from fennec import Load

    with pytest.raises(ValueError):
        SmartHome(horizon, grid, [Load("not valid", energy=[0.0] * horizon.steps)])
    with pytest.raises(ValueError):
        SmartHome(horizon, grid, [Load("short", energy=[0.0] * 3)])


def test_results_frame_is_time_indexed(horizon, grid, profiles):
    pytest.importorskip("pandas")
    results = solve(SmartHome(horizon, grid, profiles))
    frame = results.frame()
    assert len(frame) == horizon.steps
    assert "grid.energy_from" in frame.columns and "pv.energy" in frame.columns
    assert list(results.frame("grid").columns) == ["energy_from", "energy_to", "cost", "import_price", "export_price"]


def test_infeasible_problem_reports_status_without_crashing(horizon, grid, pv_energy):
    from fennec import Load

    too_much = Load("heater", energy=[10.0] * horizon.steps)  # above the contracted power at every step
    results = SmartHome(horizon, grid, [PVProduction("pv", energy=pv_energy), too_much]).solve(time_limit=10)
    assert results.status == "infeasible"
    assert not results.feasible
    assert results.summary()["objective"] is None
