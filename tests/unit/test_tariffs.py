from datetime import datetime, timedelta, timezone

import pytest

from fennec import Horizon, Schedule, Tariff
from fennec.tariffs import PRESETS, import_bi_daily_tariff, import_bi_weekly_tariff, export_none_tariff


def test_bi_daily_switches_at_eight_and_twenty_two():
    saturday = datetime(2025, 3, 22, tzinfo=timezone.utc)
    assert import_bi_daily_tariff(saturday.replace(hour=7, minute=59)) == pytest.approx(0.112617)
    assert import_bi_daily_tariff(saturday.replace(hour=8)) == pytest.approx(0.186337)
    assert import_bi_daily_tariff(saturday.replace(hour=21, minute=59)) == pytest.approx(0.186337)
    assert import_bi_daily_tariff(saturday.replace(hour=22)) == pytest.approx(0.112617)


def test_weekly_tariff_depends_on_weekday():
    sunday_noon = datetime(2025, 3, 23, 12, tzinfo=timezone.utc)
    monday_noon = datetime(2025, 3, 24, 12, tzinfo=timezone.utc)
    assert import_bi_weekly_tariff(sunday_noon) == pytest.approx(0.1161)
    assert import_bi_weekly_tariff(monday_noon) == pytest.approx(0.1921)


def test_none_and_flat_tariffs():
    instant = datetime(2025, 3, 22, 12, tzinfo=timezone.utc)
    assert export_none_tariff(instant) == 0.0
    assert Tariff.flat(0.2)(instant) == 0.2


def test_series_has_one_price_per_step():
    h = Horizon.days(datetime(2025, 3, 22, tzinfo=timezone.utc), days=1, delta_t=timedelta(hours=1))
    series = import_bi_daily_tariff.series(h)
    assert len(series) == 24
    assert series[:8] == [pytest.approx(0.112617)] * 8
    assert series[8:22] == [pytest.approx(0.186337)] * 14


def test_schedule_referencing_unknown_price_is_rejected():
    with pytest.raises(ValueError):
        Tariff("bad", prices={"P1": 0.1}, schedules=[Schedule("00:00", "24:00", "P9")])


def test_presets_cover_every_hour_of_the_week():
    h = Horizon.days(datetime(2025, 3, 17, tzinfo=timezone.utc), days=7, delta_t=timedelta(minutes=15))
    for name, tariff in PRESETS.items():
        series = tariff.series(h)
        assert len(series) == h.steps
        if name != "none":
            assert min(series) > 0, name
