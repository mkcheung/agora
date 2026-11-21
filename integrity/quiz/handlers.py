"""CLI handlers for Part B. Signature: cmd_X(args, settings) -> int."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from integrity.common.settings import Settings
from integrity.quiz import api, report


def _progress(event: dict[str, Any]) -> None:
    if event["event"] == "card_finished":
        status = "ok" if event["ok"] else "ERROR"
        print(f"[{event['index']}/{event['total']}] {event['card_id']} {status} ({event['latency_s']}s)", file=sys.stderr)
    elif event["event"] == "grading_started":
        print(f"grading {event['cards']} answers (this makes many judge calls and can take a while) ...", file=sys.stderr)
    elif event["event"] == "card_graded":
        print(f"[graded {event['index']}/{event['total']}] {event['card_id']} ({event['seconds']}s)", file=sys.stderr)
    elif event["event"] == "control_graded":
        print(f"[controls {event['index']}/{event['total']}] {event['kind']}", file=sys.stderr)
    elif event["event"] == "consistency_started":
        print(f"re-checking a sample of {event['items']} judge items for consistency ...", file=sys.stderr)


def _finish(s: api.RunSummary) -> int:
    if s.message:
        print(s.message, end="" if s.message.endswith("\n") else "\n", file=sys.stderr)
    if s.scorecard:
        print(report.render_terminal(s.scorecard), end="")
    return s.exit_code


def cmd_quiz(args: argparse.Namespace, settings: Settings) -> int:
    cards = [c for c in (args.cards or "").split(",") if c.strip()] or None
    s = api.run_quiz(sheet=args.sheet, limit=args.limit, authors=[args.author] if args.author else None, cards=cards,
                     agora=args.agora, namespace=args.namespace, mechanical_only=args.mechanical_only,
                     resume=args.resume, strict=args.strict, on_progress=_progress, settings=settings)
    return _finish(s)


def cmd_report(args: argparse.Namespace, settings: Settings) -> int:
    try:
        sc = api.load_scorecard(args.run_id, settings=settings)
    except (FileNotFoundError, ValueError) as e:
        print(f"integrity report: {e}", file=sys.stderr)
        return 1
    try:
        if args.format == "json":
            text = json.dumps(sc, indent=2, ensure_ascii=False) + "\n"
        elif args.format == "md":
            text = report.render_scorecard_md(sc)
        else:
            text = report.render_terminal(sc)
    except (KeyError, TypeError) as e:
        print(f"integrity report: the scorecard is malformed (missing {e})", file=sys.stderr)
        return 1
    print(text, end="")
    return 0


def cmd_compare(args: argparse.Namespace, settings: Settings) -> int:
    try:
        a = api.load_scorecard(args.run_a, settings=settings)
        b = api.load_scorecard(args.run_b, settings=settings)
    except (FileNotFoundError, ValueError) as e:
        print(f"integrity compare: {e}", file=sys.stderr)
        return 1
    try:
        cmp = report.compare_scorecards(a, b, force=args.force)
        text = report.render_compare(cmp)
    except (KeyError, TypeError) as e:
        print(f"integrity compare: a scorecard is malformed (missing {e})", file=sys.stderr)
        return 1
    print(text, end="", file=sys.stdout if cmp["ok"] else sys.stderr)
    return 0 if cmp["ok"] else 1


def cmd_regrade(args: argparse.Namespace, settings: Settings) -> int:
    return _finish(api.regrade(args.run_id, settings=settings, on_progress=_progress))


def cmd_calibrate(args: argparse.Namespace, settings: Settings) -> int:
    from integrity.quiz import calibrate

    try:
        return calibrate.calibrate(settings, args.run_id, args.n)
    except (FileNotFoundError, ValueError) as e:
        print(f"integrity calibrate: {e}", file=sys.stderr)
        return 1
