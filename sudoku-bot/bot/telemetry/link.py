"""Lien WebSocket sortant vers le Cloudflare Worker (reconnexion avec backoff exponentiel + jitter).

Les messages respectent le protocole documenté dans `worker/PROTOCOL.md`.
Les images (`frame`) ne sont jamais mises en file : seule la plus récente est envoyée.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger("bot.link")

try:  # websockets >= 13
    from websockets.asyncio.client import connect as _ws_connect  # type: ignore
    _HEADERS_KW = "additional_headers"
except ImportError:  # pragma: no cover - anciennes versions
    from websockets import connect as _ws_connect  # type: ignore
    _HEADERS_KW = "extra_headers"

PROTOCOL_VERSION = 1


class DashboardLink:
    def __init__(self, url: str, password: str, machine_id: str, version: str,
                 on_command: Callable[[dict], Awaitable[None]],
                 backoff_initial: float = 1.0, backoff_max: float = 60.0) -> None:
        self.url = url
        self.password = password
        self.machine_id = machine_id
        self.version = version
        self.on_command = on_command
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
        self.latest_frame: dict | None = None
        self.frame_event = asyncio.Event()
        self.connected = False
        self.viewers = 0
        self.stream_fps: float | None = None
        self._stop = asyncio.Event()

    def send(self, msg_type: str, **payload: Any) -> None:
        msg = {"v": PROTOCOL_VERSION, "type": msg_type, "machine": self.machine_id, "ts": time.time(), **payload}
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()  # on sacrifie le plus ancien
                self.queue.put_nowait(msg)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    def send_frame(self, jpeg_b64: str, width: int, height: int) -> None:
        self.latest_frame = {"v": PROTOCOL_VERSION, "type": "frame", "machine": self.machine_id, "ts": time.time(),
                             "mime": "image/jpeg", "width": width, "height": height, "data": jpeg_b64}
        self.frame_event.set()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        delay = self.backoff_initial
        url = f"{self.url}{'&' if '?' in self.url else '?'}machine={self.machine_id}"
        while not self._stop.is_set():
            try:
                kwargs = {_HEADERS_KW: {"X-Bot-Key": self.password, "X-Bot-Version": self.version}, "max_size": 8 * 1024 * 1024, "ping_interval": 20}
                async with _ws_connect(url, **kwargs) as ws:
                    self.connected = True
                    delay = self.backoff_initial
                    log.info("dashboard connecté (%s)", self.url)
                    await self._session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # réseau, TLS, refus d'auth… : on réessaie toujours
                log.warning("dashboard indisponible : %s — nouvel essai dans %.0fs", exc, delay)
            finally:
                self.connected = False
            try:
                await asyncio.wait_for(self._stop.wait(), delay + random.uniform(0, delay * 0.3))
            except asyncio.TimeoutError:
                pass
            delay = min(self.backoff_max, delay * 2)

    async def _session(self, ws: Any) -> None:
        self.send("hello", version=self.version, protocol=PROTOCOL_VERSION)

        async def sender() -> None:
            while True:
                get_msg = asyncio.ensure_future(self.queue.get())
                get_frame = asyncio.ensure_future(self.frame_event.wait())
                done, pending = await asyncio.wait({get_msg, get_frame}, return_when=asyncio.FIRST_COMPLETED)
                for p in pending:
                    p.cancel()
                if get_msg in done:
                    await ws.send(json.dumps(get_msg.result(), ensure_ascii=False))
                if get_frame in done and self.latest_frame is not None:
                    self.frame_event.clear()
                    frame, self.latest_frame = self.latest_frame, None
                    await ws.send(json.dumps(frame))

        async def receiver() -> None:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    log.warning("message dashboard illisible ignoré")
                    continue
                if msg.get("type") == "viewers":
                    self.viewers = int(msg.get("count", 0))
                    continue
                if msg.get("type") == "command":
                    try:
                        await self.on_command(msg)
                    except Exception:
                        log.exception("échec de la commande %s", msg.get("action"))

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                if t.exception():
                    raise t.exception()  # type: ignore[misc]
        finally:
            for t in tasks:
                t.cancel()
