"""Détection du pavé numérique sous la grille et étiquetage de chaque touche.

Le jeu retire la touche d'un chiffre complété (les autres gardent leur place dans l'application
cible, mais rien n'est supposé) : le pavé est RE-DÉTECTÉ à chaque vague, et l'étiquetage par
rang n'est utilisé que si les N chiffres sont présents (sinon : gabarits appris).
"""
from __future__ import annotations

import cv2
import numpy as np

from bot.config import DetectionCfg
from bot.models import GridGeometry, KeypadRead, KeyRead, Rect
from bot.vision.glyphs import TemplateBank


def _components(img: np.ndarray, geo: GridGeometry, cfg: DetectionCfg) -> list[tuple[int, int, int, int, np.ndarray]]:
    h, w = img.shape[:2]
    top = int(min(h - 1, geo.rect.y2 + geo.cell_h * 0.15))
    region = img[top:h]
    if region.size == 0:
        return []
    bg = np.median(region.reshape(-1, 3), axis=0)
    dist = np.linalg.norm(region.astype(np.float32) - bg.astype(np.float32), axis=2)
    mask = (dist > cfg.cells.ink_delta).astype(np.uint8)
    if cfg.keypad.ink == "colored":
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        mask &= (hsv[..., 1] >= cfg.colors.user_min_sat).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask * 255, connectivity=8)
    out = []
    ch = geo.cell_h
    for i in range(1, num):
        x, y, bw, bh, area = stats[i]
        if not (cfg.keypad.min_h_frac * ch <= bh <= cfg.keypad.max_h_frac * ch):
            continue
        if not (0.12 <= bw / float(bh) <= 1.1) or area < 10:
            continue
        crop = (labels[y:y + bh, x:x + bw] == i).astype(np.uint8) * 255
        out.append((int(x), int(y + top), int(bw), int(bh), crop))
    return out


def _rows(comps: list, tol_frac: float) -> list[list]:
    comps = sorted(comps, key=lambda c: c[1] + c[3] / 2)
    rows: list[list] = []
    for c in comps:
        cy = c[1] + c[3] / 2
        if rows:
            last = rows[-1]
            ly = np.mean([k[1] + k[3] / 2 for k in last])
            lh = np.mean([k[3] for k in last])
            if abs(cy - ly) <= tol_frac * lh and abs(c[3] - lh) <= 0.35 * lh:
                last.append(c)
                continue
        rows.append([c])
    return [sorted(r, key=lambda k: k[0]) for r in rows]


def _regular(row: list, tol: float) -> bool:
    if len(row) < 3:
        return True
    centers = [k[0] + k[2] / 2 for k in row]
    d = np.diff(centers)
    return float(np.std(d) / max(np.mean(d), 1e-6)) <= tol


def detect_keypad(img: np.ndarray, geo: GridGeometry, bank: TemplateBank, cfg: DetectionCfg, learn: bool = True) -> KeypadRead | None:
    n = geo.n
    rows = [r for r in _rows(_components(img, geo, cfg), cfg.keypad.row_tol_frac) if 1 <= len(r) <= n]
    if not rows:
        return None
    best: KeypadRead | None = None
    best_score = -1.0
    for row in rows:
        if not _regular(row, cfg.keypad.regularity_tol):
            continue
        centers = [k[0] + k[2] / 2 for k in row]
        pitch = float(np.median(np.diff(centers))) if len(row) > 1 else row[0][3] * 1.3
        keys: dict[int, KeyRead] = {}
        labelled_by = "templates"
        conf_row = 0.0
        if len(row) == n:
            labelled_by = "order"
            confs = []
            for idx, k in enumerate(row, start=1):
                if len(bank):
                    sym, score, margin = bank.match(k[4], allowed=set(range(1, n + 1)))
                    confs.append(0.97 if sym == idx else 0.55)
                else:
                    confs.append(0.9)
            conf_row = float(min(confs))
            for idx, k in enumerate(row, start=1):
                keys[idx] = KeyRead(idx, _key_rect(k, pitch), conf_row)
        elif len(bank):
            used: set[int] = set()
            confs = []
            for k in row:
                sym, score, margin = bank.match(k[4], allowed=set(range(1, n + 1)) - used)
                if sym == 0:
                    break
                c = float(np.clip((score - cfg.cells.digit_min_score) / (1 - cfg.cells.digit_min_score), 0, 1))
                if margin < cfg.cells.digit_min_margin:
                    c = min(c, 0.4)
                used.add(sym)
                confs.append(c)
                keys[sym] = KeyRead(sym, _key_rect(k, pitch), c)
            if len(keys) != len(row):
                continue
            # L'ordre gauche→droite doit rester croissant (le jeu conserve l'ordre)
            ordered = [s for s in sorted(keys, key=lambda s: keys[s].rect.x)]
            if ordered != sorted(ordered):
                continue
            conf_row = float(min(confs)) if confs else 0.0
        else:
            continue
        score = len(row) + conf_row + (row[0][1] / img.shape[0]) * 0.01
        if score > best_score:
            best_score = score
            best = KeypadRead(keys=keys, confidence=conf_row, labelled_by=labelled_by)
            best_row = row
    if best is not None and learn and best.labelled_by == "order" and best.confidence >= 0.85:
        for idx, k in enumerate(best_row, start=1):
            bank.add(idx, k[4])
    return best


def _key_rect(k: tuple, pitch: float) -> Rect:
    x, y, w, h, _ = k
    cx = x + w / 2.0
    kw = max(w * 1.2, pitch * 0.8)
    kh = h * 1.5
    return Rect(cx - kw / 2.0, y + h / 2.0 - kh / 2.0, kw, kh)
