"""Déduction de la zone cliquable associée à un texte détecté, et cibles graphiques sans texte."""
from __future__ import annotations

import cv2
import numpy as np

from bot.models import Rect


def button_region(img: np.ndarray, text: Rect, color_tol: float = 28.0) -> tuple[Rect, float]:
    """Étend le rectangle du texte au bouton qui le contient (croissance de région de couleur).

    Renvoie (zone, confiance). Si le fond du texte est le fond de page (pas de bouton
    distinct), renvoie le texte légèrement agrandi avec une confiance moindre.
    """
    h, w = img.shape[:2]
    pad = max(4, int(text.h * 0.45))
    sx0, sy0 = max(0, int(text.x - pad)), max(0, int(text.y - pad))
    sx1, sy1 = min(w, int(text.x2 + pad)), min(h, int(text.y2 + pad))
    ring = np.concatenate([
        img[sy0:int(text.y), sx0:sx1].reshape(-1, 3),
        img[int(text.y2):sy1, sx0:sx1].reshape(-1, 3),
    ]) if sy1 > sy0 else img[sy0:sy1, sx0:sx1].reshape(-1, 3)
    padded = Rect(text.x - pad, text.y - pad, text.w + 2 * pad, text.h + 2 * pad)
    if ring.size == 0:
        return padded, 0.6
    bg = np.median(ring, axis=0).astype(np.float32)
    wy0 = max(0, int(text.y - text.h * 3))
    wy1 = min(h, int(text.y2 + text.h * 3))
    window = img[wy0:wy1, 0:w].astype(np.float32)
    mask = (np.linalg.norm(window - bg, axis=2) < color_tol).astype(np.uint8)
    seed_y = int(min(max(text.y - pad / 2 - wy0, 0), mask.shape[0] - 1))
    seed_x = int(min(max(text.cx, 0), w - 1))
    if not mask[seed_y, seed_x]:
        return padded, 0.6
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    lab = labels[seed_y, seed_x]
    x, y, bw, bh, _ = stats[lab]
    region = Rect(float(x), float(y + wy0), float(bw), float(bh))
    touches_band = y <= 0 or y + bh >= mask.shape[0]
    too_wide = bw >= w * 0.97
    if touches_band or too_wide or not region.contains(text.cx, text.cy):
        return padded, 0.65
    return region, 0.95


def blob_above_text(img: np.ndarray, text: Rect, delta: float = 40.0) -> Rect | None:
    """Plus grand objet graphique au-dessus d'un texte (ex. flamme « Touchez la flamme »)."""
    h, w = img.shape[:2]
    y1 = int(max(0, text.y - text.h * 0.5))
    y0 = int(max(0, text.y - max(text.w, text.h * 8)))
    x0 = int(max(0, text.x - text.w * 0.3))
    x1 = int(min(w, text.x2 + text.w * 0.3))
    roi = img[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    bg = np.median(np.concatenate([roi[:4].reshape(-1, 3), roi[:, :4].reshape(-1, 3)]), axis=0)
    mask = (np.linalg.norm(roi.astype(np.float32) - bg.astype(np.float32), axis=2) > delta).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        return None
    i = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    x, y, bw, bh, area = stats[i]
    if area < (text.h ** 2):
        return None
    return Rect(float(x0 + x), float(y0 + y), float(bw), float(bh))
