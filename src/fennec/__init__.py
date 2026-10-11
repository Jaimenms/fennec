"""
Fennec: cost optimization of the flexible assets of a house (batteries, EVs, ...) behind one grid meter.

Quick start::

    from datetime import datetime, timezone
    from fennec import Horizon, SmartHome, Grid, PVProduction, Load, Battery, HuaweiLuna2000Controller
    from fennec.tariffs import import_bi_daily_tariff

    horizon = Horizon.days(datetime(2025, 3, 22, tzinfo=timezone.utc), days=1.5)
    home = SmartHome(
        horizon,
        grid=Grid(import_tariff=import_bi_daily_tariff, contracted_power_kw=6.9),
        assets=[
            PVProduction("pv", energy=pv_kwh_per_step),
            Load("house", energy=load_kwh_per_step),
            Battery("battery", 10.0, 5.0, 5.0, controller=HuaweiLuna2000Controller(max_commands=4)),
        ],
    )
    results = home.solve(time_limit=60)
    print(results.summary())
"""

from .horizon import Horizon
from .commands import Command
from .model import SmartHome
from .results import Results
from .assets import Asset, Grid, Load, PVProduction, FixedProfile, Battery, ElectricVehicle
from .controllers import BatteryController, IdealController, HuaweiLuna2000Controller
from .tariffs import Tariff, Schedule

__version__ = "0.2.0"

__all__ = [
    "Horizon",
    "Command",
    "SmartHome",
    "Results",
    "Asset",
    "Grid",
    "Load",
    "PVProduction",
    "FixedProfile",
    "Battery",
    "ElectricVehicle",
    "BatteryController",
    "IdealController",
    "HuaweiLuna2000Controller",
    "Tariff",
    "Schedule",
]
