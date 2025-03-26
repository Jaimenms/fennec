from .tariff import Tariff, Schedule, Price

import_tri_weekly_tariff = Tariff(
    name="import-bi-daily",
    prices=[Price(name="P1", value=0.3799), Price(name="P2", value=0.1766), Price(name="P3", value=0.13)],
    schedules=[
        Schedule(_from="00:00", _to="07:00", name="P3", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="07:00", _to="09:15", name="P2", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="09:15", _to="12:15", name="P1", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="12:15", _to="24:00", name="P2", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="19:30", _to="21:00", name="P1", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="21:00", _to="22:00", name="P2", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="22:00", _to="24:00", name="P3", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="00:00", _to="09:15", name="P3", weekdays=[5]),
        Schedule(_from="09:15", _to="14:00", name="P2", weekdays=[5]),
        Schedule(_from="14:00", _to="20:00", name="P1", weekdays=[5]),
        Schedule(_from="20:00", _to="22:00", name="P2", weekdays=[5]),
        Schedule(_from="22:00", _to="24:00", name="P3", weekdays=[5]),
        Schedule(_from="00:00", _to="24:00", name="P3", weekdays=[6]),
    ],
)
