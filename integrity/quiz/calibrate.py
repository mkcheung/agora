"""Owner calibration (plan section 9.5): the owner checks a sample of judge verdicts.

Records are appended to calibration.jsonl keyed by grader_version. Holdout cards are never shown.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from integrity.common import sheets, storage
from integrity.common.schema import sha256_hex
from integrity.common.settings import Settings
from integrity.quiz import api
from integrity.quiz.grading import health


def sample_items(settings: Settings, run_id: str, n: int) -> tuple[str, str, list[dict[str, Any]]]:
    """(run_id, grader_version, up to n judged items), chosen reproducibly from the run id."""
    rid = api.resolve_run(settings.data_dir, run_id)
    rdir = storage.run_dir(settings.data_dir, rid)
    run = storage.read_json(rdir / "run.json")
    if not run.get("grader_version"):
        raise ValueError(f"run {rid} was graded without a judge (--mechanical-only); nothing to calibrate")
    sheet = sheets.load_sheet(settings.data_dir, run["sheet_version"])
    cards = {c.card_id: c for c in sheet.cards if not c.holdout}
    raw = {r["card_id"]: r for r in storage.read_jsonl(rdir / "raw.jsonl")}
    items: list[dict[str, Any]] = []
    for g in storage.read_jsonl(rdir / "grades.jsonl"):
        card = cards.get(g["card_id"])
        if g.get("is_control") or card is None or not g.get("judged"):
            continue
        result = raw.get(card.card_id, {}).get("result") or {}
        answer = result.get("answer", "")
        jd = g["judged"]
        stmt = {kp.id: kp for kp in card.key_points}
        for c in jd["coverage"]:
            kp = stmt[c["kp_id"]]
            items.append({"card_id": card.card_id, "kind": "coverage", "key": c["kp_id"], "verdict": c["verdict"],
                          "evidence": c["answer_span"], "inputs": f"key point: {kp.statement}\nanswer: {answer}"})
        claims = {i["claim_id"]: i for i in jd["claims"]["items"]}
        retrieved = {it["passage_id"]: it["text"] for it in result.get("retrieved", [])}
        for s in jd["support"]:
            cl = claims.get(s["claim_id"], {})
            items.append({"card_id": card.card_id, "kind": "support", "key": s["claim_id"], "verdict": s["verdict"],
                          "evidence": s["passage_span"],
                          "inputs": f"claim: {cl.get('text', '')}\npassage {s['passage_id']}: {retrieved.get(s['passage_id'], '(not cited)')}"})
        ref = jd["refusal"]
        items.append({"card_id": card.card_id, "kind": "refusal", "key": "refusal", "verdict": str(ref["refused"]),
                      "evidence": ref["answer_span"], "inputs": f"answer: {answer}"})
    items.sort(key=lambda i: (i["card_id"], i["kind"], i["key"]))
    seed = int(sha256_hex(rid)[:8], 16)
    chosen = random.Random(seed).sample(items, min(n, len(items)))
    return rid, run["grader_version"], chosen


def calibrate(
    settings: Settings, run_id: str | None, n: int, *, ask: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> int:
    rid, gv, items = sample_items(settings, run_id or "latest", n)
    if not items:
        out("no judged items to calibrate")
        return 1
    path = health.calibration_path(settings.data_dir)
    recorded = 0
    for i, it in enumerate(items, start=1):
        out(f"\n[{i}/{len(items)}] {it['kind']} {it['key']} (card {it['card_id']})\n{it['inputs']}\n"
            f"judge verdict: {it['verdict']}\njudge evidence: {it['evidence'] or '-'}")
        while True:
            try:
                a = ask("[a]gree  [d]isagree  [u]nsure  [q]uit > ").strip().lower()[:1]
            except EOFError:
                out(f"\ninput ended before the sample was finished; recorded {recorded} verdict(s)")
                return 1
            if a in ("a", "d", "u", "q"):
                break
        if a == "q":
            break
        storage.append_jsonl(path, {"grader_version": gv, "run_id": rid, "card_id": it["card_id"], "kind": it["kind"],
                                    "key": it["key"], "verdict": it["verdict"],
                                    "owner": {"a": "agree", "d": "disagree", "u": "unsure"}[a],
                                    "at": storage.iso_z(storage.utc_now())})
        recorded += 1
    s = health.calibration_summary(settings.data_dir, gv)
    out(f"\nrecorded {recorded}; grader {gv}: " + (f"{s['agree']}/{s['n']} agreed" if s else "not yet calibrated"))
    return 0
