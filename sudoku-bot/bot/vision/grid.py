"""Détection de la grille et déduction de sa géométrie (N, blocs R×C) à partir de l'image seule.

Méthode :
1. seuillage adaptatif inverse + ouverture morphologique par noyaux longs → masques de lignes ;
2. plus grand contour quasi carré → boîte englobante ;
3. profils de couverture → on retient le plus grand N dont TOUTES les lignes attendues existent ;
4. épaisseur/noirceur des lignes internes → séparation fines/épaisses → R et C.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from bot.config import GridCfg
from bot.models import GridGeometry, Rect


@dataclass
class _Peak:
    start: int
    end: int

    @property
    def center(self) -> float:
        return (self.start + self.end) / 2.0


def _line_masks(gray: np.ndarray, cfg: GridCfg) -> tuple[np.ndarray, np.ndarray]:
    h, w = gray.shape
    block = max(3, int(w * cfg.adaptive_block_frac) | 1)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, cfg.adaptive_c)
    k = max(15, int(w * cfg.line_kernel_frac))
    hmask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    vmask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    return hmask, vmask


def _peaks(profile: np.ndarray, thr: float) -> list[_Peak]:
    idx = np.flatnonzero(profile >= thr)
    peaks: list[_Peak] = []
    if idx.size == 0:
        return peaks
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev > 2:
            peaks.append(_Peak(start, prev))
            start = i
        prev = i
    peaks.append(_Peak(start, prev))
    return peaks


def _match_lattice(peaks: list[_Peak], length: float, n: int, tol: float) -> list[float] | None:
    """Positions réelles des n+1 lignes si chacune est trouvée près de sa position attendue."""
    step = length / n
    out: list[float] = []
    for i in range(n + 1):
        exp = i * step
        best = min(peaks, key=lambda p: abs(p.center - exp), default=None)
        if best is None or abs(best.center - exp) > tol * step:
            return None
        out.append(best.center)
    return out


def _line_strengths(gray: np.ndarray, rect: tuple[int, int, int, int], pos: list[float], horizontal: bool, cell: float) -> list[float]:
    """Noirceur intégrée de chaque ligne (médiane le long de la ligne → robuste aux chiffres)."""
    x0, y0, bw, bh = rect
    half = max(2, int(cell * 0.12))
    out: list[float] = []
    for p in pos:
        if horizontal:
            yc = int(round(y0 + p))
            strip = gray[max(0, yc - half): yc + half + 1, x0 + int(cell * 0.2): x0 + bw - int(cell * 0.2)]
            prof = 255.0 - np.median(strip, axis=1)
        else:
            xc = int(round(x0 + p))
            strip = gray[y0 + int(cell * 0.2): y0 + bh - int(cell * 0.2), max(0, xc - half): xc + half + 1]
            prof = 255.0 - np.median(strip, axis=0)
        base = float(np.percentile(prof, 10))
        out.append(float(np.clip(prof - base, 0, None).sum()))
    return out


def _block_step(strengths: list[float], n: int, ratio_min: float) -> tuple[int | None, float]:
    """Pas des lignes épaisses parmi les lignes internes (indices 1..n-1), avec un score de netteté."""
    internal = strengths[1:-1]
    if len(internal) < 1:
        return None, 0.0
    order = sorted(internal)
    best_ratio, split = 0.0, None
    for i in range(len(order) - 1):
        lo, hi = order[i], order[i + 1]
        r = hi / max(lo, 1e-6)
        if r > best_ratio:
            best_ratio, split = r, (lo + hi) / 2.0
    if split is None or best_ratio < ratio_min:
        return None, best_ratio
    thick = [i + 1 for i, s in enumerate(internal) if s > split]
    if not thick:
        return None, best_ratio
    step = thick[0]
    for t in thick:
        step = math.gcd(step, t)
    expected = list(range(step, n, step))
    if thick != expected or n % step != 0 or step == n:
        return None, best_ratio
    return step, best_ratio


def detect_grid(img: np.ndarray, cfg: GridCfg) -> GridGeometry | None:
    """Renvoie la géométrie de la grille ou None si aucune grille fiable n'est visible."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    hmask, vmask = _line_masks(gray, cfg)
    both = cv2.dilate(cv2.bitwise_or(hmask, vmask), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(both, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[int, int, int, int]] = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < cfg.min_width_frac * w or bh < cfg.min_width_frac * w * 0.8:
            continue
        if abs(1.0 - bw / float(bh)) > cfg.squareness_tol:
            continue
        candidates.append((x, y, bw, bh))
    candidates.sort(key=lambda r: r[2] * r[3], reverse=True)
    for (x, y, bw, bh) in candidates:
        geo = _analyse_box(gray, hmask, vmask, (x, y, bw, bh), cfg)
        if geo is not None:
            return geo
    return None


def _analyse_box(gray: np.ndarray, hmask: np.ndarray, vmask: np.ndarray, rect: tuple[int, int, int, int], cfg: GridCfg) -> GridGeometry | None:
    x, y, bw, bh = rect
    hprof = hmask[y: y + bh, x: x + bw].astype(np.float32).sum(axis=1) / 255.0 / bw
    vprof = vmask[y: y + bh, x: x + bw].astype(np.float32).sum(axis=0) / 255.0 / bh
    hpk = _peaks(hprof, cfg.line_coverage_min)
    vpk = _peaks(vprof, cfg.line_coverage_min)
    best: tuple[int, list[float], list[float]] | None = None
    for n in sorted(set(cfg.sizes)):
        ys = _match_lattice(hpk, bh - 1, n, cfg.lattice_tol)
        xs = _match_lattice(vpk, bw - 1, n, cfg.lattice_tol)
        if ys is not None and xs is not None:
            best = (n, xs, ys)  # on garde le plus grand N entièrement validé
    if best is None:
        return None
    n, xs, ys = best
    cell = bw / n
    reg = []
    for pos in (xs, ys):
        d = np.diff(pos)
        reg.append(1.0 - float(np.std(d) / max(np.mean(d), 1e-6)))
    regularity = max(0.0, min(reg))
    hs = _line_strengths(gray, rect, ys, True, cell)
    vs = _line_strengths(gray, rect, xs, False, cell)
    step_r, ratio_r = _block_step(hs, n, cfg.thick_ratio_min)
    step_c, ratio_c = _block_step(vs, n, cfg.thick_ratio_min)
    fallback = False
    if step_r is None or step_c is None or step_r * step_c != n:
        fb = cfg.block_fallback.get(str(n))
        if fb is None:
            return None
        step_r, step_c = int(fb[0]), int(fb[1])
        fallback = True
    conf = regularity * (0.75 if fallback else 1.0)
    return GridGeometry(
        rect=Rect(float(x), float(y), float(bw), float(bh)),
        n=n,
        box_rows=step_r,
        box_cols=step_c,
        xs=tuple(float(x + v) for v in xs),
        ys=tuple(float(y + v) for v in ys),
        confidence=round(conf, 4),
        blocks_from_fallback=fallback,
    )
