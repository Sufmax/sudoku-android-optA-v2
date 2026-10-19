"""Exécution physique d'une vague via ADB, avec rythme humain et point d'arrêt entre coups."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from bot.adb.client import AdbClient
from bot.adb.humanize import Humanizer
from bot.config import SpeedTier
from bot.models import GridGeometry, KeypadRead, Move, Rect

log = logging.getLogger("bot.input")


class KeyMissingError(RuntimeError):
    """La touche du chiffre demandé n'est pas visible sur le pavé détecté."""


async def tap(adb: AdbClient, human: Humanizer, rect: Rect) -> None:
    plan = human.touch(rect)
    await adb.swipe(plan.x1, plan.y1, plan.x2, plan.y2, plan.duration_ms)


async def execute_wave(
    adb: AdbClient,
    human: Humanizer,
    tier: SpeedTier,
    wave: list[Move],
    geo: GridGeometry,
    keypad: KeypadRead,
    checkpoint: Callable[[], Awaitable[None]],
    erase_rect: Rect | None = None,
    overwrite_cells: set[tuple[int, int]] | None = None,
) -> int:
    """Joue la vague ; renvoie le nombre de coups réellement exécutés.

    `checkpoint` est attendu entre deux coups (jamais au milieu d'un coup) : c'est là que
    la pause demandée depuis le dashboard prend effet.
    """
    done = 0
    for m in wave:
        key = keypad.keys.get(m.v)
        if key is None:
            raise KeyMissingError(f"chiffre {m.v} absent du pavé")
        await checkpoint()
        cell = geo.cell_rect(m.r, m.c)
        await tap(adb, human, cell)
        await asyncio.sleep(human.delay_ms(tier.cell_to_key_ms, tier.jitter_frac) / 1000)
        if erase_rect is not None and overwrite_cells and (m.r, m.c) in overwrite_cells:
            await tap(adb, human, erase_rect)
            await asyncio.sleep(human.delay_ms(tier.cell_to_key_ms, tier.jitter_frac) / 1000)
        await tap(adb, human, key.rect)
        done += 1
        pause = human.delay_ms(tier.between_moves_ms, tier.jitter_frac) + human.extra_pause_ms()
        await asyncio.sleep(pause / 1000)
    return done
