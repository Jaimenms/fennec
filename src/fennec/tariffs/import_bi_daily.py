from .tariff import Tariff, Schedule, Price

import_bi_daily_tariff = Tariff(
    name="import-bi-daily",
    prices=[Price(name="P1", value=0.186337), Price(name="P2", value=0.112617)],
    schedules=[
        Schedule(_from="00:00", _to="08:00", name="P2"),
        Schedule(_from="08:00", _to="22:00", name="P1"),
        Schedule(_from="22:00", _to="00:00", name="P2"),
    ],
)
