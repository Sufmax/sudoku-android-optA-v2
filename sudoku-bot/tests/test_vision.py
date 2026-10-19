"""Vision sur captures réelles de `easy.sudoku.puzzle.solver.free` (1080×2340)."""
import cv2
import pytest

from bot.models import CellKind
from bot.solver.solver import SolveStatus, find_conflicts, solve
from bot.vision.digits import read_grid
from bot.vision.grid import detect_grid
from bot.vision.keypad import detect_keypad

from conftest import load_screen

FRESH_ROW0 = [0, 0, 0, 1, 4, 3, 0, 0, 8]
FRESH_ROW8 = [6, 3, 0, 0, 8, 0, 0, 0, 9]


def test_grid_geometry_fresh(cfg):
    geo = detect_grid(load_screen("game_fresh.jpg"), cfg.detection.grid)
    assert geo is not None
    assert (geo.n, geo.box_rows, geo.box_cols) == (9, 3, 3)
    assert not geo.blocks_from_fallback
    assert geo.confidence > 0.9


@pytest.mark.parametrize("name", ["difficulty.jpg", "game_over.jpg", "popup_rate.jpg", "popup_streak1.jpg", "screen_1.jpg"])
def test_no_grid_on_menus(cfg, name):
    assert detect_grid(load_screen(name), cfg.detection.grid) is None


def test_read_fresh_and_solve(cfg, bank):
    img = load_screen("game_fresh.jpg")
    geo = detect_grid(img, cfg.detection.grid)
    read = read_grid(img, geo, bank, cfg.detection)
    vals = read.values()
    assert vals[0] == FRESH_ROW0 and vals[8] == FRESH_ROW8
    assert all(c.kind in (CellKind.GIVEN, CellKind.EMPTY) for row in read.cells for c in row)
    assert not find_conflicts(read.givens(), 3, 3)
    assert solve(read.givens(), 3, 3).status == SolveStatus.UNIQUE


def test_user_and_error_colors(cfg, bank):
    img = load_screen("grid_red_digits.jpg")
    geo = detect_grid(img, cfg.detection.grid)
    read = read_grid(img, geo, bank, cfg.detection)
    assert read.cells[1][1].kind == CellKind.ERROR and read.cells[1][1].value == 4
    assert read.cells[0][7].kind == CellKind.USER and read.cells[0][7].value == 4
    assert read.cells[7][2].kind == CellKind.ERROR  # rouge pâle


def test_keypad_partial_labelled_by_templates(cfg, bank):
    img = load_screen("screen_9.jpg")
    geo = detect_grid(img, cfg.detection.grid)
    kp = detect_keypad(img, geo, bank, cfg.detection, learn=False)
    assert kp is not None and kp.labelled_by == "templates"
    assert sorted(kp.keys) == [1, 2, 3, 4, 5, 6, 7, 8]
    xs = [kp.keys[d].rect.cx for d in sorted(kp.keys)]
    assert xs == sorted(xs)


def test_keypad_completed_digit_disappears_positions_stable(cfg, bank):
    """Chiffre 1 complété → sa touche disparaît, les autres gardent leur position (mesuré)."""
    fresh = load_screen("game_fresh.jpg")
    red = load_screen("grid_red_digits.jpg")
    g1 = detect_grid(fresh, cfg.detection.grid)
    g2 = detect_grid(red, cfg.detection.grid)
    k1 = detect_keypad(fresh, g1, bank, cfg.detection, learn=False)
    k2 = detect_keypad(red, g2, bank, cfg.detection, learn=False)
    assert 1 not in k2.keys
    for d in k2.keys:
        assert abs(k1.keys[d].rect.cx - k2.keys[d].rect.cx) < 8


def test_resolution_independence(cfg, bank):
    """Même écran réduit à 720 px de large : même géométrie, même lecture."""
    img = load_screen("game_fresh.jpg")
    small = cv2.resize(img, (720, int(img.shape[0] * 720 / img.shape[1])), interpolation=cv2.INTER_AREA)
    geo = detect_grid(small, cfg.detection.grid)
    assert geo is not None and (geo.n, geo.box_rows, geo.box_cols) == (9, 3, 3)
    read = read_grid(small, geo, bank, cfg.detection)
    assert read.values()[0] == FRESH_ROW0
