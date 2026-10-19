from bot.solver.solver import SolveStatus, candidates, find_conflicts, is_complete_and_valid, solve

P9 = [
    [5, 3, 0, 0, 7, 0, 0, 0, 0], [6, 0, 0, 1, 9, 5, 0, 0, 0], [0, 9, 8, 0, 0, 0, 0, 6, 0],
    [8, 0, 0, 0, 6, 0, 0, 0, 3], [4, 0, 0, 8, 0, 3, 0, 0, 1], [7, 0, 0, 0, 2, 0, 0, 0, 6],
    [0, 6, 0, 0, 0, 0, 2, 8, 0], [0, 0, 0, 4, 1, 9, 0, 0, 5], [0, 0, 0, 0, 8, 0, 0, 7, 9],
]


def test_9x9_unique():
    r = solve(P9, 3, 3)
    assert r.status == SolveStatus.UNIQUE
    assert is_complete_and_valid(r.solution, 3, 3)
    assert all(r.solution[i][j] == P9[i][j] for i in range(9) for j in range(9) if P9[i][j])


def test_4x4():
    r = solve([[1, 0, 0, 0], [0, 0, 3, 0], [0, 4, 0, 0], [0, 0, 0, 2]], 2, 2)
    assert r.status in (SolveStatus.UNIQUE, SolveStatus.MULTIPLE)
    assert is_complete_and_valid(r.solution, 2, 2)


def test_6x6_blocks_2x3():
    g = [[1, 2, 3, 4, 5, 6], [4, 5, 6, 1, 2, 3], [2, 3, 1, 5, 6, 4], [5, 6, 4, 2, 3, 1], [3, 1, 2, 6, 4, 5], [6, 4, 5, 3, 1, 2]]
    assert is_complete_and_valid(g, 2, 3)
    puzzle = [row[:] for row in g]
    for (r, c) in [(0, 0), (1, 4), (2, 2), (3, 5), (4, 1), (5, 3), (0, 5), (5, 0)]:
        puzzle[r][c] = 0
    res = solve(puzzle, 2, 3)
    assert res.status == SolveStatus.UNIQUE and res.solution == g


def test_12x12_blocks_3x4_empty_is_multiple():
    empty = [[0] * 12 for _ in range(12)]
    r = solve(empty, 3, 4, timeout_s=5)
    assert r.status == SolveStatus.MULTIPLE
    assert is_complete_and_valid(r.solution, 3, 4)


def test_invalid_and_conflicts():
    bad = [row[:] for row in P9]
    bad[0][2] = 5
    assert (0, 0) in find_conflicts(bad, 3, 3)
    assert solve(bad, 3, 3).status == SolveStatus.INVALID


def test_none_distinct_from_timeout():
    g = [[1, 2, 0, 0], [3, 4, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    g[2][0] = 2  # colonne 0 : 1,3,2 → reste 4 ; bloc bas-gauche bloqué par la ligne
    g[2][1] = 0
    g[3][1] = 1
    g[3][0] = 0
    g[2][2] = 4
    g[2][3] = 3
    r = solve(g, 2, 2)
    assert r.status in (SolveStatus.NONE, SolveStatus.UNIQUE, SolveStatus.INVALID)
    assert r.status != SolveStatus.TIMEOUT


def test_shape_errors():
    import pytest
    with pytest.raises(ValueError):
        solve([[0] * 6 for _ in range(6)], 3, 3)
    with pytest.raises(ValueError):
        solve([[0, 7], [0, 0]], 1, 2)


def test_candidates_counts():
    cc = candidates(P9, 3, 3)
    assert cc[(0, 2)] >= 1 and (0, 0) not in cc
