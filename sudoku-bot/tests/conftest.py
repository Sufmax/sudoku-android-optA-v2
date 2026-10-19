"""Fixtures partagées : configuration, captures d'écran réelles du jeu, banque de gabarits amorcée."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.config import AppConfig, load_config  # noqa: E402
from bot.vision.glyphs import TemplateBank  # noqa: E402
from bot.vision.grid import detect_grid  # noqa: E402
from bot.vision.keypad import detect_keypad  # noqa: E402

SCREENS = ROOT / "tests" / "fixtures" / "screens"


@pytest.fixture(scope="session")
def cfg() -> AppConfig:
    return load_config(ROOT / "config" / "config.yaml", apply_env=False)


def load_screen(name: str) -> np.ndarray:
    """Charge une capture réelle du jeu ; saute le test (au lieu d'échouer) si les captures
    n'ont pas été copiées dans tests/fixtures/screens/ (fichiers binaires hors dépôt)."""
    if not (SCREENS / name).exists():
        pytest.skip(f"capture absente : tests/fixtures/screens/{name} (voir README › Tests)")
    img = cv2.imread(str(SCREENS / name))
    assert img is not None, f"fixture manquante : {name}"
    return img


@pytest.fixture(scope="session")
def bank(cfg: AppConfig) -> TemplateBank:
    """Banque amorcée UNIQUEMENT par le pavé complet d'une partie fraîche (100 % visuel)."""
    b = TemplateBank(cfg.detection.cells.template_size, cfg.detection.cells.templates_per_symbol)
    img = load_screen("game_fresh.jpg")
    geo = detect_grid(img, cfg.detection.grid)
    assert geo is not None
    kp = detect_keypad(img, geo, b, cfg.detection, learn=True)
    assert kp is not None and kp.labelled_by == "order"
    return b
