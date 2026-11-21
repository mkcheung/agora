"""Fake Agora entrypoints for the quiz tests (importable as integrity.tests.quiz_fake_agora:<name>)."""

from __future__ import annotations

import threading
from typing import Any

from integrity.common.schema import AgoraResult
from integrity.tests.quiz_fixtures import all_cards

CARDS: dict[str, dict[str, Any]] = {}  # question -> card dict
CALLS: list[str] = []
RELEASE = threading.Event()
INFO = {"model": "anthropic:claude-sonnet-5-5", "namespace": "ns-test", "k": 8, "filters": None, "code_sha256": "abc"}


def register(cards: list[dict[str, Any]] | None = None) -> None:
    CARDS.clear()
    CALLS.clear()
    RELEASE.clear()
    for c in cards or all_cards():
        CARDS[c["question"]] = c


def _cite(c: dict) -> str:
    a = c["anchor"]
    return f"({a['author']}, {a['work']}, {a['locator']})"


def _retrieved(c: dict, *, float_numbers: bool = True) -> list[dict]:
    a = c["anchor"]
    out = []
    for i, ch in enumerate(a["chunks"], start=1):
        item = {"rank": i, "author": a["author"], "work": a["work"], "locator": a["locator"], "passage_id": ch["passage_id"],
                "block_id": a["block_id"], "work_id": a["work_id"], "corpus_version": a["corpus_version"], "text": ch["text"]}
        if a.get("chapter") is not None:
            item["chapter"] = float(a["chapter"]) if float_numbers else a["chapter"]
        if a.get("section") is not None:
            item["section"] = float(a["section"]) if float_numbers else a["section"]
        out.append(item)
    return out


def _good(c: dict) -> dict[str, Any]:
    a = c["anchor"]
    answer = " ".join(f"{k['statement']} {_cite(c)}." for k in c["key_points"])
    citations = [{"author": a["author"], "work": a["work"], "chapter": a.get("chapter"), "section": a.get("section"),
                  "quote": k["quote"], "passage_id": k["chunk_ids"][0], "locator": a["locator"]} for k in c["key_points"]]
    return {"answer": answer, "citations": citations, "retrieved": _retrieved(c),
            "self_check": [{"passage_id": x["passage_id"], "quote": x["quote"], "status": "ok"} for x in citations],
            "attempts": 1, "info": dict(INFO)}


def good_agora(question: str) -> dict[str, Any]:
    CALLS.append(question)
    return _good(CARDS[question])


def wrong_passage_agora(question: str) -> dict[str, Any]:
    """Retrieves and cites a different card's passage."""
    CALLS.append(question)
    other = next(c for c in CARDS.values() if c["question"] != question and c["anchor"]["author"] != CARDS[question]["anchor"]["author"])
    r = _good(other)
    return r


def fabricating_agora(question: str) -> dict[str, Any]:
    CALLS.append(question)
    c = CARDS[question]
    r = _good(c)
    a = c["anchor"]
    r["answer"] += f" {a['author']} also argues that political authority is determined by the movements of the planets {_cite(c)}."
    return r


def contract_violating_agora(question: str) -> Any:
    CALLS.append(question)
    return {"answer": 5, "retrieved": []}


def violating_after_first_agora(question: str) -> Any:
    CALLS.append(question)
    if len(CALLS) == 1:
        return _good(CARDS[question])
    return {"answer": "x"}


def raising_agora(question: str) -> Any:
    CALLS.append(question)
    raise RuntimeError("agora exploded")


def slow_agora(question: str) -> Any:
    CALLS.append(question)
    RELEASE.wait(10)
    return _good(CARDS[question])


def pydantic_agora(question: str) -> Any:
    CALLS.append(question)
    return AgoraResult.model_validate(_good(CARDS[question]))


def flaky_once_agora(question: str) -> Any:
    CALLS.append(question)
    if CALLS.count(question) == 1:
        raise TimeoutError("transient")
    return _good(CARDS[question])


not_callable = 42
