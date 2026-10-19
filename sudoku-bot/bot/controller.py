"""Contrôleur principal : orchestre observation, navigation, résolution par vagues et reprise.

Règle d'or : le bot REFUSE D'AGIR lorsqu'il doute. Toute action suit une capture fraîche
dont la confiance dépasse `detection.min_confidence_action` ; sinon il re-capture.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import random
import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from bot.adb.client import AdbClient, AdbError, DeviceInfo
from bot.adb.humanize import Humanizer
from bot.config import ROOT, ConfigManager, ScreenRule
from bot.input.executor import KeyMissingError, execute_wave, tap
from bot.input.waves import (GivenMismatchError, WaveSizer, correct_counts, evaluate_wave, next_wave, order_moves, plan_moves)
from bot.models import CellKind, GridRead, ScreenKind, ScreenObservation
from bot.ocr.engine import OcrEngine
from bot.solver.solver import SolveStatus, candidates, find_conflicts, solve
from bot.speed.manager import SpeedManager, WaveMetrics
from bot.state.machine import BotState, StateMachine, Transition
from bot.state.store import JsonStore
from bot.telemetry.link import DashboardLink
from bot.telemetry.metrics import StatsStore
from bot.vision.glyphs import TemplateBank
from bot.vision.screens import ScreenAnalyzer

log = logging.getLogger("bot.ctrl")

KEYCODE_BACK = 4


class StopRequested(Exception):
    pass


class DeviceLost(Exception):
    pass


class Reobserve(Exception):
    """Levée après une pause : l'écran a pu changer, toute lecture antérieure est périmée."""


def givens_hash(read: GridRead) -> str:
    g = read.givens()
    return hashlib.sha1(json.dumps(g).encode()).hexdigest()[:16]


