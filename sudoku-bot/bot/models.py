"""Modèles de données partagés entre les modules (purs, sans dépendance externe)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class Rect:
    """Rectangle en pixels de la capture courante (x, y = coin haut-gauche)."""

    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x2 and self.y <= py <= self.y2

    def to_list(self) -> list[float]:
        return [round(self.x, 1), round(self.y, 1), round(self.w, 1), round(self.h, 1)]


class CellKind(str, Enum):
    EMPTY = "empty"
    GIVEN = "given"      # chiffre initial du jeu (noir) — jamais modifié
    USER = "user"        # chiffre saisi (bleu)
    ERROR = "error"      # chiffre refusé par le jeu (rouge)
    UNKNOWN = "unknown"  # encre présente mais non classée


@dataclass(frozen=True)
class CellRead:
    value: int
    kind: CellKind
    confidence: float


@dataclass(frozen=True)
class GridGeometry:
    rect: Rect
    n: int
    box_rows: int
    box_cols: int
    xs: tuple[float, ...]   # n+1 positions de lignes verticales
    ys: tuple[float, ...]   # n+1 positions de lignes horizontales
    confidence: float
    blocks_from_fallback: bool = False

    def cell_rect(self, r: int, c: int) -> Rect:
        return Rect(self.xs[c], self.ys[r], self.xs[c + 1] - self.xs[c], self.ys[r + 1] - self.ys[r])

    @property
    def cell_h(self) -> float:
        return self.rect.h / self.n


@dataclass
class GridRead:
    geometry: GridGeometry
    cells: list[list[CellRead]]

    def values(self) -> list[list[int]]:
        return [[c.value for c in row] for row in self.cells]

    def givens(self) -> list[list[int]]:
        return [[c.value if c.kind == CellKind.GIVEN else 0 for c in row] for row in self.cells]

    @property
    def min_confidence(self) -> float:
        return min((c.confidence for row in self.cells for c in row), default=0.0)


@dataclass(frozen=True)
class KeyRead:
    digit: int
    rect: Rect
    confidence: float


@dataclass
class KeypadRead:
    keys: dict[int, KeyRead]
    confidence: float
    labelled_by: str  # "order" | "templates"


class ScreenKind(str, Enum):
    GAME = "game"
    LOADING = "loading"
    OVERLAY = "overlay"
    RULE = "rule"        # écran reconnu par une règle OCR (menu, pop-up…)
    UNKNOWN = "unknown"


@dataclass
class TextHit:
    text: str
    rect: Rect
    score: float


@dataclass
class ScreenObservation:
    kind: ScreenKind
    confidence: float
    rule_id: Optional[str] = None
    grid: Optional[GridRead] = None
    keypad: Optional[KeypadRead] = None
    texts: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass(frozen=True)
class Move:
    r: int
    c: int
    v: int
