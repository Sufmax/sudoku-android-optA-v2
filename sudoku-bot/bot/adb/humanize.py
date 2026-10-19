"""Humanisation des appuis : point de contact, durée, micro-glissement, rythme et pauses.

Corrige le bug B6 : le biais droitier est appliqué AVANT le bornage, le point final reste
toujours dans la borne `tap_max_frac` de la cible.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from bot.config import HumanCfg
from bot.models import Rect


@dataclass(frozen=True)
class TouchPlan:
    x1: float
    y1: float
    x2: float
    y2: float
    duration_ms: int


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class Humanizer:
    def __init__(self, cfg: HumanCfg, rng: random.Random | None = None) -> None:
        self.cfg = cfg
        self.rng = rng or random.Random()

    def point_in(self, rect: Rect) -> tuple[float, float]:
        c = self.cfg
        bx = c.handedness_bias[0] * rect.w
        by = c.handedness_bias[1] * rect.h
        dx = self.rng.gauss(bx, c.tap_sigma_frac * rect.w)
        dy = self.rng.gauss(by, c.tap_sigma_frac * rect.h)
        dx = _clip(dx, -c.tap_max_frac * rect.w, c.tap_max_frac * rect.w)
        dy = _clip(dy, -c.tap_max_frac * rect.h, c.tap_max_frac * rect.h)
        return rect.cx + dx, rect.cy + dy

    def press_ms(self) -> int:
        lo, hi = self.cfg.press_ms
        u = self.rng.random() ** 1.6  # asymétrique : appuis plutôt courts, parfois plus longs
        return int(lo + (hi - lo) * u)

    def touch(self, rect: Rect) -> TouchPlan:
        x, y = self.point_in(rect)
        x2, y2 = x, y
        if self.rng.random() < self.cfg.micro_swipe_prob:
            amp = self.cfg.micro_swipe_frac
            lim_x = self.cfg.tap_max_frac * rect.w
            lim_y = self.cfg.tap_max_frac * rect.h
            x2 = _clip(x + self.rng.uniform(-amp, amp) * rect.w, rect.cx - lim_x, rect.cx + lim_x)
            y2 = _clip(y + self.rng.uniform(-amp, amp) * rect.h, rect.cy - lim_y, rect.cy + lim_y)
        return TouchPlan(x, y, x2, y2, self.press_ms())

    def delay_ms(self, pair: tuple[float, float], jitter_frac: float = 0.0, floor: int = 15) -> int:
        mean, sd = pair
        v = self.rng.gauss(mean, sd)
        v = _clip(v, mean * 0.35, mean * 2.6)
        if jitter_frac > 0:
            v *= 1.0 + self.rng.uniform(-jitter_frac, jitter_frac)
        return max(floor, int(v))

    def extra_pause_ms(self) -> int:
        """Hésitation occasionnelle ou pause longue (0 la plupart du temps)."""
        c = self.cfg
        r = self.rng.random()
        if r < c.long_pause_prob:
            return int(self.rng.uniform(*c.long_pause_ms))
        if r < c.long_pause_prob + c.hesitation_prob:
            return int(self.rng.uniform(*c.hesitation_ms))
        return 0
