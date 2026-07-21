"""Deterministic low-cost lexical features for SEC filing documents."""

from __future__ import annotations

import math
import re
from html.parser import HTMLParser

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{1,}")
_NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*(?:%|x)?")
_SENTENCE = re.compile(r"[.!?]+(?:\s|$)")
_SPACE = re.compile(r"\s+")

UNCERTAINTY = frozenset({
    "approximately", "assume", "assumption", "contingent", "could",
    "depend", "depends", "estimate", "estimated", "might", "may",
    "possible", "possibly", "risk", "risks", "uncertain", "uncertainty",
    "unknown", "unpredictable", "variable", "volatile",
})
POSITIVE = frozenset({
    "benefit", "favorable", "gain", "gains", "growth", "improve",
    "improved", "improvement", "increase", "increased", "opportunity",
    "positive", "profit", "profitable", "record", "strong", "success",
})
NEGATIVE = frozenset({
    "adverse", "decline", "declined", "decrease", "decreased", "deteriorate",
    "difficult", "impairment", "investigation", "loss", "losses", "negative",
    "restructuring", "weak", "weaker", "weakness",
})
LITIGIOUS = frozenset({
    "action", "claim", "claims", "court", "legal", "litigation",
    "plaintiff", "proceeding", "proceedings", "regulatory", "settlement",
})
FORWARD_LOOKING = frozenset({
    "anticipate", "believe", "expect", "forecast", "future", "guidance",
    "intend", "outlook", "plan", "project", "target",
})


class _VisibleTextParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "head", "ix:hidden"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    @staticmethod
    def _tag_name(tag: str) -> str:
        return tag.lower().split("}")[-1]

    def handle_starttag(self, tag: str, attrs) -> None:
        if self._tag_name(tag) in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._tag_name(tag) in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data)


def extract_visible_text(payload: bytes, content_type: str | None = None) -> str:
    """Extract text without executing HTML or retaining hidden XBRL blocks."""

    decoded = payload.decode("utf-8", errors="replace")
    looks_like_html = (
        "html" in str(content_type).lower()
        or "<html" in decoded[:2000].lower()
        or "<?xml" in decoded[:200].lower()
    )
    if looks_like_html:
        parser = _VisibleTextParser()
        parser.feed(decoded)
        parser.close()
        decoded = " ".join(parser.parts)
    return _SPACE.sub(" ", decoded).strip()


def _per_thousand(count: int, words: int) -> float:
    return 1000.0 * count / max(words, 1)


def compute_lexical_features(text: str) -> dict[str, float]:
    words = [token.lower() for token in _WORD.findall(text)]
    if len(words) < 50:
        raise ValueError(f"document has too few lexical tokens: {len(words)}")
    word_count = len(words)
    unique_count = len(set(words))
    sentence_count = max(1, len(_SENTENCE.findall(text)))
    uncertainty = sum(word in UNCERTAINTY for word in words)
    positive = sum(word in POSITIVE for word in words)
    negative = sum(word in NEGATIVE for word in words)
    litigious = sum(word in LITIGIOUS for word in words)
    forward = sum(word in FORWARD_LOOKING for word in words)
    number_count = len(_NUMBER.findall(text))
    return {
        "text_word_count_log1p": math.log1p(word_count),
        "text_char_count_log1p": math.log1p(len(text)),
        "avg_word_length": sum(map(len, words)) / word_count,
        "avg_sentence_words_log1p": math.log1p(word_count / sentence_count),
        "lexical_diversity": unique_count / word_count,
        "numeric_token_per_1000": _per_thousand(number_count, word_count),
        "uncertainty_per_1000": _per_thousand(uncertainty, word_count),
        "positive_per_1000": _per_thousand(positive, word_count),
        "negative_per_1000": _per_thousand(negative, word_count),
        "net_tone_per_1000": _per_thousand(positive - negative, word_count),
        "litigious_per_1000": _per_thousand(litigious, word_count),
        "forward_looking_per_1000": _per_thousand(forward, word_count),
    }


__all__ = [
    "compute_lexical_features",
    "extract_visible_text",
]
