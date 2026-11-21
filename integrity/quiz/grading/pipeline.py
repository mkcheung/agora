"""Grade a whole run: mechanical + judge for every card, controls, consistency sample, health."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from integrity.common.schema import Card, Sheet
from integrity.common.settings import Settings
from integrity.quiz.grading import controls as ctl
from integrity.quiz.grading import health, mechanical
from integrity.quiz.grading.judge import Judge, JudgeOutcome, ReplayItem


@dataclass
class GradedRun:
    grades: list[dict[str, Any]] = field(default_factory=list)
    health: dict[str, Any] = field(default_factory=dict)
    never_retrieved: list[str] = field(default_factory=list)
    consistency: dict[str, Any] | None = None


def grade_one(card: Card, result: dict | None, error: dict | None, judge: Judge | None, quote_min_words: int,
              *, is_control: bool = False, control_kind: str | None = None) -> tuple[dict[str, Any], JudgeOutcome | None]:
    mech = mechanical.grade_mechanical(card, result, error, quote_min_words=quote_min_words)
    outcome = None
    judged: dict[str, Any] = {}
    calls: list[dict[str, Any]] = []
    if judge is not None and result is not None and not mech.get("error"):
        outcome = judge.grade_card(card, result)
        judged, calls = outcome.judged, outcome.calls
        refusal = judged["refusal"]
        declined = refusal["refused"] if refusal["status"] == "ok" else None
        mechanical.finalize_declined(card, mech, declined)
    rec = {"card_id": card.card_id, "is_control": is_control, "control_kind": control_kind,
           "mechanical": {k: v for k, v in mech.items() if not k.startswith("_")}, "judged": judged, "judge_calls": calls}
    return rec, outcome


def grade_run(
    *, sheet: Sheet, cards: list[Card], records: list[dict[str, Any]], judge: Judge | None, settings: Settings,
    calibration: dict[str, int] | None = None, on_progress: Callable[[dict], None] | None = None,
) -> GradedRun:
    qmw = settings.checks.quote_min_words
    by_id = {c.card_id: c for c in cards}
    run = GradedRun()
    replays: list[ReplayItem] = []
    by_card_replays: dict[str, list[dict[str, Any]]] = {}
    index: dict[str, dict[str, Any]] = {}
    if on_progress:
        on_progress({"event": "grading_started", "cards": len(records)})
    for rec in records:
        card = by_id.get(rec["card_id"])
        if card is None:
            continue
        g, outcome = grade_one(card, rec.get("result"), rec.get("error"), judge, qmw)
        run.grades.append(g)
        index[card.card_id] = g
        if outcome:
            replays.extend(outcome.replays)
    results = [r.get("result") for r in records]
    # only the works of the cards asked in this run (a --author/--limit/--cards run must not warn about the rest)
    asked = {by_id[r["card_id"]].anchor.work for r in records if r["card_id"] in by_id and r.get("result")}
    run.never_retrieved = mechanical.never_retrieved(sorted(asked), results) if any(results) else []

    # controls
    evals = []
    for control in ctl.build_controls(sheet, settings.judge.controls_per_run):
        g, _ = grade_one(control.card, control.result, None, judge, qmw, is_control=True, control_kind=control.kind)
        g["control_id"] = control.control_id
        ev = ctl.evaluate(control, g, judged=judge is not None)
        g["control_eval"] = ev
        run.grades.append(g)
        evals.append(ev)

    # consistency
    gv = judge.grader_version if judge else ""
    if judge is not None:
        seed = health.consistency_seed(sheet.content_sha256)
        run.consistency = health.run_consistency(replays, settings.judge.consistency_sample, seed)
        for row in run.consistency["rows"]:
            by_card_replays.setdefault(row["card_id"], []).extend(
                {**c, "consistency": True, "replay_of": row["key"]} for c in row["calls"])
        for cid, calls in by_card_replays.items():
            index[cid]["judge_calls"].extend(calls)
    run.health = health.summarize(run.grades, evals, run.consistency, calibration, mechanical_only=judge is None,
                                  grader_version=gv)
    return run
