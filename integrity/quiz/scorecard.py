"""Scoring (plan section 9.6): per-card summaries, aggregate metrics, scorecard.json content.

There is deliberately no combined score. Holdout cards are aggregated separately and carry no question,
answer or key-point text in scorecard.json.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from integrity.common.schema import Card, Sheet
from integrity.quiz.grading.judge import MIN_CARD_COVERAGE

SCORECARD_SCHEMA = 1


def _ok(r: dict[str, Any] | None) -> bool:
    return bool(r) and r.get("status") == "ok"


def summarize_card(card: Card, grade: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    """Everything metrics need (plus failure details) for one scored or errored card."""
    a = card.anchor
    mech, jd = grade["mechanical"], grade.get("judged") or {}
    s: dict[str, Any] = {
        "card_id": card.card_id, "author": a.author, "work": a.work, "type": card.type, "holdout": card.holdout,
        "expected_behavior": card.expected_behavior, "error": None, "judged": bool(jd),
    }
    if mech.get("error"):
        s["error"] = mech["error"]["type"]
        s["failed_checks"] = ["error"]
        s["failures"] = [{"check": "error", "detail": f"{mech['error']['type']}: {mech['error'].get('message', '')}"}]
        return s
    qv = mech["quotes_verified"]
    s.update(
        block_hit=mech["block_hit"], block_rank=mech["block_rank"], near_hit=mech["near_hit"],
        evidence_found=mech["quotes_found"], evidence_total=mech["quotes_total"],
        cited_block=mech["cited_block"], quotes_verified=qv["verified"], quotes_total=qv["total"],
        trivial=mech["trivial_quotes"], invalid_ids=len(mech["invalid_ids"]), label_mismatches=len(mech["label_mismatches"]),
        no_citations=mech["no_citations"], self_check_disagreements=len(mech["self_check_disagreements"]),
        declined=mech["declined"], corpus_version_mismatch=mech["corpus_version_mismatch"],
    )
    failures: list[dict[str, str]] = []
    if not mech["block_hit"]:
        failures.append({"check": "M1 not_found", "detail": "the anchor paragraph was not retrieved "
                         f"(evidence recall {mech['quotes_found']}/{mech['quotes_total']})"})
    for name, key, label in (("M6 trivial_quotes", "trivial", "citation quotes under the minimum length"),
                             ("M7 invalid_ids", "invalid_ids", "cited passage ids that were never retrieved"),
                             ("M8 label_mismatches", "label_mismatches", "citation labels that differ from the retrieved passage")):
        if s[key]:
            failures.append({"check": name, "detail": f"{s[key]} {label}"})
    if mech["quotes_verified"]["verified"] < qv["total"]:
        failures.append({"check": "M5 quotes_verified", "detail": f"{qv['verified']}/{qv['total']} citation quotes found in retrieved text"})
    if jd:
        cov = Counter(c["verdict"] for c in jd["coverage"])
        s["coverage"] = {k: cov.get(k, 0) for k in ("covered", "partial", "absent", "unverified", "judge_error")}
        s["points_total"] = len(jd["coverage"])
        s["points_score"] = sum(c["score"] for c in jd["coverage"])
        stmt = {kp.id: kp.statement for kp in card.key_points}
        for c in jd["coverage"]:
            if c["verdict"] != "covered":
                failures.append({"check": f"J1 {c['verdict']}", "detail": f"{c['kp_id']}: {stmt.get(c['kp_id'], '')} "
                                 f"(judge: {c.get('model_verdict')}; evidence: {c.get('answer_span') or '-'}; {c.get('reason', '')})"})
        claims = jd["claims"]
        subs = {c["claim_id"]: c for c in claims["items"] if c["kind"] == "substantive"}
        sup = Counter()
        uncited = 0
        unmapped = sum(1 for c in subs.values() if c.get("unmapped") or c.get("citation_unmapped"))
        for r in jd["support"]:
            sup[r["verdict"]] += 1
            c = subs.get(r["claim_id"], {})
            if not c.get("cited_ids") and not c.get("citation_unmapped"):
                uncited += 1
            if r["verdict"] != "supported":
                failures.append({"check": f"J3 {r['verdict']}", "detail": f"{c.get('text', '')} (judge evidence: "
                                 f"{r.get('passage_span') or '-'}; {r.get('reason', '')})"})
        # Uncited claims are reported (SUPPORT line) but only block a pass when more than half of the substantive claims
        # are uncited. An uncited claim that is unsupported already fails through Faithful. Real Agora answers often
        # leave a lead-in sentence uncited, and the judge found every such claim supported (first live run).
        uncited_blocks = uncited > 0.5 * max(1, len(subs))
        if card.expected_behavior == "answer":
            if mech["no_citations"]:
                failures.append({"check": "M9 no_citations", "detail": "the answer carries no citations"})
            if uncited_blocks:
                failures.append({"check": "J3 uncited_claims", "detail": f"{uncited} of {len(subs)} substantive claim(s) "
                                 "cite no passage (more than half)"})
            if unmapped:
                failures.append({"check": "M13 unmapped_inline_citations", "detail": f"{unmapped} claim(s) cite a work/locator "
                                 "that matches no retrieved passage (judged against all retrieved passages)"})
        err = claims["source"] == "judge_error"
        if err:
            failures.append({"check": "J2 judge_error", "detail": "claim extraction failed"})
        rej = claims.get("rejected", [])
        for r in rej:  # a claim the judge returned but could not evidence in the answer: scored as unsupported
            failures.append({"check": "J2 unverified_claim", "detail": f"{r.get('text', '')} (answer span not found: "
                             f"{r.get('answer_span') or '-'})"})
        s["claims"] = {"total": sum(sup.values()) + err + len(rej), "supported": sup["supported"],
                       "not_supported": sup["not_supported"], "contradicted": sup["contradicted"],
                       "unverified": sup["unverified"] + len(rej), "judge_error": sup["judge_error"] + err,
                       "uncited": uncited, "unmapped": unmapped}
        s["claims_unsupported_any"] = s["claims"]["total"] > s["claims"]["supported"]
        ref = jd["refusal"]
        s["wrongful_refusal"] = card.expected_behavior == "answer" and ref["refused"] is True
        # claim-extraction health of this card: a fabricated answer must not pass by evading extraction
        refused = ref["refused"] is True or mech["declined"] is True
        s["extraction_coverage"] = claims["extraction_coverage"]
        n_sub = sum(1 for c in claims["items"] if c["kind"] == "substantive")
        extraction_bad = False
        if not err and not refused and claims.get("answer_chars", 1) > 0:
            if claims.get("returned", 1) == 0:
                extraction_bad = True
                failures.append({"check": "J2 no verified claims", "detail": "claim extraction returned no claims for a non-empty answer"})
            elif card.expected_behavior == "answer" and n_sub == 0:
                extraction_bad = True
                failures.append({"check": "J2 no verified claims", "detail": "no verified substantive claim in the answer"})
            if claims["extraction_coverage"] is not None and claims["extraction_coverage"] < MIN_CARD_COVERAGE:
                extraction_bad = True
                failures.append({"check": "J2 low extraction coverage", "detail": f"verified claims cover only "
                                 f"{claims['extraction_coverage']:.2f} of the answer (minimum {MIN_CARD_COVERAGE})"})
        s["extraction_failure"] = extraction_bad
        s["refusal_ok"] = ref["status"] == "ok" and ref["refused"] is False
        if card.expected_behavior == "answer" and not s["refusal_ok"]:
            failures.append({"check": "J4 refused" if ref["refused"] else f"J4 {ref['status']}",
                             "detail": f"answer judged as refusing ({ref.get('answer_span') or '-'})"})
        prem = jd.get("premise")
        s["premise_corrected"] = None if prem is None else prem["corrects_premise"] is True
        if prem is not None and not s["premise_corrected"]:
            failures.append({"check": "J5 premise_not_corrected", "detail": f"premise: {card.premise} ({prem.get('reason', '')})"})
        cite_ok = card.expected_behavior != "answer" or not (s["no_citations"] or uncited_blocks or unmapped)
        s["fully_passing"] = bool(
            cite_ok and not extraction_bad and s["block_hit"] and s["coverage"]["covered"] == s["points_total"] and not s["claims_unsupported_any"]
            and not (s["trivial"] or s["invalid_ids"] or s["label_mismatches"]) and s["refusal_ok"]
            and (s["premise_corrected"] is not False))
    else:
        s["fully_passing"] = None
        s["wrongful_refusal"] = card.expected_behavior == "answer" and mech["declined"] is True
        if card.expected_behavior == "answer":
            if mech["declined"] is True:
                failures.append({"check": "M11 declined", "detail": "Agora declined to answer an answerable question"})
            if mech["no_citations"]:
                failures.append({"check": "M9 no_citations", "detail": "the answer carries no citations"})
    s["failed_checks"] = [f["check"] for f in failures]
    s["failures"] = failures
    return s


def _detail(card: Card, raw: dict[str, Any]) -> dict[str, Any]:
    r = raw.get("result") or {}
    return {
        "question": card.question, "premise": card.premise,
        "expected": {"author": card.anchor.author, "work": card.anchor.work, "locator": card.anchor.locator},
        "top_retrieved": [{"rank": it.get("rank"), "author": it["author"], "work": it["work"], "locator": it["locator"]}
                          for it in (r.get("retrieved") or [])[:5]],
        "answer": r.get("answer"),
    }


def _frac(n: float, d: float) -> dict[str, float]:
    return {"n": n, "d": d}


def compute_metrics(cards: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [c for c in cards if not c["error"]]
    judged = [c for c in scored if c["judged"]]
    answerable = [c for c in scored if c["expected_behavior"] == "answer"]
    hits = [c for c in answerable if c["block_hit"]]
    ranks = Counter(str(c["block_rank"]) for c in hits)
    recall = [c["evidence_found"] / c["evidence_total"] for c in scored if c["evidence_total"]]
    cl = [c["claims"] for c in judged]
    cov = Counter()
    for c in judged:
        cov.update(c["coverage"])
    prem = [c for c in judged if c["premise_corrected"] is not None]
    ans_scored = [c for c in answerable]
    m: dict[str, Any] = {
        "cards": len(cards), "scored": len(scored), "errors": len(cards) - len(scored), "judged": len(judged),
        "answerable": len(answerable),
        "found": _frac(len(hits), len(answerable)),
        "rank_distribution": dict(sorted(ranks.items(), key=lambda kv: int(kv[0]))),
        "mrr": (sum(1 / c["block_rank"] for c in hits if c["block_rank"]) / len(answerable)) if answerable else None,
        "near_hits": sum(1 for c in answerable if not c["block_hit"] and c["near_hit"]),
        "evidence_recall": {"mean": (sum(recall) / len(recall)) if recall else None, "n": len(recall)},
        "complete": _frac(sum(c["points_score"] for c in judged), sum(c["points_total"] for c in judged)),
        "coverage_counts": {k: cov.get(k, 0) for k in ("covered", "partial", "absent", "unverified", "judge_error")},
        "faithful": _frac(sum(c["supported"] for c in cl), sum(c["total"] for c in cl)),
        "support_counts": {k: sum(c.get(k, 0) for c in cl) for k in
                           ("supported", "not_supported", "contradicted", "unverified", "judge_error", "uncited", "unmapped")},
        "answers_with_unsupported": sum(1 for c in judged if c["claims_unsupported_any"]),
        "citations": {
            "cited_block": _frac(sum(1 for c in ans_scored if c["cited_block"]), len(ans_scored)),
            "quotes_verified": _frac(sum(c["quotes_verified"] for c in scored), sum(c["quotes_total"] for c in scored)),
            "trivial": sum(c["trivial"] for c in scored), "invalid_ids": sum(c["invalid_ids"] for c in scored),
            "label_mismatches": sum(c["label_mismatches"] for c in scored),
            "no_citations": sum(1 for c in scored if c["no_citations"]),
            "self_check_disagreements": sum(c["self_check_disagreements"] for c in scored),
        },
        "behaviour": {"wrongful_refusals": sum(1 for c in scored if c.get("wrongful_refusal")),
                      "premise_corrected": _frac(sum(1 for c in prem if c["premise_corrected"]), len(prem))},
        "fully_passing": _frac(sum(1 for c in judged if c["fully_passing"]), len(judged)),
    }
    return m


def _group(cards: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in sorted({c[key] for c in cards}):
        m = compute_metrics([c for c in cards if c[key] == name])
        out[name] = {"found": m["found"], "complete": m["complete"], "faithful": m["faithful"], "scored": m["scored"]}
    return out


def build_scorecard(
    *, run: dict[str, Any], sheet: Sheet, cards: list[Card], grades: list[dict[str, Any]], raw: list[dict[str, Any]],
    health: dict[str, Any], never_retrieved: list[str], warnings: list[str], vs_previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_id = {c.card_id: c for c in cards}
    raw_by = {r["card_id"]: r for r in raw}
    real = [g for g in grades if not g.get("is_control")]
    summaries = []
    for g in real:
        card = by_id[g["card_id"]]
        s = summarize_card(card, g, raw_by.get(card.card_id))
        if not card.holdout:
            s["detail"] = _detail(card, raw_by.get(card.card_id) or {})
        else:  # sealed: ids and check names only
            s["failures"] = []
        summaries.append(s)
    main = [s for s in summaries if not s["holdout"]]
    hold = [s for s in summaries if s["holdout"]]
    mismatch = sum(1 for s in summaries if s.get("corpus_version_mismatch"))
    warnings = list(warnings)
    if mismatch:
        warnings.append(f"corpus_version differs from the sheet's for {mismatch} card(s): matching used text containment only")
    if never_retrieved:
        warnings.append("never retrieved during this run (is the book uploaded to the active namespace?): "
                        + "; ".join(never_retrieved))
    if health["claim_coverage_low"]:
        warnings.append(f"mean claim extraction coverage {health['claim_coverage']:.2f} is below 0.6")
    return {
        "schema": SCORECARD_SCHEMA, "run": run,
        # counts are those of the cards scored in THIS run; the whole sheet is reported separately
        "sheet": {"version": sheet.version, "cards": len(summaries), "holdout": len(hold),
                  "content_sha256": sheet.content_sha256,
                  "whole_sheet": {"cards": len(sheet.cards), "holdout": sum(c.holdout for c in sheet.cards)}},
        "main": compute_metrics(main), "holdout": compute_metrics(hold),
        "by_author": _group(main, "author"), "by_work": _group(main, "work"),
        "health": health,
        "trust": {"label": health["label"], "trusted": health["trusted"], "reasons": health["reasons"]},
        "warnings": warnings, "never_retrieved": never_retrieved, "vs_previous": vs_previous,
        "cards": summaries,
    }


def headline(sc: dict[str, Any]) -> dict[str, Any]:
    m = sc["main"]
    return {"found": m["found"], "complete": m["complete"], "faithful": m["faithful"],
            "fully_passing": m["fully_passing"], "errors": m["errors"], "trust": sc["trust"]["label"]}
