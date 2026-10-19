"""Extraction de glyphes (encre) et banque de gabarits de chiffres apprise visuellement."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from bot.config import ColorsCfg
from bot.models import CellKind


@dataclass
class Glyph:
    mask: np.ndarray          # masque binaire recadré (uint8 0/255)
    bbox: tuple[int, int, int, int]  # x, y, w, h dans le patch
    mean_bgr: tuple[float, float, float]
    ink_ratio: float


def ink_mask(patch: np.ndarray, delta: float, bg: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Masque des pixels s'écartant du fond (fond = médiane de l'anneau extérieur du patch)."""
    if bg is None:
        h, w = patch.shape[:2]
        b = max(1, min(h, w) // 10)
        ring = np.concatenate([patch[:b].reshape(-1, 3), patch[-b:].reshape(-1, 3), patch[:, :b].reshape(-1, 3), patch[:, -b:].reshape(-1, 3)])
        bg = np.median(ring, axis=0)
    dist = np.linalg.norm(patch.astype(np.float32) - bg.astype(np.float32), axis=2)
    return (dist > delta).astype(np.uint8) * 255, bg


def main_glyph(patch: np.ndarray, delta: float, min_h: float, max_h: float) -> Glyph | None:
    """Plus grand glyphe central dont la hauteur relative est dans [min_h, max_h]."""
    h, w = patch.shape[:2]
    mask, _ = ink_mask(patch, delta)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best_i, best_area = -1, 0
    for i in range(1, num):
        x, y, bw, bh, area = stats[i]
        if bh < min_h * h or bh > max_h * h or area < 6:
            continue
        cx = x + bw / 2.0
        if abs(cx - w / 2.0) > w * 0.35:
            continue
        if area > best_area:
            best_i, best_area = i, int(area)
    if best_i < 0:
        return None
    x, y, bw, bh, _ = stats[best_i]
    # Fusion des composantes voisines alignées (chiffres en plusieurs morceaux, ex. « 10 »)
    sel = labels == best_i
    for i in range(1, num):
        if i == best_i:
            continue
        xi, yi, wi, hi, ai = stats[i]
        if ai >= 6 and hi >= 0.5 * bh and yi < y + bh and yi + hi > y and abs((xi + wi / 2) - (x + bw / 2)) < w * 0.4:
            sel |= labels == i
    ys, xs = np.nonzero(sel)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    crop = (sel[y0:y1, x0:x1].astype(np.uint8)) * 255
    mean = patch[sel].reshape(-1, 3).mean(axis=0)
    return Glyph(crop, (x0, y0, x1 - x0, y1 - y0), (float(mean[0]), float(mean[1]), float(mean[2])), float(sel.mean()))


def classify_color(mean_bgr: tuple[float, float, float], cfg: ColorsCfg) -> CellKind:
    px = np.uint8([[list(mean_bgr)]])
    hh, ss, vv = (int(v) for v in cv2.cvtColor(px, cv2.COLOR_BGR2HSV)[0, 0])
    if ss >= cfg.error_min_sat and vv >= cfg.error_min_val and any(lo <= hh <= hi for lo, hi in cfg.error_hue):
        return CellKind.ERROR
    if ss >= cfg.user_min_sat and cfg.user_hue[0] <= hh <= cfg.user_hue[1]:
        return CellKind.USER
    if vv <= cfg.given_max_val and ss <= cfg.given_max_sat:
        return CellKind.GIVEN
    return CellKind.UNKNOWN


def normalize(mask: np.ndarray, size: int) -> np.ndarray:
    """Glyphe centré dans un carré size×size, vecteur à moyenne nulle et norme 1."""
    h, w = mask.shape
    side = max(h, w)
    canvas = np.zeros((side, side), np.uint8)
    canvas[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = mask
    inner = max(4, int(size * 0.84))
    small = cv2.resize(canvas, (inner, inner), interpolation=cv2.INTER_AREA)
    out = np.zeros((size, size), np.float32)
    o = (size - inner) // 2
    out[o:o + inner, o:o + inner] = small.astype(np.float32) / 255.0
    out = cv2.GaussianBlur(out, (3, 3), 0)
    out -= out.mean()
    norm = float(np.linalg.norm(out))
    return out / norm if norm > 1e-6 else out


class TemplateBank:
    """Gabarits de chiffres appris depuis le pavé du jeu, persistés sur disque."""

    def __init__(self, size: int, per_symbol: int, path: Path | None = None) -> None:
        self.size = size
        self.per_symbol = per_symbol
        self.path = path
        self._lock = threading.Lock()
        self._t: dict[int, list[np.ndarray]] = {}
        if path is not None and path.exists():
            self.load()

    def __len__(self) -> int:
        return sum(len(v) for v in self._t.values())

    def symbols(self) -> list[int]:
        return sorted(self._t)

    def add(self, symbol: int, mask: np.ndarray) -> None:
        vec = normalize(mask, self.size)
        with self._lock:
            lst = self._t.setdefault(symbol, [])
            if any(float((vec * t).sum()) > 0.985 for t in lst):
                return  # quasi-doublon : inutile
            lst.append(vec)
            if len(lst) > self.per_symbol:
                lst.pop(0)

    def match(self, mask: np.ndarray, allowed: set[int] | None = None) -> tuple[int, float, float]:
        """(symbole, score, marge avec le 2e meilleur symbole). Symbole 0 si banque vide."""
        vec = normalize(mask, self.size)
        scores: dict[int, float] = {}
        with self._lock:
            for sym, lst in self._t.items():
                if allowed is not None and sym not in allowed:
                    continue
                scores[sym] = max(float((vec * t).sum()) for t in lst)
        if not scores:
            return 0, 0.0, 0.0
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_sym, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        return best_sym, best, best - second

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            arrays = {f"s{sym}_{i}": t for sym, lst in self._t.items() for i, t in enumerate(lst)}
        tmp = self.path.with_name(self.path.stem + ".tmp.npz")
        np.savez_compressed(tmp, **arrays)
        tmp.replace(self.path)

    def load(self) -> None:
        if self.path is None:
            return
        data = np.load(self.path)
        with self._lock:
            self._t.clear()
            for key in data.files:
                sym = int(key[1:].split("_")[0])
                arr = data[key]
                if arr.shape == (self.size, self.size):
                    self._t.setdefault(sym, []).append(arr.astype(np.float32))
