"""Report tables and figures (pandas / matplotlib), the helpers the notebooks use."""

import pytest

from fennec import Battery, ElectricVehicle, HuaweiLuna2000Controller, IdealController, Load, SmartHome

from .conftest import solve

pd = pytest.importorskip("pandas")
matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from fennec.utils import compare, describe, energy_balance, plot_comparison, plot_dispatch, plot_profiles  # noqa: E402


@pytest.fixture
def houses(horizon, grid, profiles):
    plugged, returns = ElectricVehicle.daily_trip(horizon, "03:00", "08:00", 30.0)
    car = ElectricVehicle(
        "car",
        20.0,
        3.0,
        plugged=plugged,
        soc_initial=40.0,
        soc_on_return=returns,
        soc_target={horizon.first_steps_at("03:00")[0]: 80.0},
        max_commands=4,
    )
    huawei = Battery(
        "bat", 5.0, 2.5, 2.5, soc_initial=50.0, soc_min=10.0, controller=HuaweiLuna2000Controller(max_commands=4)
    )
    ideal = Battery("bat", 5.0, 2.5, 2.5, soc_initial=50.0, soc_min=10.0, controller=IdealController())
    return {
        "baseline": SmartHome(horizon, grid, profiles),
        "huawei + car": SmartHome(horizon, grid, profiles + [huawei, car]),
        "ideal": SmartHome(horizon, grid, profiles + [ideal]),
    }


@pytest.fixture
def results(houses):
    return {label: solve(home, mip_rel_gap=1e-3) for label, home in houses.items()}


def test_describe_lists_every_asset_with_its_parameters(houses):
    frame = describe(houses["huawei + car"])
    assert list(frame.index) == ["grid", "pv", "house", "bat", "car"]
    assert frame.loc["bat", "controller"].startswith("Huawei")
    assert frame.loc["grid", "contracted_power_kw"] == 6.9
    assert frame.loc["pv", "total_kwh"] > 0


def test_energy_balance_sums_what_each_asset_exchanged(results):
    frame = energy_balance(results["huawei + car"])
    assert set(frame.index) == {"grid", "pv", "house", "bat", "car"}
    assert frame.loc["pv", "to_house_kwh"] > 0 and frame.loc["pv", "from_house_kwh"] == 0
    assert frame.loc["car", "from_house_kwh"] > 0
    # the house balance closes: what comes in equals what goes out
    assert frame["to_house_kwh"].sum() == pytest.approx(frame["from_house_kwh"].sum(), abs=1e-3)


def test_compare_reports_bill_stored_value_objective_and_saving(results):
    frame = compare(results, reference="baseline")
    assert list(frame.index) == ["baseline", "huawei + car", "ideal"]
    assert frame.loc["baseline", "saving"] == 0.0 and frame.loc["baseline", "stored_value"] == 0.0
    assert frame.loc["ideal", "objective"] <= frame.loc["baseline", "objective"]
    assert frame.loc["ideal", "saving_pct"] >= 0
    assert "commands" in frame.columns and frame.loc["huawei + car", "commands"] >= 0
    assert "final_soc" in frame.columns
    # without a reference there is no saving column
    assert "saving" not in compare(results).columns


def test_figures_are_drawn_for_every_kind_of_asset(results):
    import matplotlib.pyplot as plt

    fig = plot_dispatch(results["huawei + car"], title="test")
    assert len(fig.axes) == 1 + 2 + 2 * 1 + 2 * 1 + 1  # prices, profiles, grid, battery x2, car x2, cost
    plt.close(fig)
    fig = plot_dispatch(results["baseline"], show_prices=False)
    assert len(fig.axes) == 3
    plt.close(fig)
    ax = plot_profiles(results["ideal"])
    assert ax.get_title(loc="left") == "PV production and load"
    plt.close(ax.figure)
    fig = plot_comparison(results, reference="baseline")
    assert len(fig.axes[0].patches) == 3
    plt.close(fig)
    fig = plot_comparison(results)
    plt.close(fig)


def test_compare_handles_a_scenario_without_solution(horizon, grid, pv_energy, results):
    hopeless = SmartHome(horizon, grid, [Load("heater", energy=[10.0] * horizon.steps)])
    failed = hopeless.solve(time_limit=10)
    frame = compare({**results, "hopeless": failed}, reference="baseline")
    assert frame.loc["hopeless", "status"] == "infeasible"
    assert frame.loc["hopeless", "objective"] is None or pd.isna(frame.loc["hopeless", "objective"])
