from datetime import datetime, timedelta, timezone

import pytest

from fennec import Horizon
from fennec.simulators import house_load_kw, pv_power_kw, simulate_house_load_energy, simulate_pv_energy

PORTO = dict(latitude=41.2089, longitude=-8.6143)
UTC = timezone.utc


def test_pv_power_follows_the_sun():
    noon = datetime(2025, 6, 21, 12, 30, tzinfo=UTC)
    midnight = datetime(2025, 6, 21, 0, 30, tzinfo=UTC)
    south = pv_power_kw(noon, 10.0, 0.2, tilt_deg=35, azimuth_deg=180, **PORTO)
    assert 0.5 < south < 2.5  # 2 kWp of panels facing south at noon under clear sky
    assert pv_power_kw(midnight, 10.0, 0.2, **PORTO) == 0.0
    # a vertical panel facing north never sees the midday sun
    assert pv_power_kw(noon, 10.0, 0.2, tilt_deg=90, azimuth_deg=0, **PORTO) == 0.0
    # output scales with area and efficiency
    assert pv_power_kw(noon, 20.0, 0.2, **PORTO) == pytest.approx(2 * south)
    assert pv_power_kw(noon, 10.0, 0.1, **PORTO) == pytest.approx(south / 2)


def test_simulated_series_have_one_value_per_step_and_integrate_inside_the_step():
    day = Horizon.days(datetime(2025, 3, 22, tzinfo=UTC), days=1)
    pv = simulate_pv_energy(day, 25.0, 0.2, **PORTO)
    assert len(pv) == day.steps and min(pv) == 0.0 and max(pv) > 0.5
    assert sum(pv[:24]) == 0.0  # no sun between midnight and 06:00
    # the same day at hourly resolution produces (almost) the same daily energy
    hourly = Horizon.days(datetime(2025, 3, 22, tzinfo=UTC), days=1, delta_t=timedelta(hours=1))
    assert sum(simulate_pv_energy(hourly, 25.0, 0.2, **PORTO)) == pytest.approx(sum(pv), rel=0.02)


def test_house_load_has_morning_day_evening_and_night_levels():
    lon = PORTO["longitude"]
    base = 0.5 + 0.005 * 100
    # solar time ~ UTC - 0.57 h in Porto: 07:30 UTC is morning, 13:00 day, 20:00 evening, 02:00 night
    assert house_load_kw(datetime(2025, 3, 22, 7, 30, tzinfo=UTC), 100, 2, lon) == pytest.approx(base + 2 * 0.5)
    assert house_load_kw(datetime(2025, 3, 22, 13, 0, tzinfo=UTC), 100, 2, lon) == pytest.approx(base + 2 * 0.3)
    assert house_load_kw(datetime(2025, 3, 22, 20, 0, tzinfo=UTC), 100, 2, lon) == pytest.approx(base + 2 * 0.7)
    assert house_load_kw(datetime(2025, 3, 22, 2, 0, tzinfo=UTC), 100, 2, lon) == pytest.approx(base + 2 * 0.2)
    day = Horizon.days(datetime(2025, 3, 22, tzinfo=UTC), days=1)
    load = simulate_house_load_energy(day, 100, 2, lon)
    assert len(load) == day.steps and min(load) > 0
