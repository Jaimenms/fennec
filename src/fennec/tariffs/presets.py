"""Portuguese low-voltage tariff presets (values in EUR/kWh, times in Portugal mainland local time)."""

from datetime import timedelta, timezone

from .tariff import Schedule, Tariff

# Portugal mainland is UTC+0 in winter and UTC+1 in summer; the regulated schedules are published in
# legal time, so a fixed offset is a simplification. Winter time is used here.
PT_TZ = timezone(timedelta(hours=0))

WEEKDAYS = (0, 1, 2, 3, 4)
SATURDAY = (5,)
SUNDAY = (6,)

export_none_tariff = Tariff.none("export-none")

import_simple_tariff = Tariff(
    name="import-simple",
    prices={"P1": 0.1675},
    schedules=[Schedule("00:00", "24:00", "P1")],
    tz=PT_TZ,
)

import_bi_daily_tariff = Tariff(
    name="import-bi-daily",
    prices={"P1": 0.186337, "P2": 0.112617},
    schedules=[
        Schedule("00:00", "08:00", "P2"),
        Schedule("08:00", "22:00", "P1"),
        Schedule("22:00", "24:00", "P2"),
    ],
    tz=PT_TZ,
)

import_bi_weekly_tariff = Tariff(
    name="import-bi-weekly",
    prices={"P1": 0.1921, "P2": 0.1161},
    schedules=[
        Schedule("00:00", "07:00", "P2", WEEKDAYS),
        Schedule("07:00", "24:00", "P1", WEEKDAYS),
        Schedule("00:00", "09:00", "P2", SATURDAY),
        Schedule("09:00", "14:00", "P1", SATURDAY),
        Schedule("14:00", "20:00", "P2", SATURDAY),
        Schedule("20:00", "22:00", "P1", SATURDAY),
        Schedule("22:00", "24:00", "P2", SATURDAY),
        Schedule("00:00", "24:00", "P2", SUNDAY),
    ],
    tz=PT_TZ,
)

import_tri_daily_tariff = Tariff(
    name="import-tri-daily",
    prices={"P1": 0.3799, "P2": 0.1766, "P3": 0.13},
    schedules=[
        Schedule("00:00", "08:00", "P3"),
        Schedule("08:00", "10:30", "P2"),
        Schedule("10:30", "13:00", "P1"),
        Schedule("13:00", "19:30", "P2"),
        Schedule("19:30", "21:00", "P1"),
        Schedule("21:00", "22:00", "P2"),
        Schedule("22:00", "24:00", "P3"),
    ],
    tz=PT_TZ,
)

import_tri_weekly_tariff = Tariff(
    name="import-tri-weekly",
    prices={"P1": 0.3799, "P2": 0.1766, "P3": 0.13},
    schedules=[
        Schedule("00:00", "07:00", "P3", WEEKDAYS),
        Schedule("07:00", "09:15", "P2", WEEKDAYS),
        Schedule("09:15", "12:15", "P1", WEEKDAYS),
        Schedule("12:15", "19:30", "P2", WEEKDAYS),
        Schedule("19:30", "21:00", "P1", WEEKDAYS),
        Schedule("21:00", "22:00", "P2", WEEKDAYS),
        Schedule("22:00", "24:00", "P3", WEEKDAYS),
        Schedule("00:00", "09:15", "P3", SATURDAY),
        Schedule("09:15", "14:00", "P2", SATURDAY),
        Schedule("14:00", "20:00", "P1", SATURDAY),
        Schedule("20:00", "22:00", "P2", SATURDAY),
        Schedule("22:00", "24:00", "P3", SATURDAY),
        Schedule("00:00", "24:00", "P3", SUNDAY),
    ],
    tz=PT_TZ,
)

PRESETS = {
    "none": export_none_tariff,
    "simple": import_simple_tariff,
    "bi_daily": import_bi_daily_tariff,
    "bi_weekly": import_bi_weekly_tariff,
    "tri_daily": import_tri_daily_tariff,
    "tri_weekly": import_tri_weekly_tariff,
}
