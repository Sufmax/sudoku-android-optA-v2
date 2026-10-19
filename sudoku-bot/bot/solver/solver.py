"""Solveur générique de Sudoku N×N à blocs R×C (N = R·C).

Bitmasks + heuristique MRV + propagation des singletons. Distingue clairement :
solution unique, solutions multiples, aucune solution, et dépassement de temps
(corrige le bug B5 de l'ancien projet où un timeout passait pour « insoluble »).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

Grid = list[list[int]]


class SolveStatus(str, Enum):
    UNIQUE = "unique"
    MULTIPLE = "multiple"
    NONE = "none"
    TIMEOUT = "timeout"
    INVALID = "invalid"


@dataclass
class SolveResult:
    status: SolveStatus
    solution: Grid | None
    nodes: int
    elapsed_s: float


def _check_shape(grid: Grid, box_rows: int, box_cols: int) -> int:
    n = len(grid)
    if n == 0 or any(len(row) != n for row in grid):
        raise ValueError("la grille doit être carrée et non vide")
    if box_rows * box_cols != n:
        raise ValueError(f"blocs {box_rows}x{box_cols} incompatibles avec N={n}")
    for row in grid:
        for v in row:
            if not 0 <= v <= n:
                raise ValueError(f"valeur {v} hors de [0, {n}]")
    return n


def box_index(r: int, c: int, n: int, box_rows: int, box_cols: int) -> int:
    """Index du bloc contenant (r, c) ; il y a n // box_cols blocs par rangée de blocs."""
    return (r // box_rows) * (n // box_cols) + (c // box_cols)


def find_conflicts(grid: Grid, box_rows: int, box_cols: int) -> set[tuple[int, int]]:
    """Cases participant à un doublon sur une ligne, une colonne ou un bloc."""
    n = _check_shape(grid, box_rows, box_cols)
    bad: set[tuple[int, int]] = set()
    groups: list[list[tuple[int, int]]] = []
    for i in range(n):
        groups.append([(i, c) for c in range(n)])
        groups.append([(r, i) for r in range(n)])
    for br in range(0, n, box_rows):
        for bc in range(0, n, box_cols):
            groups.append([(r, c) for r in range(br, br + box_rows) for c in range(bc, bc + box_cols)])
    for grp in groups:
        seen: dict[int, list[tuple[int, int]]] = {}
        for r, c in grp:
            v = grid[r][c]
            if v:
                seen.setdefault(v, []).append((r, c))
        for cells in seen.values():
            if len(cells) > 1:
                bad.update(cells)
    return bad


def is_complete_and_valid(grid: Grid, box_rows: int, box_cols: int) -> bool:
    n = _check_shape(grid, box_rows, box_cols)
    return all(v for row in grid for v in row) and not find_conflicts(grid, box_rows, box_cols) and n > 0


def candidates(grid: Grid, box_rows: int, box_cols: int) -> dict[tuple[int, int], int]:
    """Nombre de candidats de chaque case vide (utilisé pour l'ordre de saisie « humain »)."""
    n = _check_shape(grid, box_rows, box_cols)
    full = (1 << n) - 1
    rows, cols, boxes = [0] * n, [0] * n, [0] * n
    for r in range(n):
        for c in range(n):
            v = grid[r][c]
            if v:
                bit = 1 << (v - 1)
                rows[r] |= bit
                cols[c] |= bit
                boxes[box_index(r, c, n, box_rows, box_cols)] |= bit
    out: dict[tuple[int, int], int] = {}
    for r in range(n):
        for c in range(n):
            if not grid[r][c]:
                m = full & ~(rows[r] | cols[c] | boxes[box_index(r, c, n, box_rows, box_cols)])
                out[(r, c)] = bin(m).count("1")
    return out


class _Search:
    def __init__(self, grid: Grid, box_rows: int, box_cols: int, limit: int, deadline: float) -> None:
        self.n = len(grid)
        self.br, self.bc = box_rows, box_cols
        self.g = [row[:] for row in grid]
        self.full = (1 << self.n) - 1
        self.rows = [0] * self.n
        self.cols = [0] * self.n
        self.boxes = [0] * self.n
        self.limit = limit
        self.deadline = deadline
        self.solutions: list[Grid] = []
        self.nodes = 0
        self.timed_out = False

    def box(self, r: int, c: int) -> int:
        return box_index(r, c, self.n, self.br, self.bc)

    def init_masks(self) -> bool:
        for r in range(self.n):
            for c in range(self.n):
                v = self.g[r][c]
                if v:
                    bit = 1 << (v - 1)
                    b = self.box(r, c)
                    if (self.rows[r] | self.cols[c] | self.boxes[b]) & bit:
                        return False
                    self.rows[r] |= bit
                    self.cols[c] |= bit
                    self.boxes[b] |= bit
        return True

    def run(self, empties: list[tuple[int, int]]) -> None:
        """Recherche itérative-récursive (profondeur ≤ nombre de cases vides)."""
        if len(self.solutions) >= self.limit or self.timed_out:
            return
        self.nodes += 1
        if (self.nodes & 511) == 0 and time.monotonic() > self.deadline:
            self.timed_out = True
            return
        if not empties:
            self.solutions.append([row[:] for row in self.g])
            return
        best_i, best_mask, best_cnt = -1, 0, self.n + 1
        for i, (r, c) in enumerate(empties):
            m = self.full & ~(self.rows[r] | self.cols[c] | self.boxes[self.box(r, c)])
            cnt = bin(m).count("1")
            if cnt < best_cnt:
                best_i, best_mask, best_cnt = i, m, cnt
                if cnt <= 1:
                    break
        if best_cnt == 0:
            return
        r, c = empties[best_i]
        rest = empties[:best_i] + empties[best_i + 1:]
        b = self.box(r, c)
        m = best_mask
        while m:
            bit = m & -m
            m ^= bit
            self.g[r][c] = bit.bit_length()
            self.rows[r] |= bit
            self.cols[c] |= bit
            self.boxes[b] |= bit
            self.run(rest)
            self.rows[r] ^= bit
            self.cols[c] ^= bit
            self.boxes[b] ^= bit
            self.g[r][c] = 0
            if len(self.solutions) >= self.limit or self.timed_out:
                return


def solve(grid: Grid, box_rows: int, box_cols: int, timeout_s: float = 10.0) -> SolveResult:
    """Résout la grille et vérifie l'unicité (recherche limitée à 2 solutions)."""
    t0 = time.monotonic()
    n = _check_shape(grid, box_rows, box_cols)
    s = _Search(grid, box_rows, box_cols, limit=2, deadline=t0 + timeout_s)
    if not s.init_masks():
        return SolveResult(SolveStatus.INVALID, None, 0, time.monotonic() - t0)
    empties = [(r, c) for r in range(n) for c in range(n) if not grid[r][c]]
    s.run(empties)
    elapsed = time.monotonic() - t0
    if len(s.solutions) >= 2:
        return SolveResult(SolveStatus.MULTIPLE, s.solutions[0], s.nodes, elapsed)
    if s.timed_out:
        return SolveResult(SolveStatus.TIMEOUT, s.solutions[0] if s.solutions else None, s.nodes, elapsed)
    if s.solutions:
        return SolveResult(SolveStatus.UNIQUE, s.solutions[0], s.nodes, elapsed)
    return SolveResult(SolveStatus.NONE, None, s.nodes, elapsed)
