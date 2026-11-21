"""Skeleton matching for verbatim quote checks (textnorm, version 1, frozen).

All quote and evidence checks in the module use this module and nothing else.
Any change to the behaviour requires TEXTNORM_VERSION 2.
"""

from __future__ import annotations

import unicodedata

from integrity import TEXTNORM_VERSION  # noqa: F401  (re-exported for callers)

_SPECIAL = {"æ": "ae", "œ": "oe", "ß": "ss", "&": "and"}


def _char_skeleton(ch: str) -> str:
    out = []
    for c in unicodedata.normalize("NFKD", ch):
        if unicodedata.combining(c):
            continue
        for d in c.casefold():
            for e in _SPECIAL.get(d, d):
                if e.isalnum():
                    out.append(e)
    return "".join(out)


def _skeleton_with_index(s: str) -> tuple[str, list[int]]:
    """Return (skeleton, index) where index[j] is the original position of skeleton char j."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(s):
        piece = _char_skeleton(ch)
        for p in piece:
            chars.append(p)
            index.append(i)
    return "".join(chars), index


def skeleton(s: str) -> str:
    """Letters and digits only, accent-free and case-folded (see module docstring)."""
    return _skeleton_with_index(s)[0]


def has_ellipsis(s: str) -> bool:
    return "..." in s or "…" in s


def word_count(span_text: str) -> int:
    """Whitespace-separated tokens containing at least one alphanumeric character."""
    return sum(1 for tok in span_text.split() if any(c.isalnum() for c in tok))


def _is_word_char(ch: str) -> bool:
    return ch.isalnum()


def _start_ok(text: str, start: int) -> bool:
    i = start - 1
    while i >= 0 and unicodedata.combining(text[i]):
        i -= 1
    return i < 0 or not _is_word_char(text[i])


def _end_ok(text: str, end: int) -> bool:
    return end >= len(text) or not _is_word_char(text[end])


def find_matches(quote: str, text: str) -> list[tuple[int, int]]:
    """All valid (word-boundary) matches of quote in text, as original-text spans, in order.

    A quote containing an ellipsis never matches.
    """
    if has_ellipsis(quote):
        return []
    q = skeleton(quote)
    if not q:
        return []
    t, idx = _skeleton_with_index(text)
    out: list[tuple[int, int]] = []
    pos = t.find(q)
    while pos != -1:
        start = idx[pos]
        end = idx[pos + len(q) - 1] + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        if _start_ok(text, start) and _end_ok(text, end):
            out.append((start, end))
        pos = t.find(q, pos + 1)
    return out


def find_span(quote: str, text: str) -> tuple[int, int] | None:
    """Original-text span of the first valid match, or None."""
    m = find_matches(quote, text)
    return m[0] if m else None


def count_matches(quote: str, text: str) -> int:
    """Number of valid matches of quote in text."""
    return len(find_matches(quote, text))
