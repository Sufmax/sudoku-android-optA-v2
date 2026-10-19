"""Machine à états du bot : états, transitions autorisées, historique.

Principe de sûreté : aucun état n'autorise une action sans passer par OBSERVE (capture
fraîche). Au redémarrage, l'état persisté n'est qu'un indice : on repart de BOOT.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class BotState(str, Enum):
    BOOT = "boot"
    WAIT_DEVICE = "wait_device"
    WAIT_READY = "wait_ready"
    OBSERVE = "observe"
    NAVIGATE = "navigate"      # menus, pop-ups, publicités (règles OCR)
    LOADING = "loading"        # message transitoire avant la grille
    SOLVING = "solving"
    GAME_OVER = "game_over"
    RECOVERING = "recovering"
    PAUSED = "paused"
    STOPPING = "stopping"


_ANY_RUNNING = {BotState.OBSERVE, BotState.NAVIGATE, BotState.LOADING, BotState.SOLVING, BotState.GAME_OVER, BotState.RECOVERING}

ALLOWED: dict[BotState, set[BotState]] = {
    BotState.BOOT: {BotState.WAIT_DEVICE, BotState.STOPPING},
    BotState.WAIT_DEVICE: {BotState.WAIT_READY, BotState.OBSERVE, BotState.RECOVERING, BotState.STOPPING},
    BotState.WAIT_READY: {BotState.OBSERVE, BotState.WAIT_DEVICE, BotState.STOPPING},
    BotState.OBSERVE: _ANY_RUNNING | {BotState.PAUSED, BotState.WAIT_DEVICE, BotState.STOPPING, BotState.WAIT_READY},
    BotState.NAVIGATE: {BotState.OBSERVE, BotState.PAUSED, BotState.RECOVERING, BotState.WAIT_DEVICE, BotState.STOPPING},
    BotState.LOADING: {BotState.OBSERVE, BotState.PAUSED, BotState.WAIT_DEVICE, BotState.STOPPING},
    BotState.SOLVING: {BotState.OBSERVE, BotState.PAUSED, BotState.RECOVERING, BotState.WAIT_DEVICE, BotState.STOPPING},
    BotState.GAME_OVER: {BotState.OBSERVE, BotState.NAVIGATE, BotState.PAUSED, BotState.WAIT_DEVICE, BotState.STOPPING},
    BotState.RECOVERING: {BotState.OBSERVE, BotState.WAIT_DEVICE, BotState.PAUSED, BotState.STOPPING},
    BotState.PAUSED: {BotState.OBSERVE, BotState.WAIT_DEVICE, BotState.STOPPING},
    BotState.STOPPING: set(),
}


class IllegalTransition(RuntimeError):
    pass


@dataclass
class Transition:
    at: float
    src: BotState
    dst: BotState
    reason: str


class StateMachine:
    def __init__(self, on_change: Callable[[Transition], None] | None = None) -> None:
        self.state = BotState.BOOT
        self.since = time.time()
        self.history: list[Transition] = []
        self.on_change = on_change

    def can(self, dst: BotState) -> bool:
        return dst == self.state or dst in ALLOWED[self.state]

    def go(self, dst: BotState, reason: str = "") -> None:
        if dst == self.state:
            return
        if dst not in ALLOWED[self.state]:
            raise IllegalTransition(f"{self.state.value} → {dst.value} interdit ({reason})")
        tr = Transition(time.time(), self.state, dst, reason)
        self.state = dst
        self.since = tr.at
        self.history.append(tr)
        self.history = self.history[-100:]
        if self.on_change:
            self.on_change(tr)
