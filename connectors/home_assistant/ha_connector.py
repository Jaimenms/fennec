#!/usr/bin/env python3
"""
Example connector: Home Assistant <-> Fennec daemon.

This script is NOT part of the fennec package and the package does not depend on it. It shows what a
connector has to do, using only the Python standard library:

* poll Home Assistant's REST API for the entities listed in the configuration and send the daemon one
  observation per device (battery, ev, meter) with ``time`` = the entity's ``last_updated``;
* read the daemon's commands and turn them into Home Assistant service calls;
* reconnect to both sides when they go away; while the daemon is unreachable nothing is commanded, and
  the daemon itself enters its fault state when our readings stop.

Entity ids, units and service names depend on your integrations (for Huawei inverters the
"huawei_solar" custom integration by wlcrs exposes the working mode as a select entity and forcible
charge / discharge as services). Check them against your installation: the names in
``config.example.json`` are placeholders.

    python3 ha_connector.py config.json
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class HomeAssistant:
    """Minimal REST client (states and service calls)."""

    def __init__(self, url: str, token: str, timeout: float = 10.0):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(f"{self.url}{path}", data=body, headers=self.headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            text = resp.read().decode()
            return json.loads(text) if text else None

    def state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._request("GET", f"/api/states/{entity_id}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def call(self, domain: str, service: str, data: Dict[str, Any]) -> None:
        self._request("POST", f"/api/services/{domain}/{service}", data)


def number(state: Optional[Dict[str, Any]], scale: float = 1.0) -> Optional[float]:
    if state is None or state.get("state") in (None, "unknown", "unavailable", ""):
        return None
    try:
        return float(state["state"]) * scale
    except (TypeError, ValueError):
        return None


def boolean(state: Optional[Dict[str, Any]], true_values=("on", "true", "connected", "charging")) -> Optional[bool]:
    if state is None or state.get("state") in (None, "unknown", "unavailable"):
        return None
    return str(state["state"]).lower() in true_values


def updated_at(*states: Optional[Dict[str, Any]]) -> str:
    """The oldest ``last_updated`` of the states that compose an observation, as the daemon wants it."""
    stamps = [s["last_updated"] for s in states if s and s.get("last_updated")]
    if not stamps:
        return datetime.now(timezone.utc).isoformat()
    return min(stamps)


class Connector:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.ha = HomeAssistant(cfg["home_assistant"]["url"], cfg["home_assistant"]["token"])
        self.poll_s = float(cfg.get("poll_seconds", 60))
        self.writer: Optional[asyncio.StreamWriter] = None

    # ------------------------------------------------------------------ observations

    def read_battery(self) -> Optional[Dict[str, Any]]:
        e = self.cfg.get("battery")
        if not e:
            return None
        soc_state = self.ha.state(e["soc"])
        soc = number(soc_state)
        if soc is None:
            return None
        msg: Dict[str, Any] = {"type": "battery", "time": updated_at(soc_state), "soc": soc}
        mode_state = self.ha.state(e["mode"]) if e.get("mode") else None
        if mode_state is not None:
            option = str(mode_state.get("state"))
            msg["mode"] = "self_consumption" if option == e.get("self_consumption_option", option) else "forced"
        for key, field in (("power", "power_kw"), ("pv_power", "pv_kw"), ("setpoint", "setpoint_kw")):
            if e.get(key):
                value = number(self.ha.state(e[key]), e.get(f"{key}_scale", 0.001))  # W -> kW by default
                if value is not None:
                    msg[field] = value
        return msg

    def read_ev(self) -> Optional[Dict[str, Any]]:
        e = self.cfg.get("ev")
        if not e:
            return None
        plugged_state = self.ha.state(e["plugged"])
        plugged = boolean(plugged_state)
        if plugged is None:
            return None
        msg: Dict[str, Any] = {"type": "ev", "time": updated_at(plugged_state), "plugged": plugged}
        if e.get("soc"):
            soc = number(self.ha.state(e["soc"]))
            if soc is not None:
                msg["soc"] = soc
        if e.get("charging"):
            charging = boolean(self.ha.state(e["charging"]))
            if charging is not None:
                msg["charging"] = charging
        if e.get("power"):
            power = number(self.ha.state(e["power"]), e.get("power_scale", 0.001))
            if power is not None:
                msg["power_kw"] = power
        return msg

    def read_meter(self) -> Optional[Dict[str, Any]]:
        e = self.cfg.get("meter")
        if not e:
            return None
        if e.get("power"):  # one signed sensor: positive imports
            state = self.ha.state(e["power"])
            power = number(state, e.get("power_scale", 0.001))
            if power is None:
                return None
            sign = -1.0 if e.get("positive_is_export") else 1.0
            msg = {"type": "meter", "time": updated_at(state), "power_kw": sign * power}
        else:
            imp_state, exp_state = self.ha.state(e["import"]), self.ha.state(e["export"])
            imp, exp = number(imp_state, e.get("power_scale", 0.001)), number(exp_state, e.get("power_scale", 0.001))
            if imp is None or exp is None:
                return None
            msg = {"type": "meter", "time": updated_at(imp_state, exp_state), "import_kw": imp, "export_kw": exp}
        if e.get("load"):
            load = number(self.ha.state(e["load"]), e.get("power_scale", 0.001))
            if load is not None:
                msg["load_kw"] = load
        return msg

    async def poll(self) -> None:
        while True:
            for reader in (self.read_battery, self.read_ev, self.read_meter):
                try:
                    msg = await asyncio.to_thread(reader)
                except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
                    print(f"home assistant read failed: {e}", file=sys.stderr)
                    msg = None
                if msg is not None:
                    await self.send(msg)
            await asyncio.sleep(self.poll_s)

    # ------------------------------------------------------------------ commands

    def execute(self, cmd: Dict[str, Any]) -> None:
        device, action = cmd["device"], cmd["action"]
        battery, ev = self.cfg.get("battery", {}), self.cfg.get("ev", {})
        if battery and device == battery.get("device_name", "battery"):
            services = battery["services"]
            if action == "set_mode":
                self.ha.call(
                    "select",
                    "select_option",
                    {
                        "entity_id": battery["mode"],
                        "option": battery["self_consumption_option"],
                    },
                )
            elif action in ("force_charge", "force_discharge"):
                domain, service = services[action].split(".")
                self.ha.call(
                    domain,
                    service,
                    {
                        **services.get("target", {}),
                        "power": int(round(float(cmd["power_kw"]) * 1000)),
                        "duration": int(round(float(cmd.get("minutes", 15)))),
                    },
                )
            elif action == "hold":
                domain, service = services["hold"].split(".")
                self.ha.call(
                    domain,
                    service,
                    {**services.get("target", {}), "power": 0, "duration": int(round(float(cmd.get("minutes", 15))))},
                )
            elif action == "set_power":  # ideal controller: not available on a Huawei
                print(f"ignoring unsupported action {action}", file=sys.stderr)
        elif ev and device == ev.get("device_name", "car"):
            if action == "charge":
                on = bool(cmd.get("on", float(cmd.get("power_kw", 0)) > 0))
                self.ha.call("switch", "turn_on" if on else "turn_off", {"entity_id": ev["switch"]})
            elif action == "release":
                self.ha.call("switch", "turn_on", {"entity_id": ev["switch"]})  # the charger's own default
        print(f"executed {device} {action}", file=sys.stderr)

    # ------------------------------------------------------------------ daemon socket

    async def send(self, msg: Dict[str, Any]) -> None:
        if self.writer is None:
            return
        try:
            self.writer.write((json.dumps(msg) + "\n").encode())
            await self.writer.drain()
        except (ConnectionError, RuntimeError):
            self.writer = None

    async def daemon_loop(self) -> None:
        d = self.cfg["daemon"]
        while True:
            try:
                if d.get("unix"):
                    reader, writer = await asyncio.open_unix_connection(d["unix"])
                else:
                    reader, writer = await asyncio.open_connection(d.get("host", "127.0.0.1"), int(d.get("port", 7777)))
            except OSError as e:
                print(f"daemon unreachable: {e}; retrying", file=sys.stderr)
                await asyncio.sleep(10)
                continue
            self.writer = writer
            print("connected to the daemon", file=sys.stderr)
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    msg = json.loads(line)
                    if msg.get("type") == "command":
                        try:
                            await asyncio.to_thread(self.execute, msg)
                        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
                            print(f"command failed: {e}", file=sys.stderr)
                    elif msg.get("type") == "status" and msg.get("health") in ("fault", "degraded"):
                        print(f"daemon {msg['health']}: {msg.get('reason')}", file=sys.stderr)
            finally:
                self.writer = None
                writer.close()
            await asyncio.sleep(5)

    async def run(self) -> None:
        await asyncio.gather(self.daemon_loop(), self.poll())


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        cfg = json.load(f)
    try:
        asyncio.run(Connector(cfg).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
