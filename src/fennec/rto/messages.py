"""
The contract between the daemon and the external connector: JSON objects, one per line.

Inbound (connector -> daemon). Every message has ``type`` and ``time`` (ISO 8601 with offset, the
instant the value was measured; the daemon also records when it received it):

    {"type": "battery", "time": "...", "soc": 47.3, "mode": "self_consumption",
     "setpoint_kw": 0.0, "power_kw": -1.2, "pv_kw": 0.0}
        setpoint_kw: the forced setpoint in force (signed, + charges); power_kw: measured battery power
        (signed, + charges); pv_kw: PV production measured by the inverter. All three optional; power_kw
        and pv_kw feed the learned forecasts.
    {"type": "ev", "time": "...", "plugged": true, "soc": 40.0, "charging": true, "power_kw": 3.7,
     "expected_departure": "...", "expected_return": "...", "soc_on_return": 40}     (all but plugged optional)
    {"type": "meter", "time": "...", "import_kw": 1.1, "export_kw": 0.0, "load_kw": 2.3}
        load_kw (optional): the house consumption when a meter measures it; otherwise the daemon derives it
        from the balance when PV, battery and car powers are reported.
    {"type": "forecast", "time": "...", "signal": "pv" | "load", "start": "...", "step_minutes": 15,
     "values_kwh": [...]}
    {"type": "control", "time": "...", "action": "replan" | "pause" | "resume"}

Outbound (daemon -> connector):

    {"type": "command", "time": "...", "device": "battery", "action": "set_mode", "mode": "self_consumption",
     "at": "...", "until": "...", "minutes": 45}
    {"type": "command", "time": "...", "device": "battery", "action": "force_charge", "power_kw": 3.0, ...}
    {"type": "command", "time": "...", "device": "car", "action": "charge", "on": true, ...}
    {"type": "command", "time": "...", "device": "car", "action": "release"}        (give control back)
    {"type": "status", "time": "...", "health": "running", "reason": null, "stale": [], ...}
    {"type": "plan", "time": "...", "summary": {...}, "commands": [...]}

Actions a connector must understand are listed per device in ``fennec.rto.engine.SAFE_COMMANDS`` and in the
``commands()`` methods of the controllers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

INBOUND_TYPES = {"battery", "ev", "meter", "forecast", "control"}


class MessageError(ValueError):
    """A message that does not follow the contract."""


def parse_time(value: Any, default: Optional[datetime] = None) -> datetime:
    if value is None:
        if default is None:
            raise MessageError("missing 'time'")
        return default
    if isinstance(value, datetime):
        instant = value
    else:
        try:
            instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as e:
            raise MessageError(f"bad time {value!r}: {e}") from e
    if instant.tzinfo is None:
        raise MessageError(f"time {value!r} must carry a timezone offset")
    return instant


@dataclass
class Observation:
    kind: str
    time: datetime  # measured at
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def signal(self) -> str:
        """Name under which the reading is stored: forecasts are split by signal."""
        if self.kind == "forecast":
            return f"forecast.{self.data.get('signal')}"
        return self.kind

    @classmethod
    def from_dict(cls, message: Dict[str, Any], received_at: Optional[datetime] = None) -> "Observation":
        if not isinstance(message, dict):
            raise MessageError("message must be a JSON object")
        kind = message.get("type")
        if kind not in INBOUND_TYPES:
            raise MessageError(f"unknown message type {kind!r}; expected one of {sorted(INBOUND_TYPES)}")
        time = parse_time(message.get("time"), default=received_at)
        data = {k: v for k, v in message.items() if k not in ("type", "time")}
        _validate(kind, data)
        return cls(kind=kind, time=time, data=data)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.kind, "time": self.time.isoformat(), **self.data}


def _validate(kind: str, data: Dict[str, Any]) -> None:
    def need(key, types):
        if key not in data:
            raise MessageError(f"{kind}: missing '{key}'")
        if not isinstance(data[key], types) or isinstance(data[key], bool) and types is not bool:
            raise MessageError(f"{kind}: '{key}' has the wrong type")

    if kind == "battery":
        need("soc", (int, float))
        if "mode" in data and data["mode"] not in ("self_consumption", "forced"):
            raise MessageError("battery: 'mode' must be 'self_consumption' or 'forced'")
        for key in ("setpoint_kw", "power_kw", "pv_kw"):
            if key in data and not isinstance(data[key], (int, float)):
                raise MessageError(f"battery: '{key}' must be a number")
    elif kind == "ev":
        need("plugged", bool)
        if "charging" in data and not isinstance(data["charging"], bool):
            raise MessageError("ev: 'charging' must be true or false")
        if "power_kw" in data and not isinstance(data["power_kw"], (int, float)):
            raise MessageError("ev: 'power_kw' must be a number")
        for key in ("expected_departure", "expected_return"):
            if data.get(key) is not None:
                data[key] = parse_time(data[key])
    elif kind == "meter":
        if "power_kw" not in data and ("import_kw" not in data or "export_kw" not in data):
            raise MessageError("meter: give 'power_kw' or both 'import_kw' and 'export_kw'")
    elif kind == "forecast":
        if data.get("signal") not in ("pv", "load"):
            raise MessageError("forecast: 'signal' must be 'pv' or 'load'")
        need("values_kwh", list)
        need("step_minutes", (int, float))
        data["start"] = parse_time(data.get("start"))
    elif kind == "control":
        if data.get("action") not in ("replan", "pause", "resume"):
            raise MessageError("control: 'action' must be 'replan', 'pause' or 'resume'")


def outbound(kind: str, now: datetime, **payload: Any) -> Dict[str, Any]:
    return {"type": kind, "time": now.isoformat(), **payload}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
