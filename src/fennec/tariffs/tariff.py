from typing import List, Optional
from datetime import datetime
from dataclasses import dataclass


@dataclass
class Schedule:
    _from: str
    _to: str
    name: str
    weekdays: List[int] = None


@dataclass
class Price:
    name: str
    value: float


class Tariff:
    def __init__(self, name: str, schedules: Optional[List[Schedule]] = None, prices: Optional[List[Price]] = None):
        self.name = name
        self.schedules = schedules if schedules is not None else []
        self.tariff_values = prices if prices is not None else []

    def get_price_name(self, t: datetime):
        weekday = t.weekday()
        for schedule in self.schedules:
            if schedule.weekdays is None or weekday in schedule.weekdays:
                if schedule._from <= t.strftime("%H:%M") < schedule._to:
                    return schedule.name

    def get_price(self, name):
        for tariff_value in self.tariff_values:
            if tariff_value.name == name:
                return tariff_value.value
        return 0.0

    def __call__(self, t: datetime):
        price_name = self.get_price_name(t)
        return self.get_price(price_name)

