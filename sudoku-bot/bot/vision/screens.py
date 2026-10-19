"""Classification de l'écran courant : partie en cours, chargement, voile modal, écran à règle OCR, inconnu."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from bot.config import AppConfig, ScreenRule
from bot.models import GridGeometry, Rect, ScreenKind, ScreenObservation
from bot.ocr.engine import OcrEngine, OcrUnavailable
from bot.ocr.text import OcrLine, PhraseMatch, find_phrase
from bot.vision.buttons import blob_above_text, button_region
from bot.vision.digits import grid_background_value, read_grid
from bot.vision.glyphs import TemplateBank
from bot.vision.grid import detect_grid
from bot.vision.keypad import detect_keypad

log = logging.getLogger("bot.vision")


@dataclass
class ActionTarget:
    rect: Rect
    confidence: float
    label: str


def saturated_blob_over_grid(img: np.ndarray, geo: GridGeometry, area_frac: float) -> bool:
    """Bulle d'information saturée et sombre (ex. « Plus de 19 % des joueurs… ») posée sur la grille."""
    r = geo.rect
    roi = img[int(r.y):int(r.y2), int(r.x):int(r.x2)]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 1] > 120) & (hsv[..., 2] < 200)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        return False
    return float(stats[1:, cv2.CC_STAT_AREA].max()) > area_frac * roi.shape[0] * roi.shape[1]


class ScreenAnalyzer:
    def __init__(self, cfg: AppConfig, ocr: OcrEngine, bank: TemplateBank) -> None:
        self.cfg = cfg
        self.ocr = ocr
        self.bank = bank

    def analyse_game(self, img: np.ndarray, learn: bool = True) -> ScreenObservation | None:
        det = self.cfg.detection
        geo = detect_grid(img, det.grid)
        if geo is None:
            return None
        if grid_background_value(img, geo) < det.overlay.dim_value_max:
            return ScreenObservation(ScreenKind.OVERLAY, 0.8, detail="voile modal sur la grille")
        if saturated_blob_over_grid(img, geo, det.overlay.blob_area_frac):
            return ScreenObservation(ScreenKind.LOADING, 0.8, detail="message transitoire sur la grille")
        keypad = detect_keypad(img, geo, self.bank, det, learn=learn)
        if keypad is None:
            return ScreenObservation(ScreenKind.OVERLAY, 0.5, detail="grille sans pavé numérique")
        grid = read_grid(img, geo, self.bank, det)
        conf = min(geo.confidence, keypad.confidence)
        return ScreenObservation(ScreenKind.GAME, conf, grid=grid, keypad=keypad, detail=f"{geo.n}x{geo.n} blocs {geo.box_rows}x{geo.box_cols}")

    def match_rules(self, lines: list[OcrLine]) -> tuple[ScreenRule, PhraseMatch] | None:
        best: tuple[ScreenRule, PhraseMatch] | None = None
        for rule in self.cfg.screens:
            m = find_phrase(lines, self.cfg.resolve_texts(rule.any), self.cfg.ocr.match_ratio)
            if m is None:
                continue
            if rule.all:
                extra = [find_phrase(lines, self.cfg.resolve_texts([t]), self.cfg.ocr.match_ratio) for t in rule.all]
                if any(e is None for e in extra):
                    continue
                m = min([m] + [e for e in extra if e is not None], key=lambda x: x.score)
            if best is None or (rule.priority, m.score) > (best[0].priority, best[1].score):
                best = (rule, m)
        return best

    def analyse(self, img: np.ndarray) -> tuple[ScreenObservation, list[OcrLine]]:
        game = self.analyse_game(img)
        if game is not None and game.kind == ScreenKind.GAME:
            return game, []
        try:
            lines = self.ocr.read_lines(img)
        except OcrUnavailable as exc:
            log.error("OCR indisponible : %s", exc)
            return ScreenObservation(ScreenKind.UNKNOWN, 0.0, detail=f"OCR indisponible : {exc}"), []
        texts = [ln.text for ln in lines]
        found = self.match_rules(lines)
        if found is not None:
            rule, m = found
            return ScreenObservation(ScreenKind.RULE, m.score, rule_id=rule.id, texts=texts, detail=f"« {m.matched} »"), lines
        if game is not None:
            game.texts = texts
            return game, lines
        return ScreenObservation(ScreenKind.UNKNOWN, 0.0, texts=texts, detail="aucune règle reconnue"), lines

    def locate(self, img: np.ndarray, lines: list[OcrLine], rule: ScreenRule) -> ActionTarget | None:
        """Cible à toucher pour l'action d'une règle (texte → bouton, ou objet au-dessus du texte)."""
        texts = self.cfg.resolve_texts(rule.action.texts)
        m = find_phrase(lines, texts, self.cfg.ocr.match_ratio)
        if m is None:
            return None
        if rule.action.type == "tap_blob_above_text":
            blob = blob_above_text(img, m.rect)
            if blob is None:
                return None
            return ActionTarget(blob, m.score * 0.9, f"objet au-dessus de « {m.matched} »")
        region, conf = button_region(img, m.rect)
        return ActionTarget(region, m.score * conf, m.matched)
