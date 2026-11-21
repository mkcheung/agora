"""Mechanical grading M1-M12 (plan section 9.3). Pure code; matching only through common.textnorm."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from integrity.common import textnorm
from integrity.common.schema import Card


def _sk(s: Any) -> str:
    return textnorm.skeleton(str(s or ""))


def _found(quote: str, text: str) -> bool:
    return textnorm.find_span(quote, text) is not None


def grade_mechanical(
    card: Card, result: dict[str, Any] | None, error: dict[str, Any] | None = None, *, quote_min_words: int = 5
) -> dict[str, Any]:
    """Return the mechanical record for one card (or control). ``declined`` is None when J4 must decide."""
    if error or result is None:
        return {"error": error or {"type": "no_result", "message": ""}}
    anchor = card.anchor
    quotes = [kp.quote for kp in card.key_points]
    retrieved = result.get("retrieved") or []
    citations = result.get("citations") or []
    by_id: dict[str, list[dict]] = {}
    for it in retrieved:
        by_id.setdefault(it["passage_id"], []).append(it)

    def trusted(it: dict) -> bool:
        return bool(anchor.corpus_version) and it.get("corpus_version") == anchor.corpus_version

    n_trusted = sum(1 for it in retrieved if trusted(it))
    mech: dict[str, Any] = {
        "error": None,
        "ids_trusted": bool(retrieved) and n_trusted == len(retrieved),
        "corpus_version_mismatch": n_trusted < len(retrieved),
    }

    # M1
    ranks = []
    method = None
    for it in retrieved:
        by_ident = trusted(it) and it.get("block_id") == anchor.block_id
        by_text = any(_found(q, it["text"]) for q in quotes)
        if by_ident or by_text:
            ranks.append(it.get("rank") or 0)
            method = method or ("id" if by_ident else "text")
    mech["block_hit"] = bool(ranks)
    mech["block_rank"] = min(ranks) if ranks else None
    mech["block_hit_method"] = method if ranks else None

    # M2
    n_found = sum(1 for q in quotes if any(_found(q, it["text"]) for it in retrieved))
    mech["quotes_found"], mech["quotes_total"] = n_found, len(quotes)
    mech["evidence_recall"] = (n_found / len(quotes)) if quotes else None

    # M3
    near = None
    if not mech["block_hit"] and anchor.chapter is not None and anchor.section is not None:
        near = any(
            it.get("chapter") is not None and it.get("section") is not None
            and (it.get("work_id") == anchor.work_id if it.get("work_id") else _sk(it.get("work")) == _sk(anchor.work))
            and it["chapter"] == anchor.chapter and it["section"] == anchor.section
            for it in retrieved
        )
    mech["near_hit"] = near

    # M4: a citation counts only if its passage_id maps to a retrieved item that IS the anchor paragraph
    # (block_id equality when the corpus version is trusted, else the item's own text holds one of the card's
    # quotes). The citation's own quote never decides this.
    cited_block = False
    for c in citations:
        for it in by_id.get(c["passage_id"], []):
            if trusted(it):
                if it.get("block_id") == anchor.block_id:
                    cited_block = True
            elif any(_found(q, it["text"]) for q in quotes):
                cited_block = True
    mech["cited_block"] = cited_block

    # M5-M8
    verified = trivial = 0
    invalid: list[str] = []
    mismatches: list[dict] = []
    details = []
    for c in citations:
        items = by_id.get(c["passage_id"], [])
        ok = any(_found(c["quote"], it["text"]) for it in items)
        verified += ok
        details.append({"passage_id": c["passage_id"], "verified": ok})
        if textnorm.word_count(c["quote"]) < quote_min_words:
            trivial += 1
        if not items:
            invalid.append(c["passage_id"])
            continue
        it = items[0]
        bad = [f for f in ("author", "work", "locator") if _sk(c.get(f)) != _sk(it.get(f))]
        if bad:
            mismatches.append({"passage_id": c["passage_id"], "fields": bad})
    mech["quotes_verified"] = {"verified": verified, "total": len(citations), "items": details}
    mech["trivial_quotes"] = trivial
    mech["invalid_ids"] = invalid
    mech["label_mismatches"] = mismatches

    # M10
    ver = {(d["passage_id"], c["quote"]): d["verified"] for d, c in zip(details, citations, strict=True)}
    disagree = []
    for sc in result.get("self_check") or []:
        if sc["status"] != "ok":
            continue
        ok = any(_found(sc["quote"], it["text"]) for it in by_id.get(sc["passage_id"], []))
        if not ok and not ver.get((sc["passage_id"], sc["quote"]), False):
            disagree.append({"passage_id": sc["passage_id"], "quote": sc["quote"]})
    mech["self_check_disagreements"] = disagree

    # M11 / M9 (finalised after J4 when declined is absent)
    mech["declined"] = result.get("declined")
    finalize_declined(card, mech, mech["declined"], citations_empty=not citations)
    mech["_citations_empty"] = not citations
    return mech


def finalize_declined(card: Card, mech: dict[str, Any], declined: bool | None, *, citations_empty: bool | None = None) -> None:
    """Set the effective M11 value and M9. ``declined`` None means undecided (counts as not declined for M9)."""
    if citations_empty is None:
        citations_empty = mech.get("_citations_empty", False)
    mech["declined"] = declined
    mech["no_citations"] = bool(card.expected_behavior == "answer" and citations_empty and declined is not True)


def never_retrieved(works: Iterable[str], results: Iterable[dict[str, Any]]) -> list[str]:
    """Works on the sheet that appear in no retrieved item of any result (book may not be uploaded)."""
    seen = {_sk(it.get("work")) for r in results if r for it in r.get("retrieved") or []}
    return sorted({w for w in works if _sk(w) not in seen})
