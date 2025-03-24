from .tariff import Tariff, Schedule, Price

import_bi_weekly_tariff = Tariff(
    name="import-bi-weekly",
    prices=[
        Price(name="P1", value=0.1921),
        Price(name="P2", value=0.1161)
    ],
    schedules=[
        Schedule(_from="00:00", _to="07:00", name="P2", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="07:00", _to="24:00", name="P1", weekdays=[0, 1, 2, 3, 4]),
        Schedule(_from="00:00", _to="09:00", name="P2", weekdays=[5]),
        Schedule(_from="09:00", _to="14:00", name="P1", weekdays=[5]),
        Schedule(_from="14:00", _to="20:00", name="P2", weekdays=[5]),
        Schedule(_from="20:00", _to="22:00", name="P1", weekdays=[5]),
        Schedule(_from="22:00", _to="24:00", name="P2", weekdays=[5]),
        Schedule(_from="00:00", _to="24:00", name="P2", weekdays=[6])
    ]
)
