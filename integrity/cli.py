"""Command line: ``python -m integrity <command>``.

Every command from plan section 3.2 is registered. Only ``sheet list`` and ``sheet show`` are
implemented in Phase P0; the rest exit 1 with "not implemented yet (Phase X)". Builder and quiz
code must be imported lazily, inside the handler of the chosen command.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from integrity import MODULE_VERSION
from integrity.common import llm, sheets
from integrity.common.settings import ConfigError, Settings, load_settings

EXIT_OK, EXIT_USAGE, EXIT_NO_SHEET, EXIT_AGORA, EXIT_CONFIG, EXIT_RUN_FAILED, EXIT_UNTRUSTED = range(7)


def _not_implemented(phase: str) -> Callable[[argparse.Namespace, Settings], int]:
    def handler(args: argparse.Namespace, settings: Settings) -> int:
        print(f"integrity {args.command_name}: not implemented yet (Phase {phase})", file=sys.stderr)
        return 1

    return handler


def _lazy(module: str, func: str, phase: str) -> Callable[[argparse.Namespace, Settings], int]:
    """Handler that imports ``module.func`` only when the command runs (keeps Part A and Part B apart).

    If the handler does not exist yet, the command exits 1 with the "not implemented" message.
    """

    def handler(args: argparse.Namespace, settings: Settings) -> int:
        import importlib

        try:
            fn = getattr(importlib.import_module(module), func)
        except (ModuleNotFoundError, AttributeError) as e:
            if isinstance(e, ModuleNotFoundError) and e.name not in (module, module.rpartition(".")[0]):
                raise  # a real missing dependency inside the handler module: do not hide it
            return _not_implemented(phase)(args, settings)
        return fn(args, settings)

    return handler


_B = "integrity.builder.handlers"          # corpus, build
_BS = "integrity.builder.handlers_sheet"   # review, publish, retire, sheet check
_Q = "integrity.quiz.handlers"


def apply_env_file(settings: Settings) -> None:
    """Load ``<project root>/.env`` into os.environ without overriding anything already set (so API keys that
    live only in .env are visible, and .env can never override INTEGRITY_* or a variable the user exported).
    Idempotent; a missing file or python-dotenv is not an error. The file's content is never printed.
    Under pytest the real project .env is not read (tests must not depend on the developer's keys) unless a test
    sets ALLOW_DOTENV_IN_TESTS=on."""
    if "PYTEST_CURRENT_TEST" in os.environ and os.environ.get("ALLOW_DOTENV_IN_TESTS") != "on":
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    path = Path(settings.project_root) / ".env"
    if path.is_file():
        load_dotenv(path, override=False)


# --------------------------------------------------------------------------- sheet list / show


def _cmd_sheet_list(args: argparse.Namespace, settings: Settings) -> int:
    rows = sheets.summarize_versions(settings.data_dir)
    if not rows:
        print(f"no published answer sheets in {settings.data_dir / 'sheets'}")
        return EXIT_OK
    print(f"{'VERSION':<8} {'PARENT':<8} {'CARDS':>5} {'HOLDOUT':>7}  {'CREATED':<20} NOTE")
    invalid = False
    for r in rows:
        if "error" in r:
            invalid = True
            print(f"{r['version']:<8} INVALID: {r['error']}")
            continue
        print(
            f"{r['version']:<8} {r['parent'] or '-':<8} {r['cards']:>5} {r['holdout']:>7}  "
            f"{r['created_at']:<20} {r['note']}"
        )
    return EXIT_NO_SHEET if invalid else EXIT_OK


HIDDEN = "[holdout: question and key points hidden; use --reveal-holdout]"


def _print_card(card: Any, reveal: bool, detail: bool) -> None:
    a = card.anchor
    tag = " [holdout]" if card.holdout else ""
    print(f"{card.card_id}  {card.type}{tag}  {a.author} | {a.work} | {a.locator}")
    if card.holdout and not reveal:
        print(f"    {HIDDEN}")
        return
    print(f"    Q: {card.question}")
    if card.premise:
        print(f"    premise: {card.premise}")
    for kp in card.key_points:
        print(f"    {kp.id}: {kp.statement}")
        if detail:
            print(f"        quote: {kp.quote!r}")
    if detail:
        print(f"    flags: {', '.join(card.flags) or '-'}")
        print(f"    passage: {a.text}")


def _cmd_sheet_show(args: argparse.Namespace, settings: Settings) -> int:
    try:
        sheet = sheets.load_sheet(settings.data_dir, args.version or "latest")
    except sheets.SheetError as e:
        print(f"integrity sheet show: {e}", file=sys.stderr)
        return e.exit_code
    reveal = args.reveal_holdout
    if args.card:
        card = next((c for c in sheet.cards if c.card_id == args.card), None)
        if card is None:
            print(f"integrity sheet show: card {args.card} not in {sheet.version}", file=sys.stderr)
            return EXIT_USAGE
        _print_card(card, reveal, detail=True)
        return EXIT_OK
    c = sheet.counts
    print(f"answer sheet {sheet.version}  (parent: {sheet.parent or '-'}, created {sheet.created_at})")
    if sheet.note:
        print(f"note: {sheet.note}")
    print(f"cards: {c.cards}  holdout: {c.holdout}  content_sha256: {sheet.content_sha256}")
    print("by author: " + ", ".join(f"{k}={v}" for k, v in sorted(c.by_author.items())))
    print("by type:   " + ", ".join(f"{k}={v}" for k, v in sorted(c.by_type.items())))
    print()
    for card in sheet.cards:
        _print_card(card, reveal, detail=False)
    return EXIT_OK


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m integrity",
        description="Measure how accurately Agora answers questions about its corpus.",
    )
    p.add_argument("--version", action="version", version=f"integrity {MODULE_VERSION}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name: str, help_: str, phase: str, handler: Callable | None = None) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.set_defaults(handler=handler or _not_implemented(phase), command_name=name)
        return sp

    sp = add("corpus", "[A] count paragraphs per author and work, eligibility and exclusions", "A1", _lazy(_B, "cmd_corpus", "A1"))
    sp.add_argument("--source", metavar="FILE")
    sp.add_argument("--excluded", metavar="REASON")
    sp.add_argument("--show", type=int, metavar="N")

    sp = add("build", "[A] sample paragraphs, draft and check cards, write a batch", "A3", _lazy(_B, "cmd_build", "A3"))
    sp.add_argument("--count", type=int, metavar="N")
    sp.add_argument("--false-premise", type=int, metavar="M", dest="false_premise")
    sp.add_argument("--source", action="append", metavar="FILE")
    sp.add_argument("--author", action="append", metavar="NAME")
    sp.add_argument("--seed", type=int, metavar="S")
    sp.add_argument("--dry-run", action="store_true", dest="dry_run")

    sp = add("review", "[A] interactive approval of pending drafts", "A4", _lazy(_BS, "cmd_review", "A4"))
    sp.add_argument("--batch", metavar="ID")

    sp = add("publish", "[A] publish a new answer-sheet version", "A5", _lazy(_BS, "cmd_publish", "A5"))
    sp.add_argument("--note", metavar="TEXT")

    sp = add("retire", "[A] mark a card for removal in the next publish", "A5", _lazy(_BS, "cmd_retire", "A5"))
    sp.add_argument("card_id", metavar="CARD_ID")
    sp.add_argument("--reason", required=True, metavar="TEXT")

    sheet = sub.add_parser("sheet", help="[shared] sheet list | show [VERSION] | check [--apply]: inspect and maintain answer sheets")
    ssub = sheet.add_subparsers(dest="sheet_command", metavar="<subcommand>", required=True)
    sp = ssub.add_parser("check", help="[A] check every card's anchor against the current corpus")
    sp.add_argument("--apply", action="store_true")
    sp.set_defaults(handler=_lazy(_BS, "cmd_sheet_check", "A6"), command_name="sheet check")
    sp = ssub.add_parser("list", help="[shared] list published sheets")
    sp.set_defaults(handler=_cmd_sheet_list, command_name="sheet list")
    sp = ssub.add_parser("show", help="[shared] show a published sheet (holdout cards hidden by default)")
    sp.add_argument("version", nargs="?", metavar="VERSION")
    sp.add_argument("--card", metavar="ID")
    sp.add_argument("--reveal-holdout", action="store_true", dest="reveal_holdout")
    sp.set_defaults(handler=_cmd_sheet_show, command_name="sheet show")

    sp = add("quiz", "[B] run the quiz against a published answer sheet", "B2", _lazy(_Q, "cmd_quiz", "B2"))
    sp.add_argument("--sheet", metavar="VERSION")
    sp.add_argument("--limit", type=int, metavar="N")
    sp.add_argument("--author", metavar="NAME")
    sp.add_argument("--cards", metavar="IDS")
    sp.add_argument("--agora", metavar="MOD:FUNC")
    sp.add_argument("--namespace", metavar="NS")
    sp.add_argument("--mechanical-only", action="store_true", dest="mechanical_only")
    sp.add_argument("--resume", metavar="RUN_ID")
    sp.add_argument("--strict", action="store_true")

    sp = add("report", "[B] print the scorecard of a previous run", "B6", _lazy(_Q, "cmd_report", "B6"))
    sp.add_argument("run_id", nargs="?", default="latest", metavar="RUN_ID|latest")
    sp.add_argument("--format", choices=["text", "md", "json"], default="text")

    sp = add("compare", "[B] show score differences between two runs", "B6", _lazy(_Q, "cmd_compare", "B6"))
    sp.add_argument("run_a", metavar="RUN_A")
    sp.add_argument("run_b", metavar="RUN_B")
    sp.add_argument("--force", action="store_true")

    sp = add("regrade", "[B] grade saved raw answers again with the current grader", "B6", _lazy(_Q, "cmd_regrade", "B6"))
    sp.add_argument("run_id", metavar="RUN_ID")

    sp = add("calibrate", "[B] check a sample of judge verdicts and store the agreement rate", "B5", _lazy(_Q, "cmd_calibrate", "B5"))
    sp.add_argument("run_id", nargs="?", metavar="RUN_ID")
    sp.add_argument("--n", type=int, default=5)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse exits 2 on usage errors; the module's usage-error code is 1
        code = e.code if isinstance(e.code, int) else 1
        return code if code == 0 else EXIT_USAGE
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"integrity: configuration error: {e}", file=sys.stderr)
        return e.exit_code
    apply_env_file(settings)  # before the tracing setting, so a .env file cannot switch tracing back on
    llm.apply_tracing_setting(settings.models.tracing)  # before any model import
    try:
        return args.handler(args, settings)
    except KeyboardInterrupt:
        print("integrity: interrupted (a quiz run can be continued with --resume RUN_ID)", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
