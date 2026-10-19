"""Client ADB asynchrone : capture d'écran brute, injection d'appuis, reconnexion, infos appareil.

Les appuis passent par un `adb shell` persistant (pas un processus par tap) : latence
divisée par 3 à 5. Chaque commande est suivie d'un marqueur, ce qui garantit qu'aucun
ordre « périmé » ne s'exécute après un timeout (corrige le bug B4 de l'ancien projet :
en cas de timeout la session est tuée, jamais réutilisée).
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import re
import struct
import time
from dataclasses import dataclass

import cv2
import numpy as np

from bot.config import AdbCfg

log = logging.getLogger("bot.adb")


class AdbError(RuntimeError):
    """Échec d'une commande ADB (appareil absent, timeout, sortie invalide)."""


def parse_raw_screencap(data: bytes) -> np.ndarray:
    """Décode la sortie de `screencap` (sans -p) en image BGR."""
    if len(data) < 12:
        raise AdbError("screencap : sortie trop courte")
    w, h, fmt = struct.unpack_from("<III", data, 0)
    size = w * h * 4
    header = len(data) - size
    if w == 0 or h == 0 or header not in (12, 16):
        raise AdbError(f"screencap : en-tête invalide (w={w} h={h} fmt={fmt} reste={header})")
    arr = np.frombuffer(data, dtype=np.uint8, count=size, offset=header).reshape(h, w, 4)
    if fmt == 5:  # BGRA_8888
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)


@dataclass
class DeviceInfo:
    model: str = "?"
    android: str = "?"
    sdk: str = "?"
    width: int = 0
    height: int = 0
    density: int = 0
    ram_mb: int = 0
    battery: int = -1
    serial: str = ""

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


