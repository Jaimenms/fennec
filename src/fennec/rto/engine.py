"""
The decision core of the daemon, free of I/O and of clocks so that it can be driven step by step in tests.

``observe()`` takes a message from the connector, ``tick()`` is called regularly with the current time.
Both return the messages to send back. The engine keeps the health of the loop:

* ``starting`` until every required signal has been received once;
* ``running`` while every required signal is fresh and plans succeed;
* ``degraded`` when an optional signal is missing or the last plan failed (safe commands are sent, the
  next attempt is scheduled);
* ``fault`` when a required signal is older than its deadline: safe commands are sent once and nothing
  else is commanded until the signal is fresh again, which triggers an immediate replan;
* ``paused`` on request of the connector.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..commands import Command
from ..horizon import floor_to
from .config import RtoConfig
from .learning import Learner
from .messages import Observation, outbound
from .planner import Plan, Planner, PlanningError
from .state import Health, HouseState

# what every device is told when the daemon cannot (or must not) decide: the equipment's own default
SAFE_COMMANDS = {
    "battery": ("set_mode", {"mode": "self_consumption"}),
    "ev": ("release", {}),
}

# commands that stay in force until replaced; the others carry a duration and must be renewed
STICKY_ACTIONS = {"set_mode", "charge", "release"}


class Audit:
    """Append-only JSON lines log of everything the engine saw, decided and sent."""

    def __init__(self, path: Optional[Union[str, Path]] = None):
        self.path = Path(path) if path else None
        self.records: List[Dict[str, Any]] = []  # kept in memory when there is no path

    def write(self, kind: str, now: datetime, payload: Dict[str, Any]) -> None:
        record = {"kind": kind, "time": now.isoformat(), **payload}
        if self.path is None:
            self.records.append(record)
            return
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


class Engine:
    def __init__(
        self,
        config: RtoConfig,
        planner: Optional[Planner] = None,
        audit: Optional[Audit] = None,
        learner: Optional[Learner] = None,
    ):
        self.config = config
        self.learner = learner
        self.planner = planner or Planner(config, learner=learner)
        self.audit = audit or Audit(config.audit)
        self.state = HouseState(config.deadlines)
        self.devices = config.device_names()  # kind -> asset name
        self.sent_log: List[Tuple[datetime, str]] = []  # (when, device kind) of every command sent

        self.health = Health.STARTING
        self.reason: Optional[str] = None
        self.paused = False
        self.plan: Optional[Plan] = None
        self.last_sent: Dict[str, Command] = {}
        self.last_plan_at: Optional[datetime] = None
        self.planned_boundary: Optional[datetime] = None
        self.replan_requested: Optional[str] = None
        self.next_retry_at: Optional[datetime] = None
        self.failures = 0

    # ------------------------------------------------------------------ inputs

    def observe(self, obs: Observation, now: datetime) -> List[Dict[str, Any]]:
        self.audit.write("observation", now, obs.to_dict())
        out: List[Dict[str, Any]] = []
        if obs.kind == "control":
            action = obs.data["action"]
            if action == "pause" and not self.paused:
                self.paused = True
                out += self._safe_commands(now)
                out.append(self._set_health(Health.PAUSED, "paused by the connector", now))
            elif action == "resume" and self.paused:
                self.paused = False
                self.request_replan("resumed")
                out.append(self._set_health(Health.STARTING, "resumed", now))
            elif action == "replan":
                self.request_replan("requested by the connector")
            return out

        previous = self.state.update(obs, now)
        if self.learner is not None:
            self.learner.observe(obs)
        if obs.kind == "ev":
            if previous is None or bool(previous.data.get("plugged")) != bool(obs.data.get("plugged")):
                self.request_replan("car plugged" if obs.data.get("plugged") else "car unplugged")
        elif obs.kind == "forecast":
            self.request_replan(f"new {obs.signal}")
        return out

    def request_replan(self, reason: str) -> None:
        if self.replan_requested is None:
            self.replan_requested = reason

    # ------------------------------------------------------------------ the loop

    def tick(self, now: datetime) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if self.paused:
            return out

        fresh = self.state.freshness(now)
        if fresh.missing:
            if self.health != Health.STARTING:
                out.append(self._set_health(Health.STARTING, f"waiting for {fresh.missing}", now))
            return out
        if fresh.stale:
            if self.health != Health.FAULT:
                out += self._enter_fault(f"stale: {', '.join(fresh.stale)}", now)
            return out
        if self.health in (Health.FAULT, Health.STARTING):
            self.request_replan("signals fresh again" if self.health == Health.FAULT else "all signals received")
            out.append(self._set_health(Health.RUNNING, None, now))

        reason = self._plan_due(now)
        if reason:
            out += self._replan(now, reason)
        return out

    def _plan_due(self, now: datetime) -> Optional[str]:
        boundary = floor_to(now, self.config.period)
        if self.planned_boundary is None or boundary > self.planned_boundary:
            return "settlement boundary"
        if self.replan_requested is not None:
            debounce = timedelta(seconds=float(self.config.replan["event_debounce_s"]))
            if self.last_plan_at is None or now - self.last_plan_at >= debounce:
                return self.replan_requested
        if self.next_retry_at is not None and now >= self.next_retry_at:
            return "retry"
        return None

    # ------------------------------------------------------------------ daily command budget

    def commands_sent(self, kind: str, now: datetime) -> int:
        """Commands sent to a device kind over the last 24 hours."""
        since = now - timedelta(days=1)
        self.sent_log = [(when, k) for when, k in self.sent_log if when > since]
        return sum(1 for _, k in self.sent_log if k == kind)

    def budgets(self, now: datetime) -> Dict[str, int]:
        """Commands each device may still receive today, from ``config.limits``."""
        out = {}
        for kind, limit in self.config.limits.items():
            if "commands_per_day" in limit and kind in self.devices:
                out[kind] = max(0, int(limit["commands_per_day"]) - self.commands_sent(kind, now))
        return out

    def _replan(self, now: datetime, reason: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        self.planned_boundary = floor_to(now, self.config.period)
        self.replan_requested = None
        try:
            plan = self.planner.plan(now, self.state, self.budgets(now))
        except PlanningError as e:
            self.failures += 1
            self.next_retry_at = now + timedelta(seconds=float(self.config.replan["retry_s"]))
            self.audit.write("plan_failed", now, {"reason": reason, "error": str(e), "failures": self.failures})
            if self.failures == 1:
                out += self._safe_commands(now)
            out.append(self._set_health(Health.DEGRADED, f"plan failed: {e}", now))
            return out

        self.plan, self.failures, self.next_retry_at, self.last_plan_at = plan, 0, None, now
        self.audit.write("plan", now, {"reason": reason, **plan.to_dict()})
        out += self._commands_now(plan, now)
        out.append(
            outbound(
                "plan",
                now,
                reason=reason,
                summary=plan.summary(),
                commands={device: [c.to_dict() for c in cmds] for device, cmds in plan.commands.items()},
            )
        )
        degraded = self.state.freshness(now).degraded
        health = Health.DEGRADED if degraded else Health.RUNNING
        out.append(self._set_health(health, f"optional signals stale: {degraded}" if degraded else None, now))
        return out

    # ------------------------------------------------------------------ commands

    def _commands_now(self, plan: Plan, now: datetime) -> List[Dict[str, Any]]:
        out = []
        for device in plan.commands:
            cmd = plan.current(device, now)
            if cmd is not None and self._should_send(cmd, now):
                out.append(self._send(cmd, now))
        return out

    def _should_send(self, cmd: Command, now: datetime) -> bool:
        last = self.last_sent.get(cmd.device)
        if last is None or not cmd.same_intent(last):
            return True
        if cmd.action not in STICKY_ACTIONS and last.until <= now + self.config.period:
            return True  # a timed command about to expire: renew it
        return False

    def _send(self, cmd: Command, now: datetime) -> Dict[str, Any]:
        self.last_sent[cmd.device] = cmd
        kind = next((k for k, name in self.devices.items() if name == cmd.device), cmd.device)
        self.sent_log.append((now, kind))
        self.audit.write("command", now, cmd.to_dict())
        return outbound("command", now, **cmd.to_dict())

    def _safe_commands(self, now: datetime) -> List[Dict[str, Any]]:
        out = []
        for kind, name in self.devices.items():
            action, params = SAFE_COMMANDS[kind]
            out.append(self._send(Command(name, action, now, now, dict(params)), now))
        return out

    # ------------------------------------------------------------------ health

    def _enter_fault(self, reason: str, now: datetime) -> List[Dict[str, Any]]:
        self.plan = None
        out = self._safe_commands(now)
        self.last_sent = {}  # so that everything is re-sent once the loop recovers
        out.append(self._set_health(Health.FAULT, reason, now))
        return out

    def _set_health(self, health: Health, reason: Optional[str], now: datetime) -> Dict[str, Any]:
        self.health, self.reason = health, reason
        self.audit.write("health", now, {"health": health.value, "reason": reason})
        return self.status(now)

    def status(self, now: datetime) -> Dict[str, Any]:
        fresh = self.state.freshness(now)
        return outbound(
            "status",
            now,
            health=self.health.value,
            reason=self.reason,
            paused=self.paused,
            missing=fresh.missing,
            stale=fresh.stale,
            degraded=fresh.degraded,
            never_received=fresh.optional_missing,
            readings=self.state.snapshot(now),
            last_plan=self.plan.summary() if self.plan else None,
            commands_24h={kind: self.commands_sent(kind, now) for kind in self.devices},
            command_budgets=self.budgets(now),
            learned=self.learner.summary() if self.learner is not None else None,
            next_boundary=(floor_to(now, self.config.period) + self.config.period).isoformat(),
        )
