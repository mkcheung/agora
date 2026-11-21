"""CLI handlers for review, publish, retire and sheet check (lazy-imported by integrity/cli.py)."""

from __future__ import annotations

import argparse
import os
import sys

from integrity.common.settings import Settings


def cmd_review(args: argparse.Namespace, settings: Settings) -> int:
    from integrity.builder import review

    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    try:
        review.run_review(settings, getattr(args, "batch", None), color=color)
    except review.ReviewError as e:
        print(f"integrity review: {e}", file=sys.stderr)
        return e.exit_code
    return 0


def cmd_publish(args: argparse.Namespace, settings: Settings) -> int:
    from integrity.builder import publish

    try:
        r = publish.publish(settings, note=getattr(args, "note", None) or "")
    except publish.PublishError as e:
        print(f"integrity publish: {e}", file=sys.stderr)
        return e.exit_code
    c = r.sheet.counts
    print(f"published {r.version} ({r.path})")
    print(f"cards: {c.cards}  holdout: {c.holdout}  added: {len(r.added)}  retired: {len(r.retired)}  "
          f"re-anchored: {len(r.reanchored)}")
    print(f"content_sha256: {r.sheet.content_sha256}")
    return 0


def cmd_retire(args: argparse.Namespace, settings: Settings) -> int:
    from integrity.builder import publish

    try:
        version = publish.stage_retirement(settings, args.card_id, args.reason)
    except publish.PublishError as e:
        print(f"integrity retire: {e}", file=sys.stderr)
        return e.exit_code
    print(f"staged retirement of {args.card_id} (in {version}); it takes effect at the next publish")
    return 0


def cmd_sheet_check(args: argparse.Namespace, settings: Settings) -> int:
    from integrity.builder import maintain

    try:
        rep = maintain.run_check(settings)
        print(maintain.format_report(rep))
        counts = rep.counts()
        if counts["missing"] or counts["ambiguous"]:
            print(f"ATTENTION: {counts['missing']} missing and {counts['ambiguous']} ambiguous cards need a human "
                  "decision (retire, or fix the corpus); the exit code is still 0.")
        if not getattr(args, "apply", False):
            return 0
        res = maintain.apply_reanchoring(settings, rep)
    except maintain.MaintainError as e:
        print(f"integrity sheet check: {e}", file=sys.stderr)
        return e.exit_code
    for cid, why in res.failed:
        print(f"integrity sheet check: could not re-anchor {cid}:\n{why}", file=sys.stderr)
    if res.version is None:
        print("nothing to re-anchor: no sheet version published")
    else:
        print(f"published {res.version}: re-anchored {len(res.reanchored)} cards")
    return 1 if res.failed else 0