class _ShellSession:
    def __init__(self, adb: str, serial: str) -> None:
        self.adb, self.serial = adb, serial
        self.proc: asyncio.subprocess.Process | None = None
        self.ids = itertools.count(1)
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            self.adb, "-s", self.serial, "shell",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    async def kill(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                log.warning("session shell ADB récalcitrante")
        self.proc = None

    async def run(self, cmd: str, timeout: float) -> str:
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None:
                await self.start()
            assert self.proc and self.proc.stdin and self.proc.stdout
            marker = f"__END_{next(self.ids)}__"
            self.proc.stdin.write(f"{cmd}; echo {marker}\n".encode())
            try:
                await self.proc.stdin.drain()
                out: list[str] = []
                while True:
                    line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
                    if not line:
                        raise AdbError("session shell fermée")
                    s = line.decode(errors="replace").rstrip("\r\n")
                    if s == marker:
                        return "\n".join(out)
                    out.append(s)
            except (asyncio.TimeoutError, ConnectionError, AdbError) as exc:
                await self.kill()  # jamais de réutilisation d'une session incertaine
                raise AdbError(f"shell persistant : {exc!r}") from exc


class AdbClient:
    def __init__(self, cfg: AdbCfg, serial: str) -> None:
        self.cfg = cfg
        self.serial = serial
        self.session = _ShellSession(cfg.path, serial)
        self.last_latency_ms = 0.0
        self.last_capture_ms = 0.0
        self.consecutive_failures = 0

    async def _exec(self, *args: str, timeout: float | None = None, with_serial: bool = True) -> bytes:
        cmd = [self.cfg.path] + (["-s", self.serial] if with_serial else []) + list(args)
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError as exc:
            raise AdbError(f"binaire adb introuvable : {self.cfg.path}") from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout or self.cfg.command_timeout_s)
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise AdbError(f"timeout : {' '.join(args)}") from exc
        if proc.returncode != 0:
            raise AdbError(f"{' '.join(args)} → code {proc.returncode} : {err.decode(errors='replace').strip()[:200]}")
        return out

    async def shell(self, cmd: str, timeout: float | None = None) -> str:
        return (await self._exec("shell", cmd, timeout=timeout)).decode(errors="replace").strip()

    async def get_state(self) -> str:
        try:
            return (await self._exec("get-state", timeout=5)).decode().strip()
        except AdbError:
            return "offline"

    async def ensure_connected(self) -> bool:
        """Démarre le serveur, (re)connecte l'appareil réseau si besoin, vérifie le boot complet."""
        for attempt in range(1, self.cfg.reconnect_attempts + 1):
            try:
                await self._exec("start-server", with_serial=False, timeout=15)
                if ":" in self.serial:
                    await self._exec("connect", self.serial, with_serial=False, timeout=10)
                if await self.get_state() == "device" and (await self.shell("getprop sys.boot_completed", 5)).strip() == "1":
                    self.consecutive_failures = 0
                    return True
            except AdbError as exc:
                log.warning("connexion ADB tentative %d/%d : %s", attempt, self.cfg.reconnect_attempts, exc)
            try:
                await self._exec("reconnect", timeout=8)
            except AdbError:
                pass
            await asyncio.sleep(min(30.0, 1.5 ** attempt))
        return False

    async def screencap(self) -> np.ndarray:
        t0 = time.monotonic()
        try:
            if self.cfg.screencap_mode == "raw":
                img = parse_raw_screencap(await self._exec("exec-out", "screencap"))
            else:
                data = await self._exec("exec-out", "screencap", "-p")
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    raise AdbError("PNG illisible")
        except AdbError:
            self.consecutive_failures += 1
            raise
        self.consecutive_failures = 0
        self.last_capture_ms = (time.monotonic() - t0) * 1000
        return img

    async def input(self, cmd: str) -> None:
        t0 = time.monotonic()
        try:
            await self.session.run(cmd, self.cfg.command_timeout_s)
        except AdbError:
            self.consecutive_failures += 1
            raise
        self.consecutive_failures = 0
        self.last_latency_ms = (time.monotonic() - t0) * 1000

    async def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int) -> None:
        await self.input(f"input swipe {int(round(x1))} {int(round(y1))} {int(round(x2))} {int(round(y2))} {max(1, int(duration_ms))}")

    async def key(self, keycode: int | str) -> None:
        await self.input(f"input keyevent {keycode}")

    async def text(self, value: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9@._\-]", lambda m: "%s" if m.group(0) == " " else "", value)
        await self.input(f"input text '{safe}'")

    async def launch_app(self, package: str) -> None:
        await self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", timeout=15)

    async def foreground_package(self) -> str:
        out = await self.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -n 2", timeout=8)
        m = re.search(r"([a-zA-Z0-9_.]+)/[a-zA-Z0-9_.$]+", out)
        return m.group(1) if m else ""

    async def device_info(self) -> DeviceInfo:
        info = DeviceInfo(serial=self.serial)
        try:
            info.model = await self.shell("getprop ro.product.model", 5)
            info.android = await self.shell("getprop ro.build.version.release", 5)
            info.sdk = await self.shell("getprop ro.build.version.sdk", 5)
            size = await self.shell("wm size", 5)
            m = re.findall(r"(\d+)x(\d+)", size)
            if m:
                info.width, info.height = int(m[-1][0]), int(m[-1][1])
            dens = re.findall(r"(\d+)", await self.shell("wm density", 5))
            info.density = int(dens[-1]) if dens else 0
            mem = re.search(r"MemTotal:\s+(\d+)", await self.shell("cat /proc/meminfo", 5))
            info.ram_mb = int(mem.group(1)) // 1024 if mem else 0
            bat = re.search(r"level:\s*(\d+)", await self.shell("dumpsys battery", 8))
            info.battery = int(bat.group(1)) if bat else -1
        except AdbError as exc:
            log.warning("infos appareil partielles : %s", exc)
        return info

    async def snapshot_save(self, name: str) -> None:
        """Sauvegarde d'un snapshot de l'émulateur (backend avd uniquement)."""
        await self._exec("emu", "avd", "snapshot", "save", name, timeout=180)

    async def close(self) -> None:
        await self.session.kill()