class Controller:
    def __init__(self, cm: ConfigManager, adb: AdbClient, var_dir: Path, link: DashboardLink | None) -> None:
        self.cm = cm
        self.adb = adb
        self.var = var_dir
        self.link = link
        cfg = cm.cfg
        self.bank = TemplateBank(cfg.detection.cells.template_size, cfg.detection.cells.templates_per_symbol, var_dir / "state" / "templates.npz")
        self.ocr = OcrEngine(cfg.ocr)
        self.analyzer = ScreenAnalyzer(cfg, self.ocr, self.bank)
        self.human = Humanizer(cfg.human)
        self.rng = random.Random()
        self.runtime = JsonStore(var_dir / "state" / "runtime.json")
        self.rt: dict[str, Any] = self.runtime.load({"ready": False, "solutions": {}, "speed": {}})
        self.speed = SpeedManager(lambda: self.cm.cfg.speed, self.rt.get("speed"))
        self.stats = StatsStore(ROOT / cfg.telemetry.stats_path)
        self.sm = StateMachine(self._on_transition)
        self.running = asyncio.Event()
        self.running.set()
        self.ready = asyncio.Event()
        self.stop_flag = False
        self.device = DeviceInfo(serial=adb.serial)
        self.detail = ""
        self.progress: dict[str, int] = {"filled": 0, "total": 0}
        self.last_img: np.ndarray | None = None
        self.last_img_at = 0.0
        self.last_screen = ""
        self.current_game: dict[str, Any] | None = None
        self.rule_repeats: dict[str, int] = {}
        self.unknown_count = 0
        self.last_snapshot = time.time()
        self.sizer = self._new_sizer()
        self.was_ready_before = bool(self.rt.get("ready"))

    # ------------------------------------------------------------ utilitaires
    def _new_sizer(self) -> WaveSizer:
        w = self.cm.cfg.waves
        return WaveSizer(w.min_wave, w.fail_rate_shrink, w.shrink_factor, w.grow_factor, w.clean_waves_to_grow)

    def apply_config(self) -> None:
        """Propage une nouvelle configuration (rechargement à chaud)."""
        cfg = self.cm.cfg
        self.analyzer.cfg = cfg
        self.ocr.cfg = cfg.ocr
        self.human.cfg = cfg.human
        log.info("configuration appliquée à chaud")
        self.publish_status()

    def _on_transition(self, tr: Transition) -> None:
        log.info("état %s → %s %s", tr.src.value, tr.dst.value, f"({tr.reason})" if tr.reason else "")
        self.publish_status()

    def go(self, state: BotState, reason: str = "") -> None:
        if self.sm.can(state):
            self.sm.go(state, reason)
        else:
            self.sm.go(BotState.OBSERVE, f"repli sûr depuis {self.sm.state.value}")
            if state != BotState.OBSERVE and self.sm.can(state):
                self.sm.go(state, reason)

    def persist(self) -> None:
        self.rt["speed"] = self.speed.to_state()
        sols = self.rt.get("solutions", {})
        if len(sols) > 20:
            self.rt["solutions"] = dict(list(sols.items())[-20:])
        self.runtime.save(self.rt)

    async def sleep_ms(self, ms: float) -> None:
        end = time.monotonic() + ms / 1000
        while True:
            if self.stop_flag:
                raise StopRequested
            left = end - time.monotonic()
            if left <= 0:
                return
            await asyncio.sleep(min(left, 0.25))

    async def checkpoint(self) -> None:
        """Point d'arrêt : pause / arrêt pris en compte ici (jamais au milieu d'un coup)."""
        if self.stop_flag:
            raise StopRequested
        if not self.running.is_set():
            prev = self.sm.state
            if self.sm.can(BotState.PAUSED):
                self.go(BotState.PAUSED, "pause demandée")
            await self.running.wait()
            if self.stop_flag:
                raise StopRequested
            if prev != BotState.PAUSED and self.sm.state == BotState.PAUSED:
                self.go(BotState.OBSERVE, "reprise")
            raise Reobserve()

    def save_failure(self, img: np.ndarray | None, reason: str) -> None:
        t = self.cm.cfg.telemetry
        if img is None or not t.save_failure_screens:
            return
        d = ROOT / t.failure_screens_dir
        d.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() else "_" for ch in reason)[:40]
        cv2.imwrite(str(d / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        files = sorted(d.glob("*.jpg"))
        for f in files[: max(0, len(files) - t.failure_screens_max)]:
            f.unlink(missing_ok=True)

    # ------------------------------------------------------------ publication
    def status(self) -> dict[str, Any]:
        return {
            "state": self.sm.state.value,
            "since": self.sm.since,
            "detail": self.detail,
            "screen": self.last_screen,
            "paused": not self.running.is_set(),
            "ready": self.ready.is_set(),
            "speed": {"mode": self.speed.mode, "tier": self.speed.tier_name(), "label": self.speed.label(), "choices": self.speed.choices(), "wave_factor": round(self.sizer.factor, 3)},
            "progress": self.progress,
            "game": {k: v for k, v in (self.current_game or {}).items() if k in ("id", "n", "box", "started", "errors", "waves")},
            "adb": {"serial": self.adb.serial, "latency_ms": round(self.adb.last_latency_ms, 1), "capture_ms": round(self.adb.last_capture_ms, 1), "failures": self.adb.consecutive_failures},
            "device": self.device.as_dict(),
            "emulator": self.emulator_state(),
            "templates": len(self.bank),
        }

    def emulator_state(self) -> dict[str, Any]:
        """État de l'émulateur écrit par scripts/start_emulator.sh (var/state/emulator.json).

        Contient l'accélération (KVM ou logicielle), la variante d'image, l'AVD et
        l'URL noVNC de l'écran distant. Retourne un dictionnaire vide si absent/illisible.
        """
        path = self.var / "state" / "emulator.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def publish_status(self) -> None:
        st = self.status()
        try:
            JsonStore(self.var / "state" / "status.json").save({**st, "stats": self.stats.snapshot(), "updated": time.time()})
        except OSError as exc:
            log.debug("status.json non écrit : %s", exc)
        if self.link:
            self.link.send("status", status=st)

    def publish_stats(self) -> None:
        if self.link:
            self.link.send("metrics", stats=self.stats.snapshot())

    # ------------------------------------------------------------ capture
    async def capture(self) -> np.ndarray:
        try:
            img = await self.adb.screencap()
        except AdbError as exc:
            log.warning("capture impossible : %s", exc)
            if self.adb.consecutive_failures >= 3:
                raise DeviceLost(str(exc)) from exc
            await self.sleep_ms(500)
            img = await self.adb.screencap()
        self.last_img, self.last_img_at = img, time.time()
        return img

    def encode_frame(self, img: np.ndarray) -> tuple[str, int, int]:
        d = self.cm.cfg.dashboard
        h, w = img.shape[:2]
        scale = d.stream_width / float(w)
        small = cv2.resize(img, (d.stream_width, int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, d.stream_quality])
        if not ok:
            raise ValueError("encodage JPEG impossible")
        return base64.b64encode(buf.tobytes()).decode(), w, h

    async def stream_loop(self) -> None:
        """Envoie périodiquement l'écran au dashboard, uniquement s'il y a des spectateurs."""
        while not self.stop_flag:
            fps = (self.link.stream_fps if self.link and self.link.stream_fps else self.cm.cfg.dashboard.stream_fps)
            period = 1.0 / max(0.05, fps)
            await asyncio.sleep(period)
            if not self.link or not self.link.connected or self.link.viewers <= 0:
                continue
            try:
                img = self.last_img if (self.last_img is not None and time.time() - self.last_img_at < period) else await self.adb.screencap()
                if img is not None:
                    data, w, h = await asyncio.to_thread(self.encode_frame, img)
                    self.link.send_frame(data, w, h)
            except (AdbError, ValueError) as exc:
                log.debug("flux écran : %s", exc)

    # ------------------------------------------------------------ commandes
    async def handle_command(self, msg: dict) -> None:
        action = msg.get("action")
        params = msg.get("params") or {}
        ok, info = True, ""
        if action == "ready":
            self.ready.set()
            self.rt["ready"] = True
            self.persist()
            info = "PRÊT reçu"
        elif action == "pause":
            self.running.clear()
        elif action == "resume":
            self.running.set()
        elif action == "set_speed":
            ok = self.speed.set_mode(str(params.get("mode", "")))
            info = self.speed.label()
            self.persist()
        elif action == "stop":
            self.stop_flag = True
            self.running.set()
        elif action == "set_stream" and self.link:
            self.link.stream_fps = float(params.get("fps", self.cm.cfg.dashboard.stream_fps))
        elif action == "get_config" and self.link:
            self.link.send("config", yaml=self.cm.raw_yaml())
        elif action == "set_config":
            try:
                restart = self.cm.update_from_yaml(str(params.get("yaml", "")))
                self.apply_config()
                info = ("redémarrage requis pour : " + ", ".join(restart)) if restart else "appliquée à chaud"
            except Exception as exc:  # validation pydantic / YAML : renvoyée telle quelle à l'utilisateur
                ok, info = False, f"configuration refusée : {exc}"
            if self.link:
                self.link.send("config", yaml=self.cm.raw_yaml())
        elif action in ("tap", "swipe", "key", "text"):
            ok, info = await self.remote_input(action, params)
        elif action == "snapshot":
            ok, info = await self.save_snapshot()
        else:
            ok, info = False, f"action inconnue : {action}"
        log.info("commande %s → %s %s", action, "ok" if ok else "refusée", info)
        if self.link and msg.get("id"):
            self.link.send("ack", id=msg["id"], ok=ok, info=info)
        self.publish_status()

    async def remote_input(self, action: str, p: dict) -> tuple[bool, str]:
        """Contrôle manuel depuis le dashboard : autorisé seulement hors jeu autonome."""
        if self.sm.state not in (BotState.WAIT_READY, BotState.PAUSED, BotState.WAIT_DEVICE):
            return False, "contrôle manuel disponible uniquement en attente de PRÊT ou en pause"
        w = self.device.width or (self.last_img.shape[1] if self.last_img is not None else 0)
        h = self.device.height or (self.last_img.shape[0] if self.last_img is not None else 0)
        if not w or not h:
            return False, "résolution inconnue"
        try:
            if action == "tap":
                await self.adb.swipe(float(p["x"]) * w, float(p["y"]) * h, float(p["x"]) * w, float(p["y"]) * h, 60)
            elif action == "swipe":
                await self.adb.swipe(float(p["x1"]) * w, float(p["y1"]) * h, float(p["x2"]) * w, float(p["y2"]) * h, int(p.get("ms", 300)))
            elif action == "key":
                await self.adb.key({"back": 4, "home": 3, "recents": 187, "enter": 66, "del": 67}.get(str(p.get("key")), str(p.get("key"))))
            elif action == "text":
                await self.adb.text(str(p.get("text", "")))
        except (AdbError, KeyError, ValueError) as exc:
            return False, str(exc)
        self.last_img_at = 0.0
        return True, ""

    async def save_snapshot(self) -> tuple[bool, str]:
        name = self.cm.cfg.emulator.checkpoint_snapshot
        try:
            await self.adb.snapshot_save(name)
            self.last_snapshot = time.time()
            return True, f"snapshot {name} sauvegardé"
        except AdbError as exc:
            return False, f"snapshot impossible (backend non-avd ?) : {exc}"

    # ------------------------------------------------------------ boucle principale
    async def run(self) -> None:
        try:
            await self._connect_device()
            await self._wait_ready()
            while not self.stop_flag:
                try:
                    await self.checkpoint()
                    await self.step()
                except Reobserve:
                    log.info("reprise après pause : nouvelle observation complète")
                except DeviceLost as exc:
                    self.stats.stats.errors += 1
                    log.error("appareil perdu : %s", exc)
                    await self._connect_device()
                except (AdbError, KeyMissingError) as exc:
                    self.stats.stats.errors += 1
                    log.warning("action interrompue : %s — retour à l'observation", exc)
                    self.go(BotState.OBSERVE, "erreur récupérable")
                    await self.sleep_ms(800)
        except StopRequested:
            pass
        finally:
            if self.sm.can(BotState.STOPPING):
                self.sm.go(BotState.STOPPING, "arrêt")
            self.persist()
            self.stats.flush()
            try:
                self.bank.save()
            except OSError as exc:
                log.error("gabarits non sauvegardés : %s", exc)

    async def _connect_device(self) -> None:
        self.go(BotState.WAIT_DEVICE, "connexion ADB")
        failures = 0
        while not self.stop_flag:
            if await self.adb.ensure_connected():
                self.device = await self.adb.device_info()
                if self.link:
                    self.link.send("device", device=self.device.as_dict())
                log.info("appareil prêt : %s Android %s %dx%d", self.device.model, self.device.android, self.device.width, self.device.height)
                return
            failures += 1
            if failures >= self.cm.cfg.adb.restart_emulator_after_failures:
                failures = 0
                await self._restart_emulator()
            await self.sleep_ms(3000)
        raise StopRequested

    async def _restart_emulator(self) -> None:
        script = ROOT / "scripts" / "start_emulator.sh"
        log.error("ADB injoignable : redémarrage de l'émulateur en dernier recours")
        try:
            # Sans KVM, un boot à froid peut prendre jusqu'à boot_timeout_s : on laisse le script aller au bout.
            timeout = self.cm.cfg.emulator.boot_timeout_s + 300
            await asyncio.to_thread(subprocess.run, ["bash", str(script), "--restart"], timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.error("redémarrage émulateur impossible : %s", exc)

    async def _wait_ready(self) -> None:
        if self.was_ready_before and self.cm.cfg.workflow.auto_ready_on_resume:
            self.ready.set()
            log.info("relancement : PRÊT déjà donné, reprise automatique")
        if not self.ready.is_set():
            self.go(BotState.WAIT_READY, "configuration manuelle")
            hint = "relancement : ouvre le jeu, ajuste, puis PRÊT" if self.was_ready_before else "premier lancement : connecte Google, installe le jeu, ouvre-le, puis PRÊT"
            self.detail = hint
            log.warning("EN ATTENTE DE « PRÊT » — %s. Dashboard (bouton PRÊT) ou : ./run.sh ready", hint)
            self.publish_status()
            while not self.ready.is_set():
                if self.stop_flag:
                    raise StopRequested
                if self.link and self.link.viewers > 0:
                    try:
                        await self.capture()
                    except (AdbError, DeviceLost):
                        pass
                await asyncio.sleep(1.0)
        self.detail = ""
        self.go(BotState.OBSERVE, "PRÊT")

    async def step(self) -> None:
        cfg = self.cm.cfg
        if self.sm.state != BotState.OBSERVE:
            self.go(BotState.OBSERVE)
        img = await self.capture()
        obs, lines = await asyncio.to_thread(self.analyzer.analyse, img)
        self.last_screen = obs.rule_id or obs.kind.value
        self.detail = obs.detail
        min_conf = cfg.detection.min_confidence_action
        if obs.kind == ScreenKind.GAME and obs.grid is not None:
            self.unknown_count = 0
            if obs.confidence < min_conf:
                self.detail = f"grille vue mais confiance {obs.confidence:.2f} < {min_conf}"
                self.stats.stats.rereads += 1
                await self.sleep_ms(cfg.timing.screen_poll_ms)
                return
            self.go(BotState.SOLVING, obs.detail)
            await self.solve_game(obs)
            return
        if obs.kind == ScreenKind.RULE and obs.rule_id:
            self.unknown_count = 0
            rule = next(r for r in cfg.screens if r.id == obs.rule_id)
            if obs.confidence < min_conf * 0.9:
                await self.sleep_ms(cfg.timing.screen_poll_ms)
                return
            await self.handle_rule(rule, img, lines)
            return
        if obs.kind == ScreenKind.LOADING:
            self.go(BotState.LOADING, obs.detail)
            await self.sleep_ms(cfg.timing.screen_poll_ms)
            return
        self.unknown_count += 1
        self.publish_status()
        await self.recover_unknown(img, obs)

    async def recover_unknown(self, img: np.ndarray, obs: ScreenObservation) -> None:
        cfg = self.cm.cfg
        n = self.unknown_count
        retries = cfg.timing.unknown_screen_retries
        if n <= retries:
            await self.sleep_ms(cfg.timing.screen_poll_ms * (1 + n * 0.5))
            return
        self.go(BotState.RECOVERING, f"écran non reconnu ({obs.detail})")
        self.save_failure(img, f"unknown_{obs.kind.value}")
        if n <= retries + 2:
            log.warning("écran inconnu persistant : touche RETOUR")
            await self.adb.key(KEYCODE_BACK)
            await self.sleep_ms(1200)
        else:
            pkg = cfg.emulator.game_package
            log.error("écran inconnu persistant : relance du jeu %s", pkg)
            try:
                if await self.adb.foreground_package() != pkg:
                    await self.adb.launch_app(pkg)
                else:
                    await self.adb.key(KEYCODE_BACK)
            except AdbError as exc:
                log.error("relance impossible : %s", exc)
            self.unknown_count = 0
            await self.sleep_ms(cfg.timing.relaunch_wait_s * 1000)
        self.go(BotState.OBSERVE)

    async def handle_rule(self, rule: ScreenRule, img: np.ndarray, lines: list) -> None:
        cfg = self.cm.cfg
        self.rule_repeats[rule.id] = self.rule_repeats.get(rule.id, 0) + 1
        for k in list(self.rule_repeats):
            if k != rule.id:
                self.rule_repeats[k] = 0
        repeats = self.rule_repeats[rule.id]
        if rule.id in ("game_over", "loss"):
            self.finish_game(won=(rule.id == "game_over"))
            if repeats == 1:
                self.go(BotState.GAME_OVER, rule.id)
                await self.sleep_ms(cfg.timing.game_over_wait_ms)
                await self.maybe_snapshot()
                return  # on re-capture : l'écran de fin a pu évoluer
        self.go(BotState.NAVIGATE, rule.id)
        action = rule.action
        if repeats > cfg.timing.max_action_retries:
            log.warning("règle %s répétée %d fois sans effet : RETOUR", rule.id, repeats)
            self.save_failure(img, f"stuck_{rule.id}")
            await self.adb.key(KEYCODE_BACK)
            self.rule_repeats[rule.id] = 0
            await self.sleep_ms(1200)
            return
        if action.type == "wait":
            await self.sleep_ms(cfg.timing.screen_poll_ms)
            return
        if action.type == "back":
            await self.adb.key(KEYCODE_BACK)
            await self.sleep_ms(self.human.delay_ms(cfg.timing.popup_wait_ms))
            return
        if action.type == "relaunch":
            await self.adb.launch_app(cfg.emulator.game_package)
            await self.sleep_ms(cfg.timing.relaunch_wait_s * 1000)
            return
        if action.type in ("tap_text", "tap_blob_above_text"):
            target = self.analyzer.locate(img, lines, rule)
            if target is None or target.confidence < cfg.detection.min_confidence_action * 0.9:
                if action.fallback == "back":
                    await self.adb.key(KEYCODE_BACK)
                log.info("cible introuvable ou peu sûre pour %s (%s)", rule.id, target and round(target.confidence, 2))
                await self.sleep_ms(cfg.timing.screen_poll_ms)
                return
            await self.sleep_ms(self.human.delay_ms((350, 120)) + self.human.extra_pause_ms())
            log.info("%s : appui sur « %s » (confiance %.2f)", rule.id, target.label, target.confidence)
            await tap(self.adb, self.human, target.rect)
            await self.sleep_ms(self.human.delay_ms(cfg.timing.after_menu_tap_ms))

    async def maybe_snapshot(self) -> None:
        e = self.cm.cfg.emulator
        if e.snapshot_every_s > 0 and time.time() - self.last_snapshot > e.snapshot_every_s and self.adb.serial.startswith("emulator-"):
            ok, info = await self.save_snapshot()
            log.info(info)

    # ------------------------------------------------------------ partie
    def start_game_if_new(self, read: GridRead) -> None:
        gid = givens_hash(read)
        if self.current_game and self.current_game.get("id") == gid:
            return
        geo = read.geometry
        self.current_game = {"id": gid, "n": geo.n, "box": [geo.box_rows, geo.box_cols], "started": time.time(), "errors": 0, "waves": 0, "corr": {}}
        self.sizer = self._new_sizer()
        self.stats.stats.games_started += 1
        log.info("nouvelle partie %s (%dx%d, blocs %dx%d)", gid, geo.n, geo.n, geo.box_rows, geo.box_cols)
        self.stats.flush()
        self.publish_stats()

    def finish_game(self, won: bool) -> None:
        if not self.current_game:
            return
        dur = time.time() - self.current_game["started"]
        if won:
            self.stats.stats.games_won += 1
            self.stats.stats.total_game_s += dur
            self.stats.stats.last_game_s = dur
        else:
            self.stats.stats.games_failed += 1
        log.info("partie %s %s en %.1fs", self.current_game["id"], "réussie" if won else "perdue", dur)
        self.rt.get("solutions", {}).pop(self.current_game["id"], None)
        self.current_game = None
        self.progress = {"filled": 0, "total": 0}
        self.stats.flush()
        self.persist()
        self.publish_stats()
        try:
            self.bank.save()
        except OSError as exc:
            log.error("gabarits non sauvegardés : %s", exc)

    async def read_game(self, need: int) -> ScreenObservation | None:
        """Capture + lecture ; renvoie la lecture si `need` lectures consécutives concordent."""
        prev: list[list[int]] | None = None
        kinds_prev: list[list[str]] | None = None
        agree = 0
        for _ in range(need + 2):
            img = await self.capture()
            obs = await asyncio.to_thread(self.analyzer.analyse_game, img)
            if obs is None or obs.kind != ScreenKind.GAME or obs.grid is None:
                return obs
            vals = obs.grid.values()
            kinds = [[c.kind.value for c in row] for row in obs.grid.cells]
            agree = agree + 1 if (vals == prev and kinds == kinds_prev) else 1
            prev, kinds_prev = vals, kinds
            if agree >= need:
                return obs
            self.stats.stats.rereads += 1
            await self.sleep_ms(150)
        return None

    def validate_read(self, read: GridRead) -> str | None:
        """Raison du rejet, ou None si la lecture est exploitable."""
        min_conf = self.cm.cfg.detection.min_confidence_action
        for r, row in enumerate(read.cells):
            for c, cell in enumerate(row):
                if cell.kind == CellKind.UNKNOWN:
                    return f"case ({r},{c}) encre non classée"
                if cell.kind != CellKind.EMPTY and cell.confidence < min_conf:
                    return f"case ({r},{c}) chiffre incertain ({cell.confidence:.2f})"
        geo = read.geometry
        if find_conflicts(read.givens(), geo.box_rows, geo.box_cols):
            return "chiffres initiaux en conflit (lecture fausse)"
        return None

    def solution_for(self, read: GridRead) -> list[list[int]] | None:
        cfg = self.cm.cfg
        gid = givens_hash(read)
        cached = self.rt.get("solutions", {}).get(gid)
        if cached:
            return cached
        geo = read.geometry
        res = solve(read.givens(), geo.box_rows, geo.box_cols, cfg.safety.solver_timeout_s)
        log.info("solveur : %s (%d nœuds, %.3fs)", res.status.value, res.nodes, res.elapsed_s)
        if res.status == SolveStatus.UNIQUE or (res.status == SolveStatus.MULTIPLE and not cfg.safety.require_unique_solution):
            self.rt.setdefault("solutions", {})[gid] = res.solution
            self.persist()
            return res.solution
        return None

    async def solve_game(self, first: ScreenObservation) -> None:
        cfg = self.cm.cfg
        rereads = 0
        obs: ScreenObservation | None = first
        solution: list[list[int]] | None = None
        while True:
            await self.checkpoint()
            obs = await self.read_game(cfg.safety.consensus_reads) if solution is None else obs
            if obs is None or obs.kind != ScreenKind.GAME or obs.grid is None:
                self.go(BotState.OBSERVE, "grille plus visible")
                return
            read = obs.grid
            reason = self.validate_read(read)
            if reason is None:
                self.start_game_if_new(read)
                solution = self.solution_for(read)
                if solution is None:
                    reason = "grille insoluble ou ambiguë avec cette lecture"
            if reason is None and solution is not None:
                break
            rereads += 1
            self.stats.stats.rereads += 1
            log.warning("lecture rejetée (%s) — relecture %d/%d", reason, rereads, cfg.safety.max_rereads)
            if rereads >= cfg.safety.max_rereads:
                self.save_failure(self.last_img, "read_rejected")
                self.go(BotState.OBSERVE, "lecture impossible")
                await self.sleep_ms(1500)
                return
            await self.sleep_ms(400)
        assert self.current_game is not None
        await self.play_waves(obs, solution)

    async def play_waves(self, obs: ScreenObservation, solution: list[list[int]]) -> None:
        cfg = self.cm.cfg
        game = self.current_game
        assert game is not None and obs.grid is not None and obs.keypad is not None
        read, keypad = obs.grid, obs.keypad
        geo = read.geometry
        cand = candidates(read.values(), geo.box_rows, geo.box_cols)
        stuck_since = time.time()
        while True:
            await self.checkpoint()
            try:
                moves = plan_moves(read, solution)
            except GivenMismatchError as exc:
                log.error("incohérence chiffre initial / solution : %s — relecture complète", exc)
                self.rt.get("solutions", {}).pop(game["id"], None)
                self.go(BotState.OBSERVE, "incohérence")
                return
            total = sum(1 for row in read.cells for c in row if c.kind != CellKind.GIVEN)
            self.progress = {"filled": total - len(moves), "total": total}
            if not moves:
                self.detail = "grille complète, attente de l'écran de fin"
                self.publish_status()
                await self.sleep_ms(cfg.timing.game_over_wait_ms)
                self.go(BotState.OBSERVE, "grille complète")
                return
            for m in moves:
                key = f"{m.r},{m.c}"
                if game["corr"].get(key, 0) > cfg.waves.max_corrections_per_cell:
                    log.error("case %s corrigée trop souvent : arrêt sûr de la partie", key)
                    self.save_failure(self.last_img, "too_many_corrections")
                    self.running.clear()
                    self.detail = "pause de sécurité : corrections répétées (voir logs)"
                    return
            if time.time() - stuck_since > cfg.safety.stuck_game_timeout_s:
                log.error("aucun progrès depuis %ss : retour à l'observation", cfg.safety.stuck_game_timeout_s)
                self.go(BotState.OBSERVE, "partie bloquée")
                return
            tier = self.speed.tier()
            ordered = order_moves(moves, cfg.human.move_order, geo.box_rows, geo.box_cols, cand, self.rng)
            wave = next_wave(ordered, correct_counts(read, solution), geo.n, self.sizer.size(tier.wave_size), set(keypad.keys), cfg.waves.cut_on_digit_complete)
            if not wave:
                log.warning("aucun coup jouable avec le pavé visible %s — relecture", sorted(keypad.keys))
                obs2 = await self.read_game(1)
                if obs2 is None or obs2.grid is None or obs2.keypad is None:
                    self.go(BotState.OBSERVE)
                    return
                read, keypad = obs2.grid, obs2.keypad
                continue
            if keypad.confidence < cfg.detection.min_confidence_action:
                log.warning("pavé peu sûr (%.2f) — relecture", keypad.confidence)
                obs2 = await self.read_game(1)
                if obs2 is None or obs2.grid is None or obs2.keypad is None:
                    self.go(BotState.OBSERVE)
                    return
                read, keypad = obs2.grid, obs2.keypad
                continue
            overwrite = {(m.r, m.c) for m in wave if read.cells[m.r][m.c].value}
            for m in wave:
                if read.cells[m.r][m.c].value:
                    k = f"{m.r},{m.c}"
                    game["corr"][k] = game["corr"].get(k, 0) + 1
            self.detail = f"vague de {len(wave)} coup(s) · {self.speed.label()}"
            self.publish_status()
            erase_rect = None
            if cfg.waves.correction == "erase_then_write" and overwrite:
                erase_rect = await self.locate_erase()
            t_wave = time.monotonic()
            done = await execute_wave(self.adb, self.human, tier, wave, geo, keypad, self.checkpoint, erase_rect, overwrite)
            adb_lat = self.adb.last_latency_ms
            await self.sleep_ms(tier.settle_ms)
            t_render = time.monotonic()
            after_obs = await self.read_game(tier.verify_reads)
            render_ms = (time.monotonic() - t_render) * 1000 + tier.settle_ms
            game["waves"] += 1
            self.stats.stats.waves += 1
            self.stats.stats.digits_placed += done
            self.stats.stats.corrections += len(overwrite)
            if after_obs is None or after_obs.kind != ScreenKind.GAME or after_obs.grid is None or after_obs.keypad is None:
                # Fin de partie probable (dernier coup) ou pop-up : l'observation suivante tranchera.
                log.info("grille non visible après la vague (%.1fs) — observation", time.monotonic() - t_wave)
                self.go(BotState.OBSERVE, "après vague")
                return
            result = evaluate_wave(wave[:done], read, after_obs.grid)
            if result.givens_changed:
                log.error("chiffres initiaux différents après la vague : lecture douteuse, observation")
                self.save_failure(self.last_img, "givens_changed")
                self.go(BotState.OBSERVE, "lecture douteuse")
                return
            if result.fail_rate > 0:
                self.stats.stats.failed_waves += 1
            if result.errors:
                game["errors"] += len(result.errors)
                self.stats.stats.game_errors_red += len(result.errors)
                log.warning("le jeu a refusé %d chiffre(s) : %s", len(result.errors), [(m.r, m.c, m.v) for m in result.errors])
                if game["errors"] >= cfg.safety.max_game_errors:
                    self.speed.set_mode(cfg.speed.order[0])
                    self.sizer.factor = 0.05
                    log.error("seuil d'erreurs atteint : vitesse minimale et vagues unitaires")
            self.sizer.update(result)
            change = self.speed.report(WaveMetrics(result.fail_rate, adb_lat, render_ms))
            if change:
                log.info("vitesse adaptative %s → %s", change, self.speed.label())
            if result.ok:
                stuck_since = time.time()
            log.info("vague %d : %d ok, %d manquant(s), %d faux, %d erreur(s) · rendu %.0f ms · ADB %.0f ms",
                     game["waves"], len(result.ok), len(result.missing), len(result.wrong), len(result.errors), render_ms, adb_lat)
            read, keypad = after_obs.grid, after_obs.keypad
            self.publish_stats()

    async def locate_erase(self):
        """Bouton « Effacer » localisé par OCR sur la capture courante (aucune position mémorisée)."""
        from bot.ocr.text import find_phrase
        from bot.vision.buttons import button_region
        if self.last_img is None:
            return None
        lines = await asyncio.to_thread(self.ocr.read_lines, self.last_img)
        m = find_phrase(lines, self.cm.cfg.resolve_texts(["@erase"]), self.cm.cfg.ocr.match_ratio)
        if m is None:
            return None
        rect, _ = button_region(self.last_img, m.rect)
        return rect
