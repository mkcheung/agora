"""Grader controls C1-C7 (plan section 9.5): synthetic Agora results with known correct grades.

Built deterministically from sheet cards (seed from the sheet's content_sha256); graded by the same code
as real answers; excluded from Agora's scores.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from integrity.common import textnorm
from integrity.common.schema import Card, Sheet
from integrity.quiz.grading.judge import MIN_CARD_COVERAGE

MUST_PASS = {"C1": True, "C2": True, "C3": True, "C4": False, "C5": True, "C6": True, "C7": True}
KINDS = tuple(MUST_PASS)
FABRICATIONS = (
    "{A} also argues that political authority is determined by the movements of the planets",
    "{A} holds that all lawful government should be carried on in total silence",
    "{A} claims that the rightful ruler is whoever owns the largest herd of cattle",
)
REFUSAL_ANSWER = "The provided passages do not answer this question."


@dataclass
class Control:
    control_id: str
    kind: str
    must_pass: bool
    card: Card
    result: dict[str, Any]
    info: dict[str, Any] = field(default_factory=dict)


def _cite(card: Card) -> str:
    a = card.anchor
    return f"({a.author}, {a.work}, {a.locator})"


def _chunks(card: Card) -> list[dict[str, str]]:
    a = card.anchor
    cs = [{"passage_id": c.passage_id, "text": c.text} for c in a.chunks]
    return cs or [{"passage_id": a.block_id + ":c0", "text": a.text}]


def _retrieved(card: Card) -> list[dict[str, Any]]:
    a = card.anchor
    return [
        {"rank": i, "passage_id": c["passage_id"], "text": c["text"], "author": a.author, "work": a.work,
         "locator": a.locator, "block_id": a.block_id, "work_id": a.work_id, "corpus_version": a.corpus_version,
         "chapter": a.chapter, "section": a.section}
        for i, c in enumerate(_chunks(card), start=1)
    ]


def _chunk_for(card: Card, kp: Any) -> str:
    chunks = _chunks(card)
    ids = {c["passage_id"] for c in chunks}
    for cid in kp.chunk_ids:
        if cid in ids:
            return cid
    for c in chunks:
        if textnorm.find_span(kp.quote, c["text"]):
            return c["passage_id"]
    return chunks[0]["passage_id"]


def _sentence(stmt: str, card: Card) -> str:
    return f"{stmt.rstrip('. ')} {_cite(card)}."


def _citation(card: Card, kp: Any) -> dict[str, Any]:
    a = card.anchor
    return {"passage_id": _chunk_for(card, kp), "author": a.author, "work": a.work, "locator": a.locator,
            "quote": kp.quote, "chapter": a.chapter, "section": a.section}


def _result(card: Card, sentences: list[str], citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"answer": " ".join(sentences), "citations": citations, "retrieved": _retrieved(card), "declined": None,
            "self_check": None, "attempts": 1, "claims": None, "info": {"control": True}}


def _faithful(card: Card, upto: int | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    kps = card.key_points if upto is None else card.key_points[:upto]
    return [_sentence(k.statement, card) for k in kps], [_citation(card, k) for k in kps]


def build_controls(sheet: Sheet, n: int) -> list[Control]:
    """C1-C7 for each of ``n`` cards chosen by a seed derived from the sheet's content_sha256."""
    if n <= 0:
        return []
    pool = sorted((c for c in sheet.cards if c.type == "passage" and not c.holdout and len(c.key_points) >= 2),
                  key=lambda c: c.card_id)
    if not pool:
        pool = sorted((c for c in sheet.cards if c.type == "passage" and c.key_points), key=lambda c: c.card_id)
    rng = random.Random(int(sheet.content_sha256[:16] or "0", 16))
    chosen = rng.sample(pool, min(n, len(pool)))
    out: list[Control] = []
    for card in chosen:
        a = card.anchor
        sents, cits = _faithful(card)

        def add(kind: str, result: dict[str, Any], card: Card = card, **info: Any) -> None:
            out.append(Control(f"ctl-{kind}-{card.card_id}", kind, MUST_PASS[kind], card, result, info))

        add("C1", _result(card, sents, cits))
        if len(card.key_points) >= 2:
            s2, c2 = _faithful(card, len(card.key_points) - 1)
            add("C2", _result(card, s2, c2), omitted=card.key_points[-1].id)
        fab = rng.choice(FABRICATIONS).format(A=a.author)
        fab_sentence = f"{fab} {_cite(card)}."
        add("C3", _result(card, [*sents, fab_sentence], cits), fabricated=fab_sentence)
        others = sorted((c for c in sheet.cards if c.anchor.author != a.author and c.key_points), key=lambda c: c.card_id)
        if others:
            sw = rng.choice(others).key_points[0].statement
            sw_sentence = _sentence(sw, card)
            add("C4", _result(card, [*sents, sw_sentence], cits), fabricated=sw_sentence)
        short = [dict(c) for c in cits]
        short[0]["quote"] = " ".join(short[0]["quote"].split()[:2])
        add("C5", _result(card, sents, short))
        bogus = [dict(c) for c in cits]
        bogus[0]["passage_id"] = "bogus:id:c0"
        add("C6", _result(card, sents, bogus))
        add("C7", _result(card, [REFUSAL_ANSWER], []))
    return out


