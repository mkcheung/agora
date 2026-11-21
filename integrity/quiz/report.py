"""Rendering: terminal summary, scorecard.md, failures.md, and run comparison (plan sections 9.7, 9.8)."""

from __future__ import annotations

from typing import Any

from integrity.quiz import scorecard as scoring


def num(x: float | None) -> str:
    if x is None:
        return "n/a"
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def pct(n: float, d: float) -> str:
    return f"{round(100 * n / d)}%" if d else "n/a"


def frac(f: dict[str, float]) -> str:
    return f"{num(f['n'])}/{num(f['d'])}"


def signed(x: float, unit: str = "") -> str:
    s = f"{x:+.1f}" if not float(x).is_integer() else f"{int(x):+d}"
    return s + unit


def _git(run: dict[str, Any]) -> str:
    c = run.get("git_commit")
    if not c:
        return "git n/a"
    return f"git {c[:7]}" + (" (dirty)" if run.get("git_dirty") else "")


def _judged_tag(sc: dict[str, Any]) -> str:
    label = sc["trust"]["label"]
    return "  [UNTRUSTED]" if label == "UNTRUSTED" else "  [UNVERIFIED]" if label.startswith("UNVERIFIED") else ""


def _sheet_counts(sheet: dict[str, Any], word: str) -> str:
    """Cards of this run, plus the whole sheet when the run covered only part of it."""
    s = f"{sheet['cards']} cards, {sheet['holdout']} {word}"
    w = sheet.get("whole_sheet")
    if w and (w["cards"], w["holdout"]) != (sheet["cards"], sheet["holdout"]):
        s += f"; sheet has {w['cards']} cards, {w['holdout']} {word}"
    return s


# --------------------------------------------------------------------------- terminal


