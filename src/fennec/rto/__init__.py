"""
Real-time optimizer: a daemon that re-plans every settlement period from what an external connector reports.

The package never talks to equipment. It receives observations (battery, car, meter, forecasts) as JSON
messages, re-plans with the core optimizer on a rolling horizon, sends back device commands in the brand's
vocabulary, and enters a fault state (safe commands, no planning) whenever a required signal misses its
deadline.
"""

from .config import RtoConfig
from .engine import Audit, Engine, SAFE_COMMANDS
from .messages import MessageError, Observation
from .planner import Plan, Planner, PlanningError
from .state import Deadline, Health, HouseState
from .learning import History, Learner
from .daemon import Daemon, JsonLinesServer, MemoryTransport
from .twin import Twin, TwinBattery, TwinVehicle

__all__ = [
    "RtoConfig",
    "Audit",
    "Engine",
    "SAFE_COMMANDS",
    "MessageError",
    "Observation",
    "Plan",
    "Planner",
    "PlanningError",
    "Deadline",
    "Health",
    "HouseState",
    "History",
    "Learner",
    "Daemon",
    "JsonLinesServer",
    "MemoryTransport",
    "Twin",
    "TwinBattery",
    "TwinVehicle",
]
