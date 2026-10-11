import math
from datetime import datetime, timedelta, timezone

import pytest

from fennec import Grid, Horizon, Load, PVProduction, Schedule, Tariff

N_STEPS = 48


@pytest.fixture
def horizon() -> Horizon:
    return Horizon(datetime(2025, 3, 22, 0, 0, tzinfo=timezone.utc), N_STEPS, timedelta(minutes=15))


@pytest.fixture
def pv_energy():
    """Half a day of PV with a bell shape, peak ~5.6 kW: enough to fill a small battery."""
    return [1.4 * math.exp(-(((i - N_STEPS / 2) / (N_STEPS / 4)) ** 2)) for i in range(N_STEPS)]


@pytest.fixture
def load_energy():
    return [0.9 if i < 10 or i > 38 else 0.3 for i in range(N_STEPS)]


@pytest.fixture
def import_tariff():
    return Tariff(
        "test-bi",
        prices={"peak": 0.19, "off": 0.11},
        schedules=[
            Schedule("00:00", "03:00", "off"),
            Schedule("03:00", "10:00", "peak"),
            Schedule("10:00", "24:00", "off"),
        ],
    )


@pytest.fixture
def grid(import_tariff) -> Grid:
    return Grid(import_tariff=import_tariff, export_tariff=Tariff.flat(0.05), contracted_power_kw=6.9)


@pytest.fixture
def profiles(pv_energy, load_energy):
    return [PVProduction("pv", energy=pv_energy), Load("house", energy=load_energy)]


def solve(home, **kw):
    """Solve and fail loudly unless HiGHS is missing."""
    try:
        import highspy  # noqa: F401
    except ImportError:  # pragma: no cover
        pytest.skip("highspy not installed")
    kw.setdefault("time_limit", 60)
    kw.setdefault("mip_rel_gap", 1e-6)
    results = home.solve(**kw)
    assert results.status == "optimal", results.status
    return results
