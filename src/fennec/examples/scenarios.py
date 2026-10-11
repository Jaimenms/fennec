"""
Ready-made scenarios used by the notebooks, the tests and the command line.

All of them describe the same house in Porto over a day and a half at 15-minute resolution: a 5 kWp PV
array, a four-person household, a 6.9 kVA grid connection with the Portuguese bi-hourly tariff and no
export remuneration. Each function adds a different set of flexible assets.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from ..assets import Battery, ElectricVehicle, Grid, Load, PVProduction
from ..controllers import BatteryController, HuaweiLuna2000Controller
from ..horizon import Horizon
from ..model import SmartHome
from ..simulators import simulate_house_load_energy, simulate_pv_energy
from ..tariffs import export_none_tariff, import_bi_daily_tariff

PORTO = {"latitude": 41.2089, "longitude": -8.6143}


def default_horizon(start: Optional[datetime] = None, days: float = 1.5, step_minutes: int = 15) -> Horizon:
    start = start or datetime(2025, 3, 22, 0, 0, tzinfo=timezone.utc)
    return Horizon.days(start, days=days, delta_t=timedelta(minutes=step_minutes))


def porto_grid(contracted_power_kw: float = 6.9) -> Grid:
    return Grid(
        import_tariff=import_bi_daily_tariff,
        export_tariff=export_none_tariff,
        contracted_power_kw=contracted_power_kw,
    )


def porto_pv(horizon: Horizon, area_m2: float = 25.0, efficiency: float = 0.20, name: str = "pv") -> PVProduction:
    energy = simulate_pv_energy(horizon, area_m2, efficiency, tilt_deg=35, azimuth_deg=180, **PORTO)
    return PVProduction(name, energy=energy)


def porto_load(horizon: Horizon, house_area_m2: float = 100.0, residents: int = 4, name: str = "house") -> Load:
    energy = simulate_house_load_energy(horizon, house_area_m2, residents, PORTO["longitude"])
    return Load(name, energy=energy)


def porto_battery(
    horizon: Horizon,
    controller: Optional[BatteryController] = None,
    capacity_kwh: float = 10.0,
    power_kw: float = 5.0,
    soc_initial: float = 50.0,
    soc_final_min: Optional[float] = None,
    terminal_value: Union[float, str, None] = "min_import_price",
    name: str = "battery",
) -> Battery:
    """
    A LUNA2000-10 style battery. The energy left at the end of the horizon is valued at the cheapest
    import price (``terminal_value``), so the optimizer cannot look good by simply draining the battery
    and the inverter left alone is compared on the same footing.
    """
    return Battery(
        name,
        capacity_kwh=capacity_kwh,
        max_charge_kw=power_kw,
        max_discharge_kw=power_kw,
        soc_initial=soc_initial,
        soc_min=10.0,
        soc_max=100.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        controller=controller or HuaweiLuna2000Controller(max_commands=4, command_penalty=0.01),
        soc_final_min=soc_final_min,
        terminal_value=terminal_value,
    )


def porto_vehicle(
    horizon: Horizon,
    leave: str = "08:30",
    back: str = "18:00",
    soc_on_return: float = 40.0,
    soc_target: float = 80.0,
    target_at: str = "08:00",
    charger_kw: float = 3.7,
    name: str = "car",
) -> ElectricVehicle:
    """A 40 kWh EV that leaves every morning and must be at ``soc_target`` before leaving."""
    plugged, returns = ElectricVehicle.daily_trip(horizon, leave, back, soc_on_return)
    return ElectricVehicle(
        name,
        capacity_kwh=40.0,
        max_charge_kw=charger_kw,
        plugged=plugged,
        soc_initial=soc_on_return,
        soc_on_return=returns,
        soc_target={t: soc_target for t in horizon.first_steps_at(target_at)},
        target_penalty=0.5,
        max_commands=6,
        command_penalty=0.001,
    )


# ---------------------------------------------------------------------- scenarios


def baseline(horizon: Optional[Horizon] = None) -> SmartHome:
    """PV and load only: nothing to decide, the result is the reference cost."""
    horizon = horizon or default_horizon()
    return SmartHome(horizon, porto_grid(), [porto_pv(horizon), porto_load(horizon)])


def huawei_battery(
    horizon: Optional[Horizon] = None, controller: Optional[BatteryController] = None, **battery_kwargs
) -> SmartHome:
    """PV, load and a Huawei battery (default: optimized modes with at most 4 commands)."""
    horizon = horizon or default_horizon()
    battery = porto_battery(horizon, controller, **battery_kwargs)
    return SmartHome(horizon, porto_grid(), [porto_pv(horizon), porto_load(horizon), battery])


def electric_vehicle(horizon: Optional[Horizon] = None) -> SmartHome:
    """PV, load and an EV with a daily trip."""
    horizon = horizon or default_horizon()
    return SmartHome(horizon, porto_grid(), [porto_pv(horizon), porto_load(horizon), porto_vehicle(horizon)])


def battery_and_vehicle(
    horizon: Optional[Horizon] = None, controller: Optional[BatteryController] = None, **battery_kwargs
) -> SmartHome:
    """PV, load, Huawei battery and EV together."""
    horizon = horizon or default_horizon()
    battery = porto_battery(horizon, controller, **battery_kwargs)
    assets = [porto_pv(horizon), porto_load(horizon), battery, porto_vehicle(horizon)]
    return SmartHome(horizon, porto_grid(), assets)


SCENARIOS = {
    "baseline": baseline,
    "huawei_battery": huawei_battery,
    "electric_vehicle": electric_vehicle,
    "battery_and_vehicle": battery_and_vehicle,
}
