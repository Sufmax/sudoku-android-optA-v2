"""Point d'entrée du bot : `python -m bot.main [--config ...] [--analyze capture.png]`."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

from bot import __version__
from bot.adb.client import AdbClient
from bot.config import DEFAULT_CONFIG_PATH, ROOT, ConfigManager, load_config
from bot.controller import Controller
from bot.telemetry import control
from bot.telemetry.link import DashboardLink
from bot.telemetry.logs import setup_logging

log = logging.getLogger("bot.main")
VAR = ROOT / "var"


def resolve_serial(cm: ConfigManager) -> str:
    cfg = cm.cfg
    if cfg.adb.serial:
        return cfg.adb.serial
    backend = cfg.emulator.backend
    marker = VAR / "backend"
    if backend == "auto" and marker.exists():
        backend = marker.read_text().strip() or "avd"
    if backend in ("remote", "redroid"):
        return cfg.emulator.remote_serial
    # Série de l'émulateur local : « emulator-<port console> » (cf. start_emulator.sh -port)
    return f"emulator-{cfg.emulator.console_port}"


def analyze_file(path: str, config: str) -> int:
    """Analyse hors-ligne d'une capture : utile pour régler la détection sans appareil."""
    import cv2
    from bot.ocr.engine import OcrEngine
    from bot.vision.glyphs import TemplateBank
    from bot.vision.screens import ScreenAnalyzer

    cfg = load_config(config)
    img = cv2.imread(path)
    if img is None:
        print(f"image illisible : {path}", file=sys.stderr)
        return 2
    bank = TemplateBank(cfg.detection.cells.template_size, cfg.detection.cells.templates_per_symbol, VAR / "state" / "templates.npz")
    an = ScreenAnalyzer(cfg, OcrEngine(cfg.ocr), bank)
    obs, _ = an.analyse(img)
    out = {"kind": obs.kind.value, "rule": obs.rule_id, "confidence": round(obs.confidence, 3), "detail": obs.detail, "texts": obs.texts[:30]}
    if obs.grid:
        out["grid"] = obs.grid.values()
        out["kinds"] = [[c.kind.value[0] for c in row] for row in obs.grid.cells]
    if obs.keypad:
        out["keypad"] = {d: k.rect.to_list() for d, k in sorted(obs.keypad.keys.items())}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


async def amain(args: argparse.Namespace) -> int:
    cm = ConfigManager(args.config)
    cfg = cm.cfg
    sink = setup_logging(cfg.telemetry.log_level, ROOT / cfg.telemetry.json_log_path, cfg.telemetry.json_log_max_mb)
    log.info("Sudoku Bot %s — machine %s", __version__, cfg.machine.id)
    adb = AdbClient(cfg.adb, resolve_serial(cm))
    link: DashboardLink | None = None
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    if cfg.dashboard.enabled and cfg.dashboard.url and not args.no_dashboard:
        if not password:
            log.error("DASHBOARD_PASSWORD absent : dashboard désactivé")
        else:
            link = DashboardLink(cfg.dashboard.url, password, cfg.machine.id, __version__, lambda m: ctrl.handle_command(m),
                                 cfg.dashboard.backoff_initial_s, cfg.dashboard.backoff_max_s)
    else:
        log.info("dashboard désactivé (DASHBOARD_URL vide)")
    ctrl = Controller(cm, adb, VAR, link)
    if link:
        sink.callback = lambda item: link.send("log", entry=item)

    loop = asyncio.get_running_loop()

    def _stop() -> None:
        log.warning("arrêt demandé (signal)")
        ctrl.stop_flag = True
        ctrl.running.set()
        if link:
            link.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    async def housekeeping() -> None:
        inbox = VAR / "control" / "inbox"
        tick = 0
        while not ctrl.stop_flag:
            for cmd in control.drain(inbox):
                await ctrl.handle_command(cmd)
            try:
                reloaded, restart = cm.reload_if_changed()
                if reloaded:
                    ctrl.apply_config()
                    if restart:
                        log.warning("modifié mais nécessite un redémarrage : %s", ", ".join(restart))
            except Exception as exc:  # YAML invalide édité à la main : on garde l'ancienne config
                log.error("config.yaml invalide, ancienne configuration conservée : %s", exc)
                cm._mtime = cm.path.stat().st_mtime
            tick += 1
            if tick % int(max(1, cfg.dashboard.heartbeat_s * 2)) == 0:
                ctrl.publish_status()
                ctrl.publish_stats()
                ctrl.stats.flush()
            await asyncio.sleep(0.5)

    tasks = [asyncio.create_task(ctrl.run(), name="controller"), asyncio.create_task(housekeeping(), name="housekeeping")]
    if link:
        tasks += [asyncio.create_task(link.run(), name="link"), asyncio.create_task(ctrl.stream_loop(), name="stream")]
    await tasks[0]
    for t in tasks[1:]:
        t.cancel()
    await asyncio.gather(*tasks[1:], return_exceptions=True)
    await adb.close()
    log.info("bot arrêté proprement")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Sudoku Bot autonome (ADB + vision)")
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    p.add_argument("--analyze", metavar="IMAGE", help="analyse une capture et affiche le résultat (aucun appareil requis)")
    p.add_argument("--no-dashboard", action="store_true")
    args = p.parse_args()
    if args.analyze:
        raise SystemExit(analyze_file(args.analyze, args.config))
    raise SystemExit(asyncio.run(amain(args)))


if __name__ == "__main__":
    main()
