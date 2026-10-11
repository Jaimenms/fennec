"""
The daemon: an asyncio loop around the engine, talking JSON lines to one or more connectors.

    python -m fennec.rto config.json --tcp 127.0.0.1:7777
    python -m fennec.rto config.json --unix /run/fennec.sock

A connector opens the socket, writes one JSON object per line (see ``fennec.rto.messages``) and reads the
commands and status messages the daemon writes back. The daemon never opens connections itself and knows
nothing about inverters, chargers or meters.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Set

from .config import RtoConfig
from .engine import Audit, Engine
from .learning import Learner
from .messages import MessageError, Observation, outbound


class Transport(Protocol):
    async def receive(self) -> Dict[str, Any]: ...

    async def send(self, message: Dict[str, Any]) -> None: ...


class MemoryTransport:
    """In-process transport for tests and simulations."""

    def __init__(self):
        self.inbox: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self.outbox: List[Dict[str, Any]] = []

    def push(self, message: Dict[str, Any]) -> None:
        self.inbox.put_nowait(message)

    async def receive(self) -> Dict[str, Any]:
        return await self.inbox.get()

    async def send(self, message: Dict[str, Any]) -> None:
        self.outbox.append(message)


class JsonLinesServer:
    """TCP or Unix-socket server; every connected client receives every outbound message."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7777, unix_path: Optional[str] = None):
        self.host, self.port, self.unix_path = host, port, unix_path
        self.queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self.writers: Set[asyncio.StreamWriter] = set()
        self.server: Optional[asyncio.AbstractServer] = None

    async def start(self) -> None:
        if self.unix_path:
            self.server = await asyncio.start_unix_server(self._client, path=self.unix_path)
        else:
            self.server = await asyncio.start_server(self._client, host=self.host, port=self.port)

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for w in list(self.writers):
            w.close()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8").strip()
                if not text:
                    continue
                try:
                    self.queue.put_nowait(json.loads(text))
                except json.JSONDecodeError as e:
                    writer.write((json.dumps({"type": "error", "error": f"bad JSON: {e}"}) + "\n").encode())
                    await writer.drain()
        finally:
            self.writers.discard(writer)
            writer.close()

    async def receive(self) -> Dict[str, Any]:
        return await self.queue.get()

    async def send(self, message: Dict[str, Any]) -> None:
        line = (json.dumps(message, default=str) + "\n").encode("utf-8")
        for w in list(self.writers):
            try:
                w.write(line)
                await w.drain()
            except (ConnectionError, RuntimeError):
                self.writers.discard(w)


class Daemon:
    def __init__(
        self,
        engine: Engine,
        transport: Transport,
        tick_seconds: float = 5.0,
        status_seconds: float = 60.0,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.engine = engine
        self.transport = transport
        self.tick_seconds = tick_seconds
        self.status_seconds = status_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = asyncio.Lock()

    async def _emit(self, messages: Sequence[Dict[str, Any]]) -> None:
        for m in messages:
            await self.transport.send(m)

    async def _reader(self) -> None:
        while True:
            raw = await self.transport.receive()
            now = self.clock()
            try:
                obs = Observation.from_dict(raw, received_at=now)
            except MessageError as e:
                await self.transport.send(outbound("error", now, error=str(e), message=raw))
                continue
            async with self._lock:
                out = self.engine.observe(obs, now)
            await self._emit(out)

    async def _ticker(self) -> None:
        while True:
            now = self.clock()
            async with self._lock:
                out = await asyncio.to_thread(self.engine.tick, now)  # a solve may take a while
            await self._emit(out)
            await asyncio.sleep(self.tick_seconds)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.status_seconds)
            await self.transport.send(self.engine.status(self.clock()))

    async def run(self, stop: Optional[asyncio.Event] = None) -> None:
        stop = stop or asyncio.Event()
        tasks = [asyncio.create_task(c()) for c in (self._reader, self._ticker, self._heartbeat)]
        try:
            await stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------- command line


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fennec.rto", description="Fennec real-time optimizer daemon")
    p.add_argument("config", help="path to the JSON configuration (see fennec.rto.config)")
    p.add_argument("--tcp", default="127.0.0.1:7777", help="listen on HOST:PORT (default 127.0.0.1:7777)")
    p.add_argument("--unix", default=None, help="listen on a Unix socket path instead of TCP")
    p.add_argument("--tick", type=float, default=5.0, help="seconds between engine ticks")
    p.add_argument("--status-every", type=float, default=60.0, help="seconds between status heartbeats")
    p.add_argument("--audit", default=None, help="JSON lines audit file (overrides the config)")
    return p


async def serve(args: argparse.Namespace) -> None:
    config = RtoConfig.load(args.config)
    audit = Audit(args.audit or config.audit)
    learner = None
    if config.learning.get("enabled", True) and audit.path is not None:
        learner = Learner.from_audit(
            audit.path, config.house["pv"], days=int(config.learning["days"]), min_days=int(config.learning["min_days"])
        )
        print(f"learned forecasts: {learner.summary()}", file=sys.stderr)
    engine = Engine(config, audit=audit, learner=learner)
    if args.unix:
        transport = JsonLinesServer(unix_path=args.unix)
    else:
        host, _, port = args.tcp.rpartition(":")
        transport = JsonLinesServer(host=host or "127.0.0.1", port=int(port))
    await transport.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover  (Windows)
            pass
    where = args.unix or args.tcp
    print(f"fennec rto listening on {where}; devices: {engine.devices}", file=sys.stderr)
    try:
        await Daemon(engine, transport, args.tick, args.status_every).run(stop)
    finally:
        await transport.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    asyncio.run(serve(args))
    return 0
