"""Moteur OCR basé sur le binaire Tesseract (sortie TSV avec confiance par mot).

Appel direct du binaire (pas de dépendance pytesseract). Les appels sont bloquants :
le contrôleur les exécute dans un thread (`asyncio.to_thread`).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from bot.config import OcrCfg
from bot.models import Rect
from bot.ocr.text import OcrLine, OcrWord

log = logging.getLogger("bot.ocr")


class OcrUnavailable(RuntimeError):
    """Tesseract absent ou inutilisable : le bot refusera d'agir sur les menus."""


def parse_tsv(tsv: str, min_conf: float, scale: float = 1.0, offset: tuple[float, float] = (0.0, 0.0)) -> list[OcrLine]:
    """Transforme la sortie TSV de Tesseract en lignes de mots (coordonnées image d'origine)."""
    groups: dict[tuple[int, int, int, int], list[OcrWord]] = {}
    rows = tsv.strip().splitlines()
    if not rows:
        return []
    header = rows[0].split("\t")
    try:
        idx = {name: header.index(name) for name in ("level", "page_num", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text")}
    except ValueError as exc:
        raise ValueError(f"en-tête TSV inattendu : {header}") from exc
    for row in rows[1:]:
        cols = row.split("\t")
        if len(cols) < len(header):
            continue
        text = cols[idx["text"]].strip()
        if cols[idx["level"]] != "5" or not text:
            continue
        try:
            conf = float(cols[idx["conf"]])
        except ValueError:
            continue
        if conf < min_conf:
            continue
        x, y, w, h = (float(cols[idx[k]]) for k in ("left", "top", "width", "height"))
        rect = Rect(offset[0] + x / scale, offset[1] + y / scale, w / scale, h / scale)
        key = (int(cols[idx["page_num"]]), int(cols[idx["block_num"]]), int(cols[idx["par_num"]]), int(cols[idx["line_num"]]))
        groups.setdefault(key, []).append(OcrWord(text, conf, rect))
    lines = [OcrLine(sorted(ws, key=lambda w: w.rect.x)) for _, ws in sorted(groups.items())]
    return lines


def _overlap(a: Rect, b: Rect) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x, b.x))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y, b.y))
    inter = ix * iy
    small = min(a.w * a.h, b.w * b.h)
    return inter / small if small > 0 else 0.0


def merge_lines(primary: list[OcrLine], secondary: list[OcrLine]) -> list[OcrLine]:
    """Ajoute les lignes de `secondary` qui ne recouvrent aucune ligne de `primary`."""
    out = list(primary)
    for line in secondary:
        if all(_overlap(line.rect, p.rect) < 0.5 for p in primary):
            out.append(line)
    return out


class OcrEngine:
    def __init__(self, cfg: OcrCfg) -> None:
        self.cfg = cfg
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr")

    def available(self) -> bool:
        return shutil.which(self.cfg.tesseract_path) is not None

    def _run(self, gray: np.ndarray) -> str:
        ok, png = cv2.imencode(".png", gray)
        if not ok:
            raise OcrUnavailable("encodage PNG impossible")
        cmd = [self.cfg.tesseract_path, "stdin", "stdout", "-l", self.cfg.languages, "--psm", str(self.cfg.psm), "tsv"]
        try:
            res = subprocess.run(cmd, input=png.tobytes(), capture_output=True, timeout=self.cfg.timeout_s, check=False)
        except FileNotFoundError as exc:
            raise OcrUnavailable(f"tesseract introuvable ({self.cfg.tesseract_path})") from exc
        except subprocess.TimeoutExpired as exc:
            raise OcrUnavailable(f"tesseract a dépassé {self.cfg.timeout_s}s") from exc
        if res.returncode != 0:
            raise OcrUnavailable(f"tesseract a échoué : {res.stderr.decode(errors='replace')[:300]}")
        return res.stdout.decode("utf-8", errors="replace")

    def read_lines(self, img: np.ndarray, region: Rect | None = None) -> list[OcrLine]:
        """OCR de l'image (ou d'une région) → lignes de mots avec confiance."""
        ox, oy = 0.0, 0.0
        if region is not None:
            x0, y0 = max(0, int(region.x)), max(0, int(region.y))
            img = img[y0:int(region.y2), x0:int(region.x2)]
            ox, oy = float(x0), float(y0)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        jobs = [self._pool.submit(self._run, gray)]
        if self.cfg.dual_polarity:
            jobs.append(self._pool.submit(self._run, 255 - gray))
        results = [parse_tsv(j.result(), self.cfg.min_word_conf, 1.0, (ox, oy)) for j in jobs]
        lines = results[0]
        for extra in results[1:]:
            lines = merge_lines(lines, extra)
        return lines
