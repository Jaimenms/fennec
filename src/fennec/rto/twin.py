"""
Digital twin: a simulated house that plays the role of the external connector.

It applies the daemon's commands to a simple plant model (the inverter's self-consumption rule, forced
charge / discharge, an on/off charger, a car that leaves and comes back) and produces the observations the
real connector would send, optionally delivered late. Used to test the closed loop without any hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..tariffs import Tariff


@dataclass
class TwinBattery:
    capacity_kwh: float = 10.0
    max_charge_kw: float = 5.0
    max_discharge_kw: float = 5.0
    soc: float = 50.0
    soc_min: float = 10.0
    soc_max: float = 100.0
    efficiency: float = 0.95
    mode: str = "self_consumption"  # or "forced"
    forced_kw: float = 0.0  # signed: positive charges
    forced_until: Optional[datetime] = None


@dataclass
class TwinVehicle:
    capacity_kwh: float = 40.0
    charger_kw: float = 3.7
    leave: str = "08:30"
    back: str = "18:00"
    soc_on_return: float = 40.0
    soc: float = 40.0
    plugged: bool = True
    charger_on: bool = True  # the charger's own default: charge whenever plugged
    released: bool = True  # True: the charger follows its default, False: it follows the daemon
    efficiency: float = 0.95


@dataclass
class Twin:
    start: datetime
    pv_kw: Callable[[datetime], float]
    load_kw: Callable[[datetime], float]
    tariff: Tariff
    battery: Optional[TwinBattery] = None
    vehicle: Optional[TwinVehicle] = None
    step: timedelta = timedelta(minutes=15)
    report_every: timedelta = timedelta(minutes=5)  # how often the "connector" reports battery and car
    delays: Dict[str, timedelta] = field(default_factory=dict)  # kind -> delivery delay
    names: Dict[str, str] = field(default_factory=lambda: {"battery": "battery", "ev": "car"})
    now: datetime = field(init=False)
    cost: float = field(init=False, default=0.0)
    log: List[Dict[str, Any]] = field(init=False, default_factory=list)

    def __post_init__(self):
        self.now = self.start
        self._next_report = self.start + self.report_every

    # ------------------------------------------------------------------ commands from the daemon

    def apply(self, message: Dict[str, Any]) -> None:
        if message.get("type") != "command":
            return
        device, action = message["device"], message["action"]
        if self.battery is not None and device == self.names["battery"]:
            b = self.battery
            if action == "set_mode":
                b.mode, b.forced_kw, b.forced_until = "self_consumption", 0.0, None
            elif action in ("force_charge", "force_discharge", "hold"):
                power = float(message.get("power_kw", 0.0))
                b.mode = "forced"
                b.forced_kw = power if action == "force_charge" else -power if action == "force_discharge" else 0.0
                b.forced_until = self.now + timedelta(minutes=float(message.get("minutes", 15)))
            elif action == "set_power":
                b.mode, b.forced_kw = "forced", float(message["power_kw"])
                b.forced_until = self.now + timedelta(minutes=float(message.get("minutes", 15)))
        if self.vehicle is not None and device == self.names["ev"]:
            v = self.vehicle
            if action == "charge":
                v.released = False
                v.charger_on = (
                    bool(message.get("on", True)) if "on" in message else float(message.get("power_kw", 0)) > 0
                )
            elif action == "release":
                v.released, v.charger_on = True, True
        self.log.append({"time": self.now.isoformat(), "applied": message})

    # ------------------------------------------------------------------ physics

    def _trip_events(self, t0: datetime, t1: datetime) -> None:
        """Depart / return when the clock crosses the trip times inside [t0, t1)."""
        v = self.vehicle
        if v is None:
            return
        for hhmm, plugged_after in ((v.leave, False), (v.back, True)):
            hh, mm = (int(x) for x in hhmm.split(":"))
            when = t0.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if t0 <= when < t1 and v.plugged != plugged_after:
                v.plugged = plugged_after
                if plugged_after:
                    v.soc = v.soc_on_return
                if v.released:
                    v.charger_on = True

    def _step(self) -> List[Tuple[datetime, Dict[str, Any]]]:
        t0, t1 = self.now, self.now + self.step
        hours = self.step.total_seconds() / 3600.0
        self._trip_events(t0, t1)
        pv = self.pv_kw(t0) * hours
        load = self.load_kw(t0) * hours

        car = 0.0
        v = self.vehicle
        if v is not None and v.plugged and v.charger_on:
            room = (100.0 - v.soc) / 100.0 * v.capacity_kwh / v.efficiency
            car = min(v.charger_kw * hours, max(0.0, room))
            v.soc += 100.0 / v.capacity_kwh * v.efficiency * car

        bat_to = bat_from = 0.0
        b = self.battery
        if b is not None:
            if b.mode == "forced" and b.forced_until is not None and t0 >= b.forced_until:
                b.mode, b.forced_kw = "self_consumption", 0.0  # a timed command expired
            room = (b.soc_max - b.soc) / 100.0 * b.capacity_kwh / b.efficiency
            avail = (b.soc - b.soc_min) / 100.0 * b.capacity_kwh * b.efficiency
            net = load + car - pv  # what the house needs from battery + grid (negative: surplus)
            if b.mode == "self_consumption":
                if net < 0:
                    bat_to = min(-net, b.max_charge_kw * hours, room)
                else:
                    bat_from = min(net, b.max_discharge_kw * hours, avail)
            else:
                if b.forced_kw > 0:
                    bat_to = min(b.forced_kw * hours, b.max_charge_kw * hours, room)
                elif b.forced_kw < 0:
                    bat_from = min(-b.forced_kw * hours, b.max_discharge_kw * hours, avail)
            b.soc += 100.0 / b.capacity_kwh * (b.efficiency * bat_to - bat_from / b.efficiency)

        grid = load + car - pv + bat_to - bat_from
        imported, exported = max(0.0, grid), max(0.0, -grid)
        self.cost += imported * self.tariff(t0)
        self.now = t1

        out: List[Tuple[datetime, Dict[str, Any]]] = [
            (
                t1 + self.delays.get("meter", timedelta(0)),
                {
                    "type": "meter",
                    "time": t1.isoformat(),
                    "import_kw": round(imported / hours, 3),
                    "export_kw": round(exported / hours, 3),
                },
            )
        ]
        return out

    def snapshot(self, at: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """The current state as observations (what a connector sends on start-up and at every report)."""
        stamp = (at or self.now).isoformat()
        out: List[Dict[str, Any]] = []
        if self.battery is not None:
            b = self.battery
            out.append(
                {
                    "type": "battery",
                    "time": stamp,
                    "soc": round(b.soc, 2),
                    "mode": b.mode,
                    "setpoint_kw": b.forced_kw if b.mode == "forced" else 0.0,
                }
            )
        if self.vehicle is not None:
            v = self.vehicle
            msg: Dict[str, Any] = {"type": "ev", "time": stamp, "plugged": v.plugged}
            if v.plugged:
                msg["soc"] = round(v.soc, 2)
            out.append(msg)
        return out

    def advance(self, until: datetime) -> List[Tuple[datetime, Dict[str, Any]]]:
        """
        Simulate up to ``until`` and return the observations with the instant each should be delivered:
        a meter reading per physical step, and battery / car reports every ``report_every``.
        """
        pending: List[Tuple[datetime, Dict[str, Any]]] = []
        while self.now + self.step <= until:
            pending.extend(self._step())
        while self._next_report <= until:
            for msg in self.snapshot(at=self._next_report):
                pending.append((self._next_report + self.delays.get(msg["type"], timedelta(0)), msg))
            self._next_report += self.report_every
        return pending
