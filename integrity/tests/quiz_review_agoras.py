"""Fake Agora entrypoints for the review-fix tests (integrity.tests.quiz_review_agoras:<name>)."""

from __future__ import annotations

from typing import Any

from integrity.tests import quiz_fake_agora as fa


def sysexit_agora(question: str) -> Any:
    fa.CALLS.append(question)
    raise SystemExit(3)


def interrupt_second_agora(question: str) -> Any:
    fa.CALLS.append(question)
    if len(fa.CALLS) == 2:
        raise KeyboardInterrupt
    return fa._good(fa.CARDS[question])


def declining_agora(question: str) -> Any:
    """Retrieves the right paragraph but declines (and cites nothing)."""
    fa.CALLS.append(question)
    r = fa._good(fa.CARDS[question])
    r.update(answer="The provided passages do not answer this question.", citations=[], self_check=None, declined=True)
    return r