def render_terminal(sc: dict[str, Any]) -> str:
    run, m = sc["run"], sc["main"]
    judged = m["judged"] > 0
    tag = _judged_tag(sc)
    mech_only = run.get("mechanical_only")
    L: list[str] = []
    sheet = sc["sheet"]
    if sc["trust"]["label"] == "UNTRUSTED":
        L.append("WARNING: judged metrics (Complete, Faithful, Fully passing) are UNTRUSTED: " + "; ".join(sc["trust"]["reasons"]))
    elif sc["trust"]["label"].startswith("UNVERIFIED") and judged:
        L.append(f"WARNING: judged metrics (Complete, Faithful, Fully passing) are {sc['trust']['label']}: "
                 "the grader's controls were not checked")
    L.append(f"INTEGRITY QUIZ  {run['run_id']}   sheet {sheet['version']} ({_sheet_counts(sheet, 'sealed')})"
             f"   grader {run.get('grader_version') or '-'}   judge {'none (mechanical only)' if mech_only else run.get('judge_model')}")
    agora = [f"Agora {run.get('entrypoint')}"]
    if run.get("agora_model"):
        agora.append(run["agora_model"])
    if run.get("k") is not None:
        agora.append(f"k={run['k']}")
    if run.get("namespace"):
        agora.append(f"ns {run['namespace']}")
    agora.append(_git(run))
    L.append(" · ".join(agora))
    if run.get("source_run"):
        L.append(f"regraded from {run['source_run']}")
    L.append("")
    L.append(f"HEADLINE ({m['cards']} main cards)")
    L.append(f"  {'Found':<10} {'right paragraph retrieved':<35} {frac(m['found']):<8} {pct(**_nd(m['found']))}")
    if judged:
        L.append(f"  {'Complete':<10} {'key points covered':<35} {frac(m['complete']):<8} {pct(**_nd(m['complete']))}{tag}")
        sc_ = m["support_counts"]
        extra = f"   ({sc_['contradicted']} contradicted ⚠)" if sc_["contradicted"] else ""
        L.append(f"  {'Faithful':<10} {'claims supported by citations':<35} {frac(m['faithful']):<8} {pct(**_nd(m['faithful']))}{extra}{tag}")
        L.append(f"  {'Fully passing cards':<46} {frac(m['fully_passing'])}{tag}")
    else:
        L.append("  Complete / Faithful / Fully passing: not computed (--mechanical-only)")
    c = m["citations"]
    wr = f" · Wrongful refusals {m['behaviour']['wrongful_refusals']}"
    L.append(f"  Errors {m['errors']}{wr} · Answers with no citations {c['no_citations']}")
    L.append("")
    k = run.get("k")
    er = m["evidence_recall"]["mean"]
    mrr = "n/a" if m["mrr"] is None else f"{m['mrr']:.2f}"
    L.append(f"RETRIEVAL   hit@{k if k is not None else 'k'} {frac(m['found'])} · evidence recall "
             f"{'n/a' if er is None else f'{round(100 * er)}%'} · MRR {mrr} · near hits {m['near_hits']}")
    L.append(f"CITATIONS   cited right paragraph {frac(c['cited_block'])} · quotes verified {frac(c['quotes_verified'])} · "
             f"trivial {c['trivial']} · invented IDs {c['invalid_ids']} · label mismatches {c['label_mismatches']}")
    if c["self_check_disagreements"]:
        L.append(f"            Agora self-check disagreed with the module on {c['self_check_disagreements']} quotes")
    if judged:
        cv, su = m["coverage_counts"], m["support_counts"]
        L.append(f"COVERAGE    covered {cv['covered']} · partial {cv['partial']} · absent {cv['absent']}"
                 + (f" · unverified {cv['unverified']}" if cv["unverified"] else "")
                 + (f" · judge errors {cv['judge_error']}" if cv["judge_error"] else "") + tag)
        L.append(f"SUPPORT     supported {su['supported']} · not supported {su['not_supported']} · contradicted {su['contradicted']}"
                 f" · unverified {su['unverified']} · uncited claims {su['uncited']} · unmapped citations {su['unmapped']}"
                 + (f" · judge errors {su['judge_error']}" if su["judge_error"] else "") + tag)
    L.append("")
    w = max([13, *(len(n) for n in sc["by_author"])]) + 2
    L.append(f"{'BY AUTHOR':<{w + 2}}{'Found':<8}{'Complete':>9}{'Faithful':>10}" + (tag if judged else ""))
    for name, g in sc["by_author"].items():
        comp = pct(**_nd(g["complete"])) if judged else "-"
        fa = pct(**_nd(g["faithful"])) if judged else "-"
        L.append(f"  {name:<{w}}{frac(g['found']):<8}{comp:>9}{fa:>10}")
    ho = sc["holdout"]
    if ho["cards"]:
        s = f"SEALED ({ho['cards']})  Found {frac(ho['found'])}"
        if ho["judged"]:
            s += f" · Complete {pct(**_nd(ho['complete']))} · Faithful {pct(**_nd(ho['faithful']))}"
        L.append("")
        L.append(s + (tag if ho["judged"] else ""))
    L.append("")
    L.extend(_health_lines(sc))
    for w in sc["warnings"]:
        L.append(f"warning: {w}")
    if sc.get("vs_previous"):
        v = sc["vs_previous"]
        L.append(f"vs {v['run_id']} (same sheet): {v['text']}")
    L.append("")
    L.append(f"Files: {run.get('files_dir', '')}/scorecard.md, failures.md, scorecard.json")
    return "\n".join(L) + "\n"


def _nd(f: dict[str, float]) -> dict[str, float]:
    return {"n": f["n"], "d": f["d"]}


def _mark(h: dict[str, Any]) -> str:
    """A check mark only for a TRUSTED grader; 'no controls ran' is neither a pass nor a fail."""
    return "✓" if h["label"] == "TRUSTED" else "✗" if h["label"] == "UNTRUSTED" else "-"


