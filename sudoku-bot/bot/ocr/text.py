"""Normalisation de texte et correspondance floue tolérante (accents, casse, erreurs OCR)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from bot.models import Rect

_KEEP = re.compile(r"[^a-z0-9' ]+")


def normalize(text: str) -> str:
    """Minuscules, sans accents, ponctuation retirée, espaces compactés."""
    s = unicodedata.normalize("NFD", text or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()
    s = s.replace("’", "'")
    s = _KEEP.sub(" ", s)
    return " ".join(s.split())


def similarity(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class OcrWord:
    text: str
    conf: float
    rect: Rect


@dataclass
class OcrLine:
    words: list[OcrWord]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def rect(self) -> Rect:
        return union([w.rect for w in self.words])

    @property
    def conf(self) -> float:
        return min((w.conf for w in self.words), default=0.0)


def union(rects: list[Rect]) -> Rect:
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x2 for r in rects)
    y1 = max(r.y2 for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


@dataclass
class PhraseMatch:
    phrase: str
    matched: str
    rect: Rect
    ratio: float
    ocr_conf: float

    @property
    def score(self) -> float:
        """Score combiné (similarité × confiance OCR normalisée)."""
        return self.ratio * (0.6 + 0.4 * min(1.0, self.ocr_conf / 100.0))


def find_phrase(lines: list[OcrLine], phrases: list[str], min_ratio: float) -> PhraseMatch | None:
    """Meilleure occurrence d'une des phrases, sur des fenêtres de mots de chaque ligne."""
    best: PhraseMatch | None = None
    for phrase in phrases:
        target = normalize(phrase)
        if not target:
            continue
        n_words = len(target.split())
        short = len(target) <= 3
        for line in lines:
            words = line.words
            for size in {max(1, n_words - 1), n_words, n_words + 1}:
                for i in range(0, max(1, len(words) - size + 1)):
                    win = words[i:i + size]
                    if not win:
                        continue
                    cand = normalize(" ".join(w.text for w in win))
                    if not cand:
                        continue
                    if short:
                        ratio = 1.0 if cand == target else 0.0
                    elif target in cand and len(cand) <= len(target) * 1.6:
                        ratio = 1.0 if cand == target else 0.95
                    else:
                        ratio = SequenceMatcher(None, cand, target).ratio()
                    if ratio < min_ratio:
                        continue
                    m = PhraseMatch(phrase, cand, union([w.rect for w in win]), ratio, min(w.conf for w in win))
                    if best is None or m.score > best.score:
                        best = m
    return best
