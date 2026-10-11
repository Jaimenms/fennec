from datetime import datetime, timedelta, timezone

import pytest

from fennec import Horizon


def test_from_range_and_basic_properties():
    start = datetime(2025, 3, 22, tzinfo=timezone.utc)
    h = Horizon.from_range(start, start + timedelta(hours=36), timedelta(minutes=15))
    assert h.steps == 144
    assert h.hours == 0.25
    assert h.end == start + timedelta(hours=36)
    assert h.at(4) == start + timedelta(hours=1)
    assert h.energy(4.0) == 1.0
    assert len(h.timestamps) == 144


def test_requires_timezone_aware_start():
    with pytest.raises(ValueError):
        Horizon(datetime(2025, 3, 22), 10)


def test_within_handles_windows_that_wrap_midnight():
    h = Horizon.days(datetime(2025, 3, 22, tzinfo=timezone.utc), days=1, delta_t=timedelta(hours=1))
    day = h.within("08:00", "18:00")
    assert day[8] and day[17] and not day[18] and not day[7]
    night = h.within("22:00", "06:00")
    assert night[23] and night[0] and night[5] and not night[6] and not night[21]


def test_first_steps_at_returns_one_step_per_day():
    h = Horizon.days(datetime(2025, 3, 22, tzinfo=timezone.utc), days=2, delta_t=timedelta(minutes=15))
    steps = h.first_steps_at("08:00")
    assert steps == [32, 32 + 96]
    assert h.first_steps_at("07:50") == [32, 32 + 96]  # rounds up to the first step at or after


def test_days_helper_handles_fractional_days():
    h = Horizon.days(datetime(2025, 3, 22, tzinfo=timezone.utc), days=1.5)
    assert h.steps == 144


def test_validation_of_bad_horizons():
    start = datetime(2025, 3, 22, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        Horizon(start, steps=0)
    with pytest.raises(ValueError):
        Horizon(start, steps=4, delta_t=timedelta(0))
    with pytest.raises(ValueError):
        Horizon(start, durations=[])
    with pytest.raises(ValueError):
        Horizon(start, durations=[timedelta(minutes=15), timedelta(minutes=-5)])
    with pytest.raises(ValueError):
        Horizon.rolling(start, align="middle")
    h = Horizon(start, steps=4)
    assert h.step_at(start - timedelta(minutes=1)) is None and h.step_at(start + timedelta(hours=5)) is None
    assert h.steps_after(start + timedelta(minutes=16)) == [2, 3]
    assert "steps=4" in repr(h) and "durations" in repr(
        Horizon.segments(start, [(timedelta(minutes=15), 1), (timedelta(hours=1), 1)])
    )
    assert list(h) == h.timestamps and len(h) == 4 and h.unix[0] == start.timestamp()