def _health_lines(sc: dict[str, Any]) -> list[str]:
    h = sc["health"]
    if sc["run"].get("mechanical_only"):
        return ["GRADER HEALTH  not run (--mechanical-only)"]
    c = h["controls"]
    first = [f"controls {c['must_pass_passed']}/{c['must_pass_total']} must-pass " + _mark(h)]
    ev = h["evidence"]
    first.append(f"evidence rejected {ev['rejected']}/{ev['checked']}")
    first.append("claim coverage " + ("n/a" if h["claim_coverage"] is None else f"{h['claim_coverage']:.2f}"
                                       + (" ⚠ low" if h["claim_coverage_low"] else "")))
    if h["judge_errors"]:
        first.append(f"judge errors on {h['judge_errors']} cards")
    second = []
    co = h["consistency"]
    if co and co["sampled"]:
        second.append(f"consistency {co['agreed']}/{co['sampled']} ({round(co['pct'])}%)")
    else:
        second.append("consistency not sampled")
    ca = h["calibration"]
    gv = h["grader_version"]
    if ca:
        second.append(f"owner agreement {ca['agree']}/{ca['n']} (grader {gv})")
    else:
        second.append(f"owner agreement: not yet calibrated (grader {gv})")
    return [f"GRADER HEALTH  {' · '.join(first)} · trust {h['label']}", f"               {' · '.join(second)}"]


# --------------------------------------------------------------------------- scorecard.md


