"""Extra fake Agoras for the quiz fix regressions (importable as integrity.tests.quiz_fix_agoras:<name>)."""

from __future__ import annotations

from typing import Any

from integrity.tests import quiz_fake_agora as fa


def _statements(c: dict) -> list[str]:
    return [k["statement"] for k in c["key_points"]]


def nocite_agora(question: str) -> dict[str, Any]:
    """Right statements, no citations at all, no inline citations."""
    fa.CALLS.append(question)
    c = fa.CARDS[question]
    r = fa._good(c)
    r["answer"] = " ".join(f"{s}." for s in _statements(c))
    r["citations"], r["self_check"] = [], []
    return r


def badinline_agora(question: str) -> dict[str, Any]:
    """Structured citations are right but every inline label names a locator that was never retrieved."""
    fa.CALLS.append(question)
    c = fa.CARDS[question]
    a = c["anchor"]
    r = fa._good(c)
    r["answer"] = " ".join(f"{s} ({a['author']}, {a['work']}, Chapter 99, paragraph 999)." for s in _statements(c))
    return r
