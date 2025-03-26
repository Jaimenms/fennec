from .tariff import Tariff, Schedule, Price

import_tri_daily_tariff = Tariff(
    name="import-bi-daily",
    prices=[Price(name="P1", value=0.3799), Price(name="P2", value=0.1766), Price(name="P3", value=0.13)],
    schedules=[
        Schedule(_from="00:00", _to="08:00", name="P3"),
        Schedule(_from="08:00", _to="10:30", name="P2"),
        Schedule(_from="10:30", _to="13:00", name="P1"),
        Schedule(_from="13:00", _to="19:30", name="P2"),
        Schedule(_from="19:30", _to="21:00", name="P1"),
        Schedule(_from="21:00", _to="22:00", name="P2"),
        Schedule(_from="22:00", _to="24:00", name="P3"),
    ],
)
