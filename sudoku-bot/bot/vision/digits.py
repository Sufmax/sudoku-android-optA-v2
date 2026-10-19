"""Lecture de toutes les cases d'une grille : vide / donnée / saisie / erreur + valeur + confiance."""
from __future__ import annotations

import numpy as np

from bot.config import DetectionCfg
from bot.models import CellKind, CellRead, GridGeometry, GridRead
from bot.vision.glyphs import TemplateBank, classify_color, main_glyph


def read_cell(img: np.ndarray, geo: GridGeometry, r: int, c: int, bank: TemplateBank, cfg: DetectionCfg) -> CellRead:
    rect = geo.cell_rect(r, c)
    inset = cfg.cells.inset_frac
    x0 = int(rect.x + rect.w * inset)
    y0 = int(rect.y + rect.h * inset)
    x1 = int(rect.x2 - rect.w * inset)
    y1 = int(rect.y2 - rect.h * inset)
    patch = img[y0:y1, x0:x1]
    if patch.size == 0:
        return CellRead(0, CellKind.UNKNOWN, 0.0)
    rel = (y1 - y0)
    glyph = main_glyph(patch, cfg.cells.ink_delta, cfg.cells.min_glyph_h_frac * rect.h / rel, cfg.cells.max_glyph_h_frac * rect.h / rel)
    if glyph is None:
        # Case vide : confiance d'autant plus forte qu'il y a peu d'encre résiduelle
        return CellRead(0, CellKind.EMPTY, 0.95)
    kind = classify_color(glyph.mean_bgr, cfg.colors)
    sym, score, margin = bank.match(glyph.mask, allowed=set(range(1, geo.n + 1)))
    if sym == 0:
        return CellRead(0, CellKind.UNKNOWN, 0.0)
    conf_score = (score - cfg.cells.digit_min_score) / max(1e-6, 1.0 - cfg.cells.digit_min_score)
    conf_margin = margin / max(1e-6, cfg.cells.digit_min_margin * 3)
    conf = float(np.clip(0.5 + 0.5 * min(conf_score, conf_margin), 0.0, 1.0))
    if score < cfg.cells.digit_min_score or margin < cfg.cells.digit_min_margin:
        conf = min(conf, 0.4)
    if kind == CellKind.UNKNOWN:
        conf = min(conf, 0.5)
    return CellRead(sym, kind, round(conf, 4))


def read_grid(img: np.ndarray, geo: GridGeometry, bank: TemplateBank, cfg: DetectionCfg) -> GridRead:
    cells = [[read_cell(img, geo, r, c, bank, cfg) for c in range(geo.n)] for r in range(geo.n)]
    return GridRead(geometry=geo, cells=cells)


def grid_background_value(img: np.ndarray, geo: GridGeometry) -> float:
    """Luminosité médiane (canal V) de la grille : faible si un voile modal la recouvre."""
    r = geo.rect
    roi = img[int(r.y):int(r.y2), int(r.x):int(r.x2)]
    return float(np.median(roi.max(axis=2)))
