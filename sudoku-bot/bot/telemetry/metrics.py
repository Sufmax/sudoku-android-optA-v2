"""Statistiques persistées (survivent aux redémarrages et à l'hibernation)."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bot.state.store import JsonStore


@dataclass
class Stats:
    games_started: int = 0
    games_won: int = 0
    games_failed: int = 0
    total_game_s: float = 0.0
    last_game_s: float = 0.0
    digits_placed: int = 0
    corrections: int = 0
    rereads: int = 0
    waves: int = 0
    failed_waves: int = 0
    errors: int = 0
    game_errors_red: int = 0
    total_runtime_s: float = 0.0
    first_seen: float = field(default_factory=time.time)

    def derived(self, session_start: float) -> dict:
        d = asdict(self)
        done = max(1, self.games_won)
        d["avg_game_s"] = round(self.total_game_s / done, 1) if self.games_won else 0.0
        d["avg_digit_s"] = round(self.total_game_s / max(1, self.digits_placed), 3) if self.digits_placed else 0.0
        d["wave_fail_rate"] = round(self.failed_waves / max(1, self.waves), 3)
        d["correction_rate"] = round(self.corrections / max(1, self.digits_placed), 3)
        d["uptime_s"] = round(time.time() - session_start, 1)
        return d


class StatsStore:
    def __init__(self, path: Path) -> None:
        self.store = JsonStore(path)
        raw = self.store.load()
        known = {k: v for k, v in raw.items() if k in Stats.__dataclass_fields__}
        self.stats = Stats(**known)
        self.session_start = time.time()
        self._last_flush = time.time()

    def flush(self) -> None:
        now = time.time()
        self.stats.total_runtime_s += now - self._last_flush
        self._last_flush = now
        self.store.save(asdict(self.stats))

    def snapshot(self) -> dict:
        return self.stats.derived(self.session_start)
