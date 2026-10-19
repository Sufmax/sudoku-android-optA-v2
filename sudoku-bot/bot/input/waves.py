"""Stratégie de saisie par vagues (logique pure, testable sans appareil).

- `plan_moves` : coups nécessaires pour amener la grille lue à la solution, sans JAMAIS
  toucher un chiffre initial ;
- `next_wave` : prochaine vague, COUPÉE juste après un coup qui complète un chiffre
  (le jeu retire alors la touche de ce chiffre ; dans l'application cible les autres touches
  gardent leur place, mais d'autres jeux recentrent le pavé : garde-fou paramétrable) ;
- `evaluate_wave` : comparaison attendu / relu → ok, manquants, faux, erreurs ;
- `WaveSizer` : réduction/augmentation dynamique de la taille de vague.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from bot.models import CellKind, GridRead, Move

Grid = list[list[int]]


class GivenMismatchError(ValueError):
    """Un chiffre initial lu contredit la solution : lecture à refaire, aucune action."""


def plan_moves(read: GridRead, solution: Grid) -> list[Move]:
    moves: list[Move] = []
    for r, row in enumerate(read.cells):
        for c, cell in enumerate(row):
            target = solution[r][c]
            if cell.kind == CellKind.GIVEN:
                if cell.value != target:
                    raise GivenMismatchError(f"case donnée ({r},{c}) lue {cell.value}, solution {target}")
                continue
            if cell.kind == CellKind.USER and cell.value == target:
                continue
            moves.append(Move(r, c, target))
    return moves


def correct_counts(read: GridRead, solution: Grid) -> dict[int, int]:
    """Nombre d'occurrences correctes de chaque chiffre actuellement sur la grille."""
    n = len(solution)
    counts = {d: 0 for d in range(1, n + 1)}
    for r, row in enumerate(read.cells):
        for c, cell in enumerate(row):
            if cell.value and cell.value == solution[r][c] and cell.kind in (CellKind.GIVEN, CellKind.USER):
                counts[cell.value] += 1
    return counts


def order_moves(moves: list[Move], mode: str, box_rows: int, box_cols: int, cand: dict[tuple[int, int], int] | None, rng: random.Random) -> list[Move]:
    mv = list(moves)
    if mode == "rows":
        return sorted(mv, key=lambda m: (m.r, m.c))
    if mode == "random":
        rng.shuffle(mv)
        return mv
    if mode == "digit":
        rng.shuffle(mv)
        return sorted(mv, key=lambda m: m.v)
    if mode == "box":
        return sorted(mv, key=lambda m: (m.r // box_rows, m.c // box_cols, rng.random()))
    cc = cand or {}
    out: list[Move] = []
    cur: Move | None = None
    remaining = mv
    while remaining:
        def score(m: Move) -> float:
            s = float(cc.get((m.r, m.c), 3))
            if cur is not None:
                s -= 1.2 if m.v == cur.v else 0.0
                s -= 0.8 if (m.r // box_rows == cur.r // box_rows and m.c // box_cols == cur.c // box_cols) else 0.0
                s -= 0.4 if (m.r == cur.r or m.c == cur.c) else 0.0
                s += 0.08 * (abs(m.r - cur.r) + abs(m.c - cur.c))
            return s + rng.uniform(0.0, 1.1)
        nxt = min(remaining, key=score)
        remaining = [m for m in remaining if m is not nxt]
        out.append(nxt)
        cur = nxt
    return out


def next_wave(queue: list[Move], counts: dict[int, int], n: int, size: int, available: set[int], cut_on_complete: bool = True) -> list[Move]:
    """Sélectionne la prochaine vague dans `queue` (sans la modifier)."""
    sim = dict(counts)
    wave: list[Move] = []
    for m in queue:
        if len(wave) >= size:
            break
        if m.v not in available:
            continue
        wave.append(m)
        sim[m.v] = sim.get(m.v, 0) + 1
        if cut_on_complete and sim[m.v] >= n:
            break  # le pavé va changer : on recapture avant de continuer
    return wave


@dataclass
class WaveResult:
    ok: list[Move] = field(default_factory=list)
    missing: list[Move] = field(default_factory=list)
    wrong: list[Move] = field(default_factory=list)
    errors: list[Move] = field(default_factory=list)
    givens_changed: bool = False

    @property
    def total(self) -> int:
        return len(self.ok) + len(self.missing) + len(self.wrong) + len(self.errors)

    @property
    def fail_rate(self) -> float:
        return 0.0 if self.total == 0 else 1.0 - len(self.ok) / self.total


def evaluate_wave(wave: list[Move], before: GridRead, after: GridRead) -> WaveResult:
    res = WaveResult()
    for r, row in enumerate(before.cells):
        for c, cell in enumerate(row):
            if cell.kind == CellKind.GIVEN and (after.cells[r][c].kind != CellKind.GIVEN or after.cells[r][c].value != cell.value):
                res.givens_changed = True
    for m in wave:
        cell = after.cells[m.r][m.c]
        if cell.kind == CellKind.ERROR:
            res.errors.append(m)
        elif cell.kind == CellKind.EMPTY or cell.value == 0:
            res.missing.append(m)
        elif cell.value == m.v and cell.kind == CellKind.USER:
            res.ok.append(m)
        else:
            res.wrong.append(m)
    return res


class WaveSizer:
    def __init__(self, min_wave: int, fail_rate_shrink: float, shrink_factor: float, grow_factor: float, clean_to_grow: int) -> None:
        self.min_wave = max(1, min_wave)
        self.fail_rate_shrink = fail_rate_shrink
        self.shrink_factor = shrink_factor
        self.grow_factor = grow_factor
        self.clean_to_grow = clean_to_grow
        self.factor = 1.0
        self.clean = 0

    def size(self, base: int) -> int:
        return max(self.min_wave, int(round(base * self.factor)))

    def update(self, result: WaveResult) -> None:
        if result.total == 0:
            return
        if result.fail_rate > self.fail_rate_shrink:
            self.factor = max(0.05, self.factor * self.shrink_factor)
            self.clean = 0
        elif result.fail_rate == 0:
            self.clean += 1
            if self.clean >= self.clean_to_grow:
                self.factor = min(1.0, self.factor * self.grow_factor)
                self.clean = 0
