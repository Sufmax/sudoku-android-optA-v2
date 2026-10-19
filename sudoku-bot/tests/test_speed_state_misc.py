import random
import struct

import numpy as np
import pytest

from bot.adb.client import AdbError, parse_raw_screencap
from bot.adb.humanize import Humanizer
from bot.config import ConfigManager, load_config
from bot.models import Rect
from bot.speed.manager import SpeedManager, WaveMetrics
from bot.state.machine import BotState, IllegalTransition, StateMachine
from bot.state.store import JsonStore
from bot.telemetry.control import drain, write_command


def good():
    return WaveMetrics(0.0, 40, 400, 0.2)


def test_adaptive_starts_medium_climbs_and_drops(cfg):
    sp = SpeedManager(lambda: cfg.speed)
    assert sp.mode == "adaptive" and sp.tier_name() == "medium"
    t = 1000.0
    changes = [sp.report(good(), t + i) for i in range(3)]
    assert changes[-1] == "up" and sp.tier_name() == "fast"
    assert sp.report(WaveMetrics(0.5, 40, 400, 0.2), t + 10) == "down"
    assert sp.tier_name() == "medium"
    # plafond : impossible de remonter à « fast » pendant ceiling_hold_s
    for i in range(10):
        sp.report(good(), t + 20 + i)
    assert sp.tier_name() == "medium"
    for i in range(10):
        sp.report(good(), t + 2000 + i)
    assert sp.tier_name() in ("fast", "very_fast")


def test_cpu_load_blocks_climb(cfg):
    sp = SpeedManager(lambda: cfg.speed)
    for i in range(6):
        sp.report(WaveMetrics(0.0, 40, 400, 3.0), 100 + i)
    assert sp.tier_name() == "medium"


def test_manual_mode_and_persistence(cfg):
    sp = SpeedManager(lambda: cfg.speed)
    assert sp.set_mode("slow") and sp.tier().wave_size == cfg.speed.tiers["slow"].wave_size
    assert not sp.set_mode("warp")
    sp2 = SpeedManager(lambda: cfg.speed, sp.to_state())
    assert sp2.mode == "slow"


def test_state_machine():
    sm = StateMachine()
    sm.go(BotState.WAIT_DEVICE)
    sm.go(BotState.WAIT_READY)
    with pytest.raises(IllegalTransition):
        sm.go(BotState.SOLVING)
    sm.go(BotState.OBSERVE)
    sm.go(BotState.SOLVING)
    sm.go(BotState.PAUSED)
    with pytest.raises(IllegalTransition):
        sm.go(BotState.SOLVING)  # après une pause : observation obligatoire
    sm.go(BotState.OBSERVE)
    assert len(sm.history) == 6


def test_humanizer_stays_in_bounds(cfg):
    h = Humanizer(cfg.human, random.Random(42))
    r = Rect(100, 200, 80, 60)
    for _ in range(3000):
        p = h.touch(r)
        for x, y in ((p.x1, p.y1), (p.x2, p.y2)):
            assert abs(x - r.cx) <= cfg.human.tap_max_frac * r.w + 1e-6
            assert abs(y - r.cy) <= cfg.human.tap_max_frac * r.h + 1e-6
        assert cfg.human.press_ms[0] <= p.duration_ms <= cfg.human.press_ms[1]
    pts = [h.point_in(r) for _ in range(500)]
    assert sum(1 for x, _ in pts if abs(x - r.cx) < 0.5) < 25  # pas toujours le centre exact


def test_parse_raw_screencap():
    w, h = 3, 2
    px = np.arange(w * h * 4, dtype=np.uint8).tobytes()
    img = parse_raw_screencap(struct.pack("<IIII", w, h, 1, 0) + px)
    assert img.shape == (2, 3, 3)
    with pytest.raises(AdbError):
        parse_raw_screencap(b"\x00" * 8)


def test_store_and_control(tmp_path):
    s = JsonStore(tmp_path / "a.json")
    s.save({"x": 1})
    assert s.load() == {"x": 1}
    (tmp_path / "b.json").write_text("{corrompu")
    assert JsonStore(tmp_path / "b.json").load({"d": 1}) == {"d": 1}
    write_command(tmp_path / "inbox", "ready")
    write_command(tmp_path / "inbox", "set_speed", mode="fast")
    cmds = drain(tmp_path / "inbox")
    assert [c["action"] for c in cmds] == ["ready", "set_speed"] and drain(tmp_path / "inbox") == []


def test_config_hot_reload(tmp_path):
    from bot.config import DEFAULT_CONFIG_PATH
    p = tmp_path / "c.yaml"
    p.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    cm = ConfigManager(p)
    text = p.read_text(encoding="utf-8").replace("min_confidence_action: 0.75", "min_confidence_action: 0.8").replace('avd_name: "sudoku"', 'avd_name: "autre"')
    restart = cm.update_from_yaml(text)
    assert cm.cfg.detection.min_confidence_action == 0.8
    assert "emulator.avd_name" in restart
    with pytest.raises(Exception):
        cm.update_from_yaml(text.replace("tap_max_frac: 0.30", "tap_max_frac: 0.9"))
    assert cm.cfg.human.tap_max_frac == 0.30


def test_emulator_config_defaults_match_proven_recipe():
    """La configuration livrée doit reprendre la recette émulateur validée sur CodeSandbox."""
    from bot.config import load_config
    cfg = load_config(apply_env=False)
    e = cfg.emulator
    assert e.api_level == 29 and e.abi == "x86_64"
    assert e.gpu == "swiftshader_indirect"
    assert e.image_variant in ("playstore", "aurora")
    assert e.ram_mb <= 4096 and e.cores <= 3
    assert e.backend == "auto"
    assert cfg.display.novnc_port == 6080 and cfg.display.xvfb_display == ":1"


def test_display_section_requires_restart(tmp_path):
    from bot.config import DEFAULT_CONFIG_PATH
    p = tmp_path / "c.yaml"
    p.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    cm = ConfigManager(p)
    text = p.read_text(encoding="utf-8").replace('xvfb_screen: "1920x1080x24"', 'xvfb_screen: "1280x1024x24"')
    restart = cm.update_from_yaml(text)
    assert "display.xvfb_screen" in restart


def test_resolve_serial_uses_console_port(monkeypatch):
    from bot.config import DEFAULT_CONFIG_PATH
    from bot.main import resolve_serial
    monkeypatch.delenv("ADB_SERIAL", raising=False)
    monkeypatch.delenv("ANDROID_BACKEND", raising=False)
    cm = ConfigManager(DEFAULT_CONFIG_PATH)
    cm.cfg.emulator.backend = "avd"
    cm.cfg.adb.serial = ""
    assert resolve_serial(cm) == f"emulator-{cm.cfg.emulator.console_port}"
