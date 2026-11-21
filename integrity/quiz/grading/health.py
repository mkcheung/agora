"""Grader health (plan section 9.5): trust, consistency, evidence rejection, extraction coverage, calibration."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from integrity.common import storage
from integrity.quiz.grading.judge import ReplayItem

LOW_COVERAGE = 0.6


def consistency_seed(content_sha256: str) -> int:
    return int((content_sha256 or "0")[:16], 16)


def select_sample(items: list[ReplayItem], fraction: float, seed: int) -> list[ReplayItem]:
    """Seeded, reproducible sample (independent of the order the items were produced in)."""
    if fraction <= 0 or not items:
        return []
    ordered = sorted(items, key=lambda i: (i.card_id, i.kind, i.key))
    n = min(len(ordered), max(1, round(fraction * len(ordered))))
    return random.Random(seed).sample(ordered, n)


def run_consistency(items: list[ReplayItem], fraction: float, seed: int) -> dict[str, Any]:
    """Judge a sample again in fresh calls; agreement = same effective verdict."""
    sample = select_sample(items, fraction, seed)
    agreed, rows = 0, []
    for it in sample:
        try:
            again, info = it.fn()
        except Exception as e:  # noqa: BLE001
            again, info = f"error:{type(e).__name__}", {"calls": []}
        ok = again == it.original
        agreed += ok
        rows.append({"card_id": it.card_id, "kind": it.kind, "key": it.key, "first": it.original, "second": again,
                     "agreed": ok, "calls": info.get("calls", [])})
    return {"sampled": len(sample), "agreed": agreed,
            "pct": round(100 * agreed / len(sample), 1) if sample else None, "rows": rows}


def calibration_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "calibration.jsonl"


def calibration_summary(data_dir: str | Path, grader_version: str) -> dict[str, int] | None:
    recs = [r for r in storage.read_jsonl(calibration_path(data_dir)) if r.get("grader_version") == grader_version]
    if not recs:
        return None
    return {"n": len(recs), "agree": sum(r.get("owner") == "agree" for r in recs),
            "disagree": sum(r.get("owner") == "disagree" for r in recs),
            "unsure": sum(r.get("owner") == "unsure" for r in recs)}


def _evidence_counts(grades: list[dict[str, Any]]) -> tuple[int, int]:
    total = rejected = 0
    for g in grades:
        jd = g.get("judged") or {}
        recs = list(jd.get("coverage", [])) + list(jd.get("support", []))
        recs += [r for r in (jd.get("refusal"), jd.get("premise")) if r]
        claims = jd.get("claims") or {}
        recs += list(claims.get("items", [])) + list(claims.get("rejected", []))
        for r in recs:
            if r.get("evidence_ok") is not None:
                total += 1
                rejected += r["evidence_ok"] is False
    return total, rejected


def summarize(
    grades: list[dict[str, Any]],
    control_evals: list[dict[str, Any]],
    consistency: dict[str, Any] | None,
    calibration: dict[str, int] | None,
    *,
    mechanical_only: bool,
    grader_version: str,
) -> dict[str, Any]:
    must = [c for c in control_evals if c["must_pass"] and c["passed"] is not None]
    failed = [c for c in must if not c["passed"]]
    info = [c for c in control_evals if not c["must_pass"] and c["passed"] is not None]
    total, rejected = _evidence_counts(grades)
    covs = [g["judged"]["claims"]["extraction_coverage"] for g in grades
            if not g.get("is_control") and (g.get("judged") or {}).get("claims", {}).get("extraction_coverage") is not None]
    mean_cov = round(sum(covs) / len(covs), 3) if covs else None
    judge_errors = sum(1 for g in grades if _has_judge_error(g))
    if mechanical_only:
        label, reasons = "NOT RUN (mechanical only)", []
    elif failed:
        label = "UNTRUSTED"
        reasons = [f"{c['kind']} failed on {c['card_id']}: {c['detail']}" for c in failed]
    elif not must:
        label, reasons = "UNVERIFIED (no controls ran)", []
    else:
        label, reasons = "TRUSTED", []
    return {
        "label": label, "trusted": None if mechanical_only else label == "TRUSTED", "reasons": reasons,
        "controls": {"must_pass_total": len(must), "must_pass_passed": len(must) - len(failed),
                     "informational_total": len(info), "informational_passed": sum(c["passed"] for c in info),
                     "failed": failed, "evals": control_evals},
        "evidence": {"checked": total, "rejected": rejected},
        "claim_coverage": mean_cov, "claim_coverage_low": mean_cov is not None and mean_cov < LOW_COVERAGE,
        "judge_errors": judge_errors,
        "consistency": ({k: v for k, v in consistency.items() if k != "rows"} if consistency else None),
        "calibration": calibration, "grader_version": grader_version,
    }


def _has_judge_error(g: dict[str, Any]) -> bool:
    jd = g.get("judged") or {}
    recs = list(jd.get("coverage", [])) + list(jd.get("support", [])) + [r for r in (jd.get("refusal"), jd.get("premise")) if r]
    return any(r.get("status") == "judge_error" for r in recs) or (jd.get("claims") or {}).get("source") == "judge_error"