def render_scorecard_md(sc: dict[str, Any]) -> str:
    run, m = sc["run"], sc["main"]
    judged = m["judged"] > 0
    tag = {"  [UNTRUSTED]": " (UNTRUSTED)", "  [UNVERIFIED]": " (UNVERIFIED)"}.get(_judged_tag(sc), "")
    L = [f"# Scorecard {run['run_id']}", "",
         (f"- Sheet: {sc['sheet']['version']} ({_sheet_counts(sc['sheet'], 'holdout')}), "
          f"content `{sc['sheet']['content_sha256'][:12]}`"),
         f"- Grader: {run.get('grader_version') or '-'}; judge: {run.get('judge_model') if not run.get('mechanical_only') else 'none (mechanical only)'}",
         f"- Agora: {run.get('entrypoint')} · {run.get('agora_model') or 'model n/a'} · k={run.get('k')} · ns {run.get('namespace') or 'n/a'} · {_git(run)}",
         f"- Judged-metric trust: **{sc['trust']['label']}**"]
    if run.get("source_run"):
        L.append(f"- Regraded from {run['source_run']}")
    L += ["", f"## Headline ({m['cards']} main cards)", "", "| Metric | Value | Share |", "|---|---|---|",
          f"| Found (right paragraph retrieved) | {frac(m['found'])} | {pct(**_nd(m['found']))} |"]
    if judged:
        L += [f"| Complete (key points covered){tag} | {frac(m['complete'])} | {pct(**_nd(m['complete']))} |",
              f"| Faithful (claims supported){tag} | {frac(m['faithful'])} | {pct(**_nd(m['faithful']))} |",
              f"| Fully passing cards{tag} | {frac(m['fully_passing'])} | {pct(**_nd(m['fully_passing']))} |"]
    c = m["citations"]
    L += ["", f"Errors: {m['errors']}. Answers with no citations: {c['no_citations']}."
          + f" Wrongful refusals: {m['behaviour']['wrongful_refusals']}.", "",
          "## Retrieval", "",
          f"- hit rank distribution: {', '.join(f'rank {k}: {v}' for k, v in m['rank_distribution'].items()) or 'none'}",
          f"- MRR: {'n/a' if m['mrr'] is None else f'{m['mrr']:.2f}'}; near hits: {m['near_hits']}",
          f"- evidence recall: {'n/a' if m['evidence_recall']['mean'] is None else pct(m['evidence_recall']['mean'], 1)}",
          "", "## Citation integrity", "",
          f"- cited the anchor paragraph: {frac(c['cited_block'])}",
          f"- quotes verified: {frac(c['quotes_verified'])}",
          (f"- trivial quotes: {c['trivial']}; invented ids: {c['invalid_ids']}; label mismatches: {c['label_mismatches']}; "
           f"no citations: {c['no_citations']}; self-check disagreements: {c['self_check_disagreements']}")]
    if judged:
        cv, su = m["coverage_counts"], m["support_counts"]
        L += ["", f"## Coverage and support{tag}", "",
              (f"- coverage: covered {cv['covered']}, partial {cv['partial']}, absent {cv['absent']}, "
               f"unverified {cv['unverified']}, judge error {cv['judge_error']}"),
              (f"- support: supported {su['supported']}, not supported {su['not_supported']}, contradicted {su['contradicted']}, "
               f"unverified {su['unverified']}, judge error {su['judge_error']}, uncited claims {su['uncited']}, "
               f"unmapped inline citations (M13) {su['unmapped']}"),
              f"- answers with at least one unsupported claim: {m['answers_with_unsupported']}",
              f"- premise corrected: {frac(m['behaviour']['premise_corrected'])}"]
    L += ["", f"## By author{tag if judged else ''}", "", "| Author | Found | Complete | Faithful |", "|---|---|---|---|"]
    for n, g in sc["by_author"].items():
        L.append(f"| {n} | {frac(g['found'])} | {_cf(g['complete'], judged)} | {_cf(g['faithful'], judged)} |")
    L += ["", f"## By work{tag if judged else ''}", "", "| Work | Found | Complete | Faithful |", "|---|---|---|---|"]
    for n, g in sc["by_work"].items():
        L.append(f"| {n} | {frac(g['found'])} | {_cf(g['complete'], judged)} | {_cf(g['faithful'], judged)} |")
    ho = sc["holdout"]
    if ho["cards"]:
        L += ["", f"## Sealed holdout ({ho['cards']} cards, reported separately)", "",
              f"Found {frac(ho['found'])}" + (f"; Complete {pct(**_nd(ho['complete']))}; Faithful {pct(**_nd(ho['faithful']))}"
                                              if ho["judged"] else "") + f"; errors {ho['errors']}"]
    L += ["", "## Grader health", ""] + [f"- {x.strip()}" for x in _health_lines(sc)]
    if sc["warnings"]:
        L += ["", "## Warnings", ""] + [f"- {w}" for w in sc["warnings"]]
    return "\n".join(L) + "\n"


def _cf(f: dict[str, float], judged: bool) -> str:
    return f"{frac(f)} ({pct(**_nd(f))})" if judged else "-"


# --------------------------------------------------------------------------- failures.md


def render_failures_md(sc: dict[str, Any]) -> str:
    L = [f"# Failures {sc['run']['run_id']}", ""]
    if sc["trust"]["label"] != "TRUSTED" and sc["main"]["judged"]:
        L += [f"**Judged checks (J1-J5, M9, M13) are {sc['trust']['label']}**: " + "; ".join(sc["trust"]["reasons"]), ""]
    def failed(c: dict[str, Any]) -> bool:  # mechanical-only cards have no fully_passing: any failed check counts
        return bool(c["error"] or c["fully_passing"] is False or (c["fully_passing"] is None and c.get("failed_checks")))

    main = [c for c in sc["cards"] if not c["holdout"] and failed(c)]
    L.append(f"{len(main)} main card(s) did not fully pass." + (
        "" if sc["main"]["judged"] else " (Mechanical only: judged checks were not run.)"))
    for c in main:
        d = c.get("detail", {})
        L += ["", f"## {c['card_id']} · {c['author']} · {c['work']}", "",
              f"Question: {d.get('question')}"]
        if d.get("premise"):
            L.append(f"False premise: {d['premise']}")
        e = d.get("expected", {})
        L.append(f"Expected location: {e.get('author')}, {e.get('work')}, {e.get('locator')}")
        L += ["", "Top retrieved:"]
        top = d.get("top_retrieved") or []
        L += [f"- #{t['rank']} {t['author']}, {t['work']}, {t['locator']}" for t in top] or ["- (none)"]
        L += ["", "Agora's answer:", "", f"> {(d.get('answer') or '(no answer)').replace(chr(10), chr(10) + '> ')}", "",
              "Failed checks:"]
        L += [f"- {f['check']}: {f['detail']}" for f in c["failures"]] or ["- (none recorded)"]
    hold = [c for c in sc["cards"] if c["holdout"] and failed(c)]
    if hold:
        L += ["", "## Sealed holdout cards (details hidden)", ""]
        L += [f"- {c['card_id']}: {', '.join(c['failed_checks']) or 'failed'}" for c in hold]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- compare


