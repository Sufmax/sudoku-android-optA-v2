"""Paliers de vitesse et mode adaptatif.

Règles du mode adaptatif :
- départ au palier `adaptive.start` (Moyen) ;
- DESCENTE immédiate si la vague échoue au-delà de `down_fail_rate`, ou si la latence ADB /
  le temps de rendu dépassent les seuils « mauvais » ; le palier quitté devient un plafond
  temporaire (`ceiling_hold_s`) ;
- MONTÉE après `up_after_clean_waves` vagues propres consécutives avec latences « bonnes »
  et charge CPU sous `cpu_load_max`, hors période de cooldown et sous le plafond.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from bot.config import SpeedCfg, SpeedTier

ADAPTIVE = "adaptive"


@dataclass
class WaveMetrics:
    fail_rate: float
    adb_latency_ms: float
    render_ms: float
    cpu_load: float | None = None


def current_cpu_load() -> float:
    """Charge moyenne sur 1 min rapportée au nombre de vCPU (0 si indisponible)."""
    try:
        return os.getloadavg()[0] / max(1, os.cpu_count() or 1)
    except OSError:
        return 0.0


class SpeedManager:
    def __init__(self, cfg: Callable[[], SpeedCfg], state: dict | None = None) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        c = cfg()
        self.mode: str = c.mode
        self.auto_tier: str = c.adaptive.start
        self.clean_streak = 0
        self.cooldown = 0
        self.ceiling: tuple[str, float] | None = None
        self.history: list[dict] = []
        if state:
            self._restore(state)

    # ------------------------------------------------------------------ état
    def _restore(self, state: dict) -> None:
        c = self._cfg()
        if state.get("mode") in (ADAPTIVE, *c.tiers):
            self.mode = state["mode"]
        if state.get("auto_tier") in c.tiers:
            self.auto_tier = state["auto_tier"]

    def to_state(self) -> dict:
        with self._lock:
            return {"mode": self.mode, "auto_tier": self.auto_tier, "history": self.history[-30:]}

    # ------------------------------------------------------------- consultation
    def choices(self) -> list[dict[str, str]]:
        c = self._cfg()
        return [{"id": ADAPTIVE, "label": "Adaptatif"}] + [{"id": k, "label": c.tiers[k].label} for k in c.order if k in c.tiers]

    def tier_name(self) -> str:
        with self._lock:
            c = self._cfg()
            name = self.auto_tier if self.mode == ADAPTIVE else self.mode
            return name if name in c.tiers else c.adaptive.start

    def tier(self) -> SpeedTier:
        return self._cfg().tiers[self.tier_name()]

    def label(self) -> str:
        t = self.tier()
        return f"Adaptatif › {t.label}" if self.mode == ADAPTIVE else t.label

    def set_mode(self, mode: str) -> bool:
        c = self._cfg()
        if mode != ADAPTIVE and mode not in c.tiers:
            return False
        with self._lock:
            self.mode = mode
            self.clean_streak = 0
            self.cooldown = 0
        return True

    # ------------------------------------------------------------- adaptation
    def _bounds(self, c: SpeedCfg) -> tuple[int, int]:
        order = c.order
        lo = order.index(c.adaptive.min) if c.adaptive.min in order else 0
        hi = order.index(c.adaptive.max) if c.adaptive.max in order else len(order) - 1
        return lo, hi

    def report(self, m: WaveMetrics, now: float | None = None) -> str | None:
        """Intègre les métriques d'une vague ; renvoie 'up', 'down' ou None."""
        now = time.time() if now is None else now
        c = self._cfg()
        a = c.adaptive
        load = current_cpu_load() if m.cpu_load is None else m.cpu_load
        with self._lock:
            self.history.append({"t": round(now, 1), "tier": self.auto_tier, "fail": round(m.fail_rate, 3), "adb": round(m.adb_latency_ms), "render": round(m.render_ms), "cpu": round(load, 2)})
            self.history = self.history[-200:]
            if self.mode != ADAPTIVE:
                return None
            order = c.order
            lo, hi = self._bounds(c)
            cur = order.index(self.auto_tier) if self.auto_tier in order else lo
            if self.ceiling and now >= self.ceiling[1]:
                self.ceiling = None
            if self.cooldown > 0:
                self.cooldown -= 1
            bad = m.fail_rate > a.down_fail_rate or m.adb_latency_ms > a.adb_latency_bad_ms or m.render_ms > a.render_bad_ms
            good = m.fail_rate == 0 and m.adb_latency_ms <= a.adb_latency_ok_ms and m.render_ms <= a.render_ok_ms and load <= a.cpu_load_max
            if bad:
                self.clean_streak = 0
                if cur > lo:
                    self.ceiling = (order[cur], now + a.ceiling_hold_s)
                    self.auto_tier = order[cur - 1]
                    self.cooldown = a.cooldown_waves
                    return "down"
                return None
            if not good:
                self.clean_streak = 0
                return None
            self.clean_streak += 1
            if self.clean_streak < a.up_after_clean_waves or self.cooldown > 0 or cur >= hi:
                return None
            nxt = order[cur + 1]
            if self.ceiling and order.index(nxt) >= order.index(self.ceiling[0]):
                return None
            self.auto_tier = nxt
            self.clean_streak = 0
            self.cooldown = a.cooldown_waves
            return "up"
