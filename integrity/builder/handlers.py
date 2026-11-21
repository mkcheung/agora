"""CLI handlers for Part A commands corpus and build (exit codes per plan section 3.2)."""

from __future__ import annotations

import argparse
import sys
from collections import Counter, OrderedDict

from integrity.builder import eligibility
from integrity.builder.build import BuildError, run_build
from integrity.builder.corpus import Corpus, CorpusError, load_corpus
from integrity.builder.strata import assign, author_strata
from integrity.common.settings import Settings


def corpus_tables(corpus: Corpus, settings: Settings, source: str | None = None) -> tuple[str, list[eligibility.Verdict]]:
    used = eligibility.collect_used(settings.data_dir)
    verdicts = eligibility.evaluate(corpus.paragraphs, settings, used)
    lines: list[str] = []
    n_chunks = sum(len(p.chunks) for p in corpus.paragraphs)
    n_el = sum(v.eligible for v in verdicts)
    lines.append(
        f"Corpus {corpus.corpus_version}: {len(corpus.paragraphs)} paragraphs ({n_chunks} chunks), "
        f"{n_el} eligible, {len(corpus.paragraphs) - n_el} excluded"
        + (f"  [source {source}]" if source else "")
    )
    for w in used.warnings:
        lines.append(f"warning: {w}")
    lines.append("")
    lines.append(f"{'AUTHOR':<18} {'WORK':<44} {'PARAS':>6} {'ELIGIBLE':>8} {'EXCLUDED':>8}")
    by_work: OrderedDict[tuple[str, str, str], list[eligibility.Verdict]] = OrderedDict()
    for v in verdicts:
        by_work.setdefault((v.paragraph.author, v.paragraph.work_id, v.paragraph.work), []).append(v)
    for (author, wid, work), vs in by_work.items():
        el = sum(v.eligible for v in vs)
        lines.append(f"{author:<18} {(work + ' (' + wid + ')')[:44]:<44} {len(vs):>6} {el:>8} {len(vs) - el:>8}")
    lines.append("")
    lines.append("EXCLUSIONS BY REASON (a paragraph can have several reasons)")
    lines.append(f"{'WORK':<40} " + " ".join(f"{r[3:]:>11}" for r in eligibility.REASON_IDS))
    for (_a, wid, _w), vs in by_work.items():
        c = eligibility.reason_counts(vs)
        lines.append(f"{wid[:40]:<40} " + " ".join(f"{c.get(r, 0):>11}" for r in eligibility.REASON_IDS))
    lines.append("")
    lines.append("STRATA")
    lines.append(f"{'AUTHOR':<18} {'STRATUM':<46} {'WEIGHT':>6} {'PARAS':>6} {'ELIGIBLE':>8}")
    rules_by_author = author_strata(settings, corpus.paragraphs)
    for author, rules in rules_by_author.items():
        tally: dict[str, list[int]] = {r.name: [0, 0] for r in rules}
        unmatched = [0, 0]
        for v in verdicts:
            if v.paragraph.author != author:
                continue
            name = assign(v.paragraph, rules)
            t = tally[name] if name else unmatched
            t[0] += 1
            t[1] += v.eligible
        for r in rules:
            lines.append(f"{author:<18} {r.name:<46} {r.weight:>6.4f} {tally[r.name][0]:>6} {tally[r.name][1]:>8}")
        if unmatched[0]:
            lines.append(f"{author:<18} {'(unmatched: not sampled)':<46} {'-':>6} {unmatched[0]:>6} {unmatched[1]:>8}")
    return "\n".join(lines), verdicts


def cmd_corpus(args: argparse.Namespace, settings: Settings) -> int:
    sources = [args.source] if getattr(args, "source", None) else None
    try:
        corpus = load_corpus(settings, sources)
    except CorpusError as e:
        print(f"integrity corpus: {e}", file=sys.stderr)
        return e.exit_code
    text, verdicts = corpus_tables(corpus, settings, args.source)
    print(text)
    if getattr(args, "excluded", None):
        try:
            rid = eligibility.normalize_reason(args.excluded)
        except ValueError as e:
            print(f"integrity corpus: {e}", file=sys.stderr)
            return 1
        n = args.show if getattr(args, "show", None) else 5
        hits = [v for v in verdicts if rid in v.reasons]
        print(f"\n{rid}: {len(hits)} paragraphs; showing {min(n, len(hits))}")
        for v in hits[:n]:
            p = v.paragraph
            print(f"  {p.locator}  [{p.work_id}]  {v.detail.get(rid, '')}")
            print(f"    {p.text[:200]!r}")
    return 0


def cmd_build(args: argparse.Namespace, settings: Settings) -> int:
    count = args.count if args.count is not None else settings.build.default_count
    fp = args.false_premise if args.false_premise is not None else settings.build.default_false_premise
    if not 0 <= count <= 200:
        print(f"integrity build: --count must be between 0 and 200 (got {count})", file=sys.stderr)
        return 1
    if not 0 <= fp <= 50:
        print(f"integrity build: --false-premise must be between 0 and 50 (got {fp})", file=sys.stderr)
        return 1
    try:
        summary = run_build(
            settings, count=count, false_premise=fp, sources=args.source, authors=args.author, seed=args.seed,
            dry_run=args.dry_run,
            options={"count": args.count, "false_premise": args.false_premise, "sources": args.source,
                     "authors": args.author, "dry_run": args.dry_run},
        )
    except BuildError as e:
        print(f"integrity build: {e}", file=sys.stderr)
        return e.exit_code
    print(summary.format())
    if args.dry_run and summary.prompts:
        first = summary.prompts[0]
        print(f"\n--- rendered prompt for slot {first['slot']} (system) ---\n{first['system']}")
        print(f"\n--- (user) ---\n{first['user']}")
    if not args.dry_run and summary.filled == 0:
        return 5
    return 0


__all__ = ["Counter", "cmd_build", "cmd_corpus"]