def _consistency(sc: dict[str, Any]) -> float | None:
    co = (sc["health"] or {}).get("consistency")
    return (co["agreed"] / co["sampled"]) if co and co.get("sampled") else None


def main_card_ids(sc: dict[str, Any]) -> frozenset[str]:
    return frozenset(c["card_id"] for c in sc["cards"] if not c["holdout"])


def _restrict(sc: dict[str, Any], ids: frozenset[str] | set[str]) -> dict[str, Any]:
    return scoring.compute_metrics([c for c in sc["cards"] if c["card_id"] in ids and not c["holdout"]])


def compare_scorecards(a: dict[str, Any], b: dict[str, Any], force: bool = False) -> dict[str, Any]:
    ra, rb = a["run"], b["run"]
    res: dict[str, Any] = {"ok": True, "error": None, "notes": [], "rows": [], "a": ra["run_id"], "b": rb["run_id"]}
    if ra.get("textnorm_version") != rb.get("textnorm_version"):
        res.update(ok=False, error="runs use different textnorm versions and are not comparable")
        return res
    ma, mb = a["main"], b["main"]
    ia, ib = main_card_ids(a), main_card_ids(b)
    same_sheet = ra["sheet_version"] == rb["sheet_version"]
    if not same_sheet or ia != ib:
        shared = ia & ib
        why = (f"different sheets ({ra['sheet_version']} vs {rb['sheet_version']})" if not same_sheet
               else f"different card sets ({len(ia)} vs {len(ib)} cards, e.g. a --limit or --author run)")
        if not force:
            res.update(ok=False, error=f"runs cover {why}; use --force to compare only the {len(shared)} cards they share")
            return res
        if not shared:
            res.update(ok=False, error=f"runs cover {why} and share no cards")
            return res
        ma, mb = _restrict(a, shared), _restrict(b, shared)
        res["notes"].append(f"{why}: compared only {len(shared)} shared cards of {len(ia)}/{len(ib)}; "
                            "metrics recomputed for that subset")
    judged_ok = ra.get("grader_version") == rb.get("grader_version") and ma["judged"] and mb["judged"]
    if ra.get("grader_version") != rb.get("grader_version"):
        if force:
            judged_ok = bool(ma["judged"] and mb["judged"])
            res["notes"].append(f"grader versions differ ({ra.get('grader_version')} vs {rb.get('grader_version')}): "
                                "judged differences are not like-for-like (--force)")
        else:
            res["notes"].append(f"grader versions differ ({ra.get('grader_version')} vs {rb.get('grader_version')}): "
                                "judged metrics not compared (use --force)")
    cons = [x for x in (_consistency(a), _consistency(b)) if x is not None]
    c = min(cons) if cons else None

    def add(key: str, label: str, va: float, vb: float, unit: str, judged: bool, noise: bool | None) -> None:
        res["rows"].append({"key": key, "label": label, "a": va, "b": vb, "delta": vb - va, "unit": unit,
                            "judged": judged, "noise": noise})

    def card_noise(d: float) -> bool:
        return abs(d) <= 1

    fa, fb = ma["found"]["n"], mb["found"]["n"]
    add("found", "Found", fa, fb, "", False, card_noise(fb - fa))
    ra_, rb_ = ma["evidence_recall"]["mean"], mb["evidence_recall"]["mean"]
    if ra_ is not None and rb_ is not None:
        n = max(mb["evidence_recall"]["n"], 1)
        add("evidence_recall", "Evidence recall (pts)", 100 * ra_, 100 * rb_, "", False, abs(rb_ - ra_) * n <= 1)
    ca, cb = ma["citations"], mb["citations"]
    add("cited_block", "Cited right paragraph", ca["cited_block"]["n"], cb["cited_block"]["n"], "", False,
        card_noise(cb["cited_block"]["n"] - ca["cited_block"]["n"]))
    for k in ("trivial", "invalid_ids", "label_mismatches", "no_citations"):
        add(k, k.replace("_", " "), ca[k], cb[k], "", False, card_noise(cb[k] - ca[k]))
    add("errors", "Errors", ma["errors"], mb["errors"], "", False, card_noise(mb["errors"] - ma["errors"]))
    if judged_ok:
        add("complete", "Complete (points)", ma["complete"]["n"], mb["complete"]["n"], " points", True,
            abs(mb["complete"]["n"] - ma["complete"]["n"]) <= 1
            or (c is not None and abs(mb["complete"]["n"] - ma["complete"]["n"]) < (1 - c) * mb["complete"]["d"]))
        d = mb["faithful"]["n"] - ma["faithful"]["n"]
        add("faithful", "Faithful (claims)", ma["faithful"]["n"], mb["faithful"]["n"], " claims", True,
            c is not None and abs(d) < (1 - c) * mb["faithful"]["d"])
        d = mb["fully_passing"]["n"] - ma["fully_passing"]["n"]
        add("fully_passing", "Fully passing cards", ma["fully_passing"]["n"], mb["fully_passing"]["n"], "", True,
            card_noise(d) or (c is not None and abs(d) < (1 - c) * mb["fully_passing"]["d"]))
        for k, label in (("uncited", "Uncited claims"), ("unmapped", "Unmapped citations")):
            va, vb = ma["support_counts"].get(k, 0), mb["support_counts"].get(k, 0)
            add(k, label, va, vb, "", True, card_noise(vb - va))
        add("wrongful_refusals", "Wrongful refusals", ma["behaviour"]["wrongful_refusals"],
            mb["behaviour"]["wrongful_refusals"], "", True,
            card_noise(mb["behaviour"]["wrongful_refusals"] - ma["behaviour"]["wrongful_refusals"]))
    return res


def brief(cmp: dict[str, Any]) -> str:
    parts = []
    for r in cmp["rows"]:
        if r["key"] in ("found", "complete", "faithful"):
            noise = " (within noise)" if r["noise"] else ""
            unit = r["unit"] or ""
            parts.append(f"{r['label'].split(' ')[0]} {signed(r['delta'], unit)}{noise}")
    return " · ".join(parts) or "no comparable metrics"


def render_compare(cmp: dict[str, Any]) -> str:
    if not cmp["ok"]:
        return f"integrity compare: {cmp['error']}\n"
    L = [f"COMPARE  {cmp['a']}  ->  {cmp['b']}", ""]
    for n in cmp["notes"]:
        L.append(f"note: {n}")
    if cmp["notes"]:
        L.append("")
    L.append(f"  {'metric':<26}{cmp['a']:>20}{cmp['b']:>20}   change")
    for r in cmp["rows"]:
        noise = "  (within noise)" if r["noise"] else ""
        L.append(f"  {r['label']:<26}{num(r['a']):>20}{num(r['b']):>20}   {signed(r['delta'], r['unit'])}{noise}")
    return "\n".join(L) + "\n"
