import random

from bot.input.waves import GivenMismatchError, WaveSizer, correct_counts, evaluate_wave, next_wave, order_moves, plan_moves
from bot.models import CellKind, CellRead, GridGeometry, GridRead, Move, Rect

import pytest

SOL = [[1, 2, 3, 4], [3, 4, 1, 2], [2, 1, 4, 3], [4, 3, 2, 1]]


def make_read(spec):
    """spec : liste de chaînes, 'g3' donné, 'u3' saisi, 'e3' erreur, '.' vide."""
    geo = GridGeometry(Rect(0, 0, 400, 400), 4, 2, 2, (0, 100, 200, 300, 400), (0, 100, 200, 300, 400), 1.0)
    kinds = {"g": CellKind.GIVEN, "u": CellKind.USER, "e": CellKind.ERROR}
    cells = []
    for row in spec:
        out = []
        for tok in row.split():
            if tok == ".":
                out.append(CellRead(0, CellKind.EMPTY, 0.95))
            else:
                out.append(CellRead(int(tok[1]), kinds[tok[0]], 0.95))
        cells.append(out)
    return GridRead(geo, cells)


def test_plan_skips_givens_and_correct_user_fixes_errors():
    read = make_read(["g1 . u3 .", ". g4 . .", "e3 . . .", ". . . g1"])
    moves = plan_moves(read, SOL)
    assert Move(0, 2, 3) not in moves  # saisie correcte conservée
    assert Move(2, 0, 2) in moves  # erreur corrigée
    assert all(not (m.r == 0 and m.c == 0) for m in moves)  # jamais un chiffre initial


def test_plan_rejects_misread_given():
    with pytest.raises(GivenMismatchError):
        plan_moves(make_read(["g2 . . .", ". . . .", ". . . .", ". . . ."]), SOL)


def test_wave_cut_on_digit_completion():
    read = make_read(["g1 . . .", ". . g1 .", ". g1 . .", ". . . ."])
    counts = correct_counts(read, SOL)
    assert counts[1] == 3
    queue = [Move(0, 1, 2), Move(3, 3, 1), Move(1, 0, 3), Move(1, 1, 4)]
    wave = next_wave(queue, counts, 4, 10, {1, 2, 3, 4})
    assert wave == [Move(0, 1, 2), Move(3, 3, 1)]  # coupée après la complétion du 1


def test_wave_respects_available_keys_and_size():
    read = make_read([". . . .", ". . . .", ". . . .", ". . . ."])
    queue = [Move(0, 0, 1), Move(0, 1, 2), Move(0, 2, 3), Move(0, 3, 4)]
    assert next_wave(queue, correct_counts(read, SOL), 4, 2, {2, 3, 4}) == [Move(0, 1, 2), Move(0, 2, 3)]


def test_evaluate_wave():
    before = make_read(["g1 . . .", ". . . .", ". . . .", ". . . ."])
    after = make_read(["g1 u2 . e9", ". u1 . .", ". . . .", ". . . ."])
    wave = [Move(0, 1, 2), Move(0, 2, 3), Move(0, 3, 4), Move(1, 1, 4)]
    res = evaluate_wave(wave, before, after)
    assert res.ok == [Move(0, 1, 2)] and res.missing == [Move(0, 2, 3)]
    assert res.errors == [Move(0, 3, 4)] and res.wrong == [Move(1, 1, 4)]
    assert res.fail_rate == 0.75 and not res.givens_changed


def test_evaluate_detects_given_change():
    before = make_read(["g1 . . .", ". . . .", ". . . .", ". . . ."])
    after = make_read(["u1 . . .", ". . . .", ". . . .", ". . . ."])
    assert evaluate_wave([], before, after).givens_changed


def test_wave_sizer():
    s = WaveSizer(1, 0.15, 0.5, 1.25, 2)
    assert s.size(8) == 8
    bad = evaluate_wave([Move(0, 1, 2)], make_read(["g1 . . .", ". . . .", ". . . .", ". . . ."]), make_read(["g1 . . .", ". . . .", ". . . .", ". . . ."]))
    s.update(bad)
    assert s.size(8) == 4
    good = evaluate_wave([Move(0, 1, 2)], make_read(["g1 . . .", ". . . .", ". . . .", ". . . ."]), make_read(["g1 u2 . .", ". . . .", ". . . .", ". . . ."]))
    s.update(good)
    s.update(good)
    assert s.size(8) == 5


def test_order_moves_is_permutation():
    moves = [Move(r, c, SOL[r][c]) for r in range(4) for c in range(4)]
    for mode in ("human", "rows", "random", "box", "digit"):
        out = order_moves(moves, mode, 2, 2, None, random.Random(1))
        assert sorted(out, key=lambda m: (m.r, m.c)) == sorted(moves, key=lambda m: (m.r, m.c))
