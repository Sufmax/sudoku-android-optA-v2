from bot.models import Rect
from bot.ocr.engine import merge_lines, parse_tsv
from bot.ocr.text import OcrLine, OcrWord, find_phrase, normalize, similarity
from bot.vision.screens import ScreenAnalyzer
from bot.vision.glyphs import TemplateBank
from bot.ocr.engine import OcrEngine

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv(rows):
    return "\n".join([HEADER] + ["\t".join(map(str, r)) for r in rows])


def line(*words, y=100):
    out, x = [], 50
    for w in words:
        out.append(OcrWord(w, 90.0, Rect(x, y, 20 * len(w), 40)))
        x += 20 * len(w) + 15
    return OcrLine(out)


def test_normalize_and_similarity():
    assert normalize("  Débutant  LVL ") == "debutant lvl"
    assert normalize("Aimez-vous le Sudoku ?") == "aimez vous le sudoku"
    assert similarity("Nouvelle partie", "nouvele partie") > 0.9


def test_parse_tsv_groups_lines_and_filters_conf():
    t = tsv([
        (5, 1, 1, 1, 1, 1, 100, 200, 120, 40, 91.5, "Nouvelle"),
        (5, 1, 1, 1, 1, 2, 230, 200, 100, 40, 88.0, "partie"),
        (5, 1, 2, 1, 1, 1, 100, 400, 60, 30, 12.0, "bruit"),
        (4, 1, 1, 1, 1, 0, 100, 200, 230, 40, -1, ""),
    ])
    lines = parse_tsv(t, 40)
    assert len(lines) == 1 and lines[0].text == "Nouvelle partie"
    assert lines[0].rect.x == 100 and lines[0].rect.x2 == 330


def test_find_phrase_fuzzy_and_short_exact():
    lines = [line("Nouvele", "partie", y=900), line("OK", y=1200), line("Bonjour", y=50)]
    m = find_phrase(lines, ["nouvelle partie"], 0.78)
    assert m is not None and m.rect.y == 900
    assert find_phrase(lines, ["ok"], 0.78).rect.y == 1200
    assert find_phrase([line("look")], ["ok"], 0.78) is None


def test_merge_lines_dedup():
    a = [line("Nouvelle", "partie")]
    b = [line("Nouvelle", "partie"), line("Facile", y=600)]
    assert len(merge_lines(a, b)) == 2


def test_rules_priority(cfg):
    an = ScreenAnalyzer(cfg, OcrEngine(cfg.ocr), TemplateBank(32, 4))
    # Fin de partie (« Débutant » dans le tableau) : la règle difficulty NE doit PAS gagner
    over = [line("Coup", "de", "génie", "!", y=300), line("Difficulté", "Débutant", y=500), line("Nouvelle", "partie", y=1200)]
    assert an.match_rules(over)[0].id == "game_over"
    sheet = [line("Nouvelle", "partie", y=700), line("Débutant", y=800), line("Facile", y=900), line("Moyen", y=1000)]
    assert an.match_rules(sheet)[0].id == "difficulty"
    best_over_sheet = [line("Nouveau", "Meilleur", "Temps!", y=300)] + sheet
    assert an.match_rules(best_over_sheet)[0].id == "difficulty"
    home = [line("Sudoku", "classique", y=800), line("Nouvelle", "partie", y=950)]
    assert an.match_rules(home)[0].id == "home"
    rate = [line("Aimez-vous", "le", "Sudoku?", y=400), line("Évaluez-nous", y=600)]
    assert an.match_rules(rate)[0].id == "rate_popup"
    assert an.match_rules([line("Lorem", "ipsum")]) is None