def _overlaps(claim: dict[str, Any], answer: str, sentence: str) -> bool:
    target = textnorm.find_span(sentence, answer)
    span = claim.get("span")
    if target is None or not span:
        return False
    return span[0] < target[1] and target[0] < span[1]


def evaluate(control: Control, grade: dict[str, Any], *, judged: bool = True) -> dict[str, Any]:
    """Compare a control's grade record with its expected outcome. ``judged=False`` checks only mechanical parts."""
    mech, jd, kind = grade["mechanical"], grade.get("judged") or {}, control.kind
    answer = control.result["answer"]
    passed, detail = True, ""

    def fail(msg: str) -> None:
        nonlocal passed, detail
        passed, detail = False, msg

    cov = {c["kp_id"]: c["verdict"] for c in jd.get("coverage", [])}
    support = {s["claim_id"]: s["verdict"] for s in jd.get("support", [])}
    claims = (jd.get("claims") or {}).get("items", [])
    needs_judge = kind in ("C2", "C3", "C4", "C7")
    if mech.get("error"):
        fail(f"grading error: {mech['error']}")
    elif needs_judge and not judged:
        return {"control_id": control.control_id, "kind": kind, "card_id": control.card.card_id,
                "must_pass": control.must_pass, "passed": None, "detail": "skipped (mechanical only)"}
    elif kind == "C1":
        if not mech["block_hit"]:
            fail("M1 miss")
        elif mech["quotes_verified"]["verified"] != mech["quotes_verified"]["total"] or not mech["quotes_verified"]["total"]:
            fail("M5 not all verified")
        elif judged:
            bad = [k for k, v in cov.items() if v != "covered"]
            sup = [c for c in claims if c["kind"] == "substantive"]
            rej = (jd.get("claims") or {}).get("rejected") or []
            if not cov or bad:
                fail(f"points not covered: {bad or 'none judged'}")
            elif not sup or rej or any(support.get(c["claim_id"]) != "supported" for c in sup):
                fail("not every claim supported" + (f" ({len(rej)} claim(s) with an unverifiable span)" if rej else ""))
            elif (jd.get("claims") or {}).get("extraction_coverage", 1) < MIN_CARD_COVERAGE:
                fail("claim extraction coverage too low")
    elif kind == "C2":
        last = control.info["omitted"]
        # "partial" is acceptable: the remaining statements can legitimately overlap the omitted point (seen live,
        # first quiz run). What must never happen is "covered" (or an unverified/missing verdict).
        if cov.get(last) not in ("absent", "partial"):
            fail(f"omitted point {last} judged {cov.get(last)}")
        elif any(v != "covered" for k, v in cov.items() if k != last):
            fail("a remaining point was not covered")
    elif kind in ("C3", "C4"):
        hit = [c for c in claims if c["kind"] == "substantive" and _overlaps(c, answer, control.info["fabricated"])]
        # a judge that calls the planted claim "contradicted" caught it just as well as "not supported" (seen live)
        want = {"not_supported", "contradicted"}
        if not hit:
            fail("fabricated claim was not extracted")
        elif any(support.get(c["claim_id"]) not in want for c in hit):
            fail(f"fabricated claim judged {[support.get(c['claim_id']) for c in hit]}")
    elif kind == "C5":
        if mech["trivial_quotes"] != 1:
            fail(f"M6 counted {mech['trivial_quotes']}")
    elif kind == "C6":
        if len(mech["invalid_ids"]) != 1:
            fail(f"M7 counted {len(mech['invalid_ids'])}")
    elif kind == "C7" and (jd.get("refusal") or {}).get("refused") is not True:
        fail("refusal not detected")
    return {"control_id": control.control_id, "kind": kind, "card_id": control.card.card_id,
            "must_pass": control.must_pass, "passed": passed, "detail": detail}
