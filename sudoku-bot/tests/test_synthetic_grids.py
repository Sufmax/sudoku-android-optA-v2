"""Grilles synthétiques : 4×4 (2×2), 6×6 (2×3), 12×12 (3×4) → géométrie déduite de l'image."""
import cv2
import numpy as np
import pytest

from bot.vision.grid import detect_grid


def draw_grid(n: int, br: int, bc: int, size: int = 900, W: int = 1080, H: int = 2000) -> np.ndarray:
    img = np.full((H, W, 3), 250, np.uint8)
    x0, y0 = (W - size) // 2, 400
    step = size / n
    for i in range(n + 1):
        thick_h = 6 if i % br == 0 else 2
        thick_v = 6 if i % bc == 0 else 2
        y = int(round(y0 + i * step))
        x = int(round(x0 + i * step))
        cv2.line(img, (x0, y), (x0 + size, y), (60, 60, 60), thick_h)
        cv2.line(img, (x, y0), (x, y0 + size), (60, 60, 60), thick_v)
    for r in range(n):
        for c in range((r * 3) % n, n, 4):
            cv2.putText(img, str((r + c) % 9 + 1), (int(x0 + c * step + step * 0.3), int(y0 + r * step + step * 0.75)), cv2.FONT_HERSHEY_SIMPLEX, step / 60, (20, 20, 20), 2)
    return img


@pytest.mark.parametrize("n,br,bc", [(4, 2, 2), (6, 2, 3), (6, 3, 2), (8, 2, 4), (9, 3, 3), (12, 3, 4), (16, 4, 4)])
def test_geometry(cfg, n, br, bc):
    geo = detect_grid(draw_grid(n, br, bc), cfg.detection.grid)
    assert geo is not None
    assert (geo.n, geo.box_rows, geo.box_cols) == (n, br, bc)
    assert not geo.blocks_from_fallback
