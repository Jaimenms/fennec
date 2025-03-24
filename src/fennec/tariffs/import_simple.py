from .tariff import Tariff, Schedule, Price

import_simple_tariff = Tariff(
    name="import-simple",
    prices=[
        Price(name="P1", value=0.1675)
    ],
    schedules=[
        Schedule(
            _from="00:00",
            _to="24:00",
            name="P1"
        )
    ]
)



