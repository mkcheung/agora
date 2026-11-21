"""Preflight checks P1-P7 (plan section 9.1)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integrity.common import sheets, storage
from integrity.common.schema import Card, Sheet
from integrity.common.settings import Settings
from integrity.quiz.agora import CONTRACT_SUMMARY, AgoraAdapter, AgoraLoadError

EXIT_OK, EXIT_USAGE, EXIT_NO_SHEET, EXIT_AGORA, EXIT_CONFIG, EXIT_RUN_FAILED, EXIT_UNTRUSTED = range(7)

P1_MESSAGE = """integrity quiz: no published answer sheet found in integrity_data/sheets/.
The quiz grades Agora against an answer sheet, so it cannot run without one.
Create one first:
  python -m integrity build      # draft cards from the corpus
  python -m integrity review     # approve cards
  python -m integrity publish    # publish answer sheet v001
"""

KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def provider(model_id: str) -> str:
    return (model_id or "").split(":", 1)[0].strip().lower() if ":" in (model_id or "") else ""


def git_state(project_root: str | Path) -> tuple[str | None, bool | None]:
    """(commit, dirty) from git; (None, None) when git or the repository is unavailable."""
    def run(*args: str) -> str | None:
        try:
            r = subprocess.run(["git", *args], cwd=project_root, capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    if commit is None:
        return None, None
    status = run("status", "--porcelain")
    return commit.strip(), (bool(status.strip()) if status is not None else None)


@dataclass
class PreflightResult:
    exit_code: int = EXIT_OK
    message: str = ""
    sheet: Sheet | None = None
    cards: list[Card] = field(default_factory=list)
    adapter: AgoraAdapter | None = None
    lock: storage.FileLock | None = None
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    git_commit: str | None = None
    git_dirty: bool | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == EXIT_OK

    def release(self) -> None:
        if self.lock is not None:
            self.lock.release()


def scorable(card: Card) -> bool:
    if card.type == "false_premise":
        return bool(card.premise)
    return bool(card.key_points)


def select_cards(sheet: Sheet, authors: Sequence[str] | None, card_ids: Sequence[str] | None) -> list[Card]:
    cards = sorted(sheet.cards, key=lambda c: c.card_id)
    if authors:
        needles = [a.lower() for a in authors]
        cards = [c for c in cards if any(n == c.anchor.author.lower() or n in c.anchor.author.lower() for n in needles)]
    if card_ids:
        cards = [c for c in cards if c.card_id in set(card_ids)]
    return cards


def _fail(res: PreflightResult, code: int, message: str, check: str) -> PreflightResult:
    res.exit_code = code
    res.message = message
    res.checks[check] = {"ok": False, "detail": message.strip().splitlines()[0] if message.strip() else ""}
    res.release()
    return res


def run_preflight(
    settings: Settings,
    *,
    sheet: str | None = None,
    limit: int | None = None,
    authors: Sequence[str] | None = None,
    cards: Sequence[str] | None = None,
    agora: str | None = None,
    namespace: str | None = None,
    mechanical_only: bool = False,
    strict: bool = False,
    agora_model: str | None = None,
    env: Mapping[str, str] | None = None,
) -> PreflightResult:
    env = os.environ if env is None else env
    res = PreflightResult()
    data_dir = settings.data_dir
    if limit is not None and limit < 1:
        return _fail(res, EXIT_USAGE, f"integrity quiz: --limit must be at least 1 (got {limit}).\n", "P0")

    # P1
    if not sheets.list_versions(data_dir):
        return _fail(res, EXIT_NO_SHEET, P1_MESSAGE, "P1")
    try:
        version, _ = sheets.resolve(data_dir, sheet or "latest")
    except sheets.SheetError as e:
        return _fail(res, EXIT_NO_SHEET, f"integrity quiz: {e}\n", "P1")
    res.checks["P1"] = {"ok": True, "detail": version}

    # P2
    try:
        loaded = sheets.load_sheet(data_dir, version)
    except sheets.SheetError as e:
        return _fail(res, EXIT_NO_SHEET, f"integrity quiz: answer sheet {version} is not usable: {e}\n", "P2")
    chosen = select_cards(loaded, authors, cards)
    if cards:
        missing = sorted(set(cards) - {c.card_id for c in loaded.cards})
        if missing:
            return _fail(res, EXIT_USAGE, f"integrity quiz: cards not on sheet {version}: {', '.join(missing)}\n", "P2")
    n_scorable = sum(1 for c in chosen if scorable(c) and not c.holdout)
    if n_scorable < settings.quiz.min_cards:
        msg = (f"integrity quiz: sheet {version} has {n_scorable} scorable non-holdout cards after filters; "
               f"quiz.min_cards is {settings.quiz.min_cards}.\n")
        return _fail(res, EXIT_NO_SHEET, msg, "P2")
    res.sheet = loaded
    res.cards = [c for c in chosen if scorable(c)]
    if limit is not None:
        res.cards = res.cards[:limit]
    res.checks["P2"] = {"ok": True, "detail": f"{len(res.cards)} cards to run, {n_scorable} scorable non-holdout"}

    # P3: import and callability (the first card's result is validated by the runner)
    spec = agora or settings.seams.agora_entrypoint
    adapter = AgoraAdapter(spec, settings.project_root, namespace)
    try:
        adapter.load()
    except AgoraLoadError as e:
        return _fail(res, EXIT_AGORA, f"integrity quiz: {e}\n\n{CONTRACT_SUMMARY}\n", "P3")
    res.adapter = adapter
    res.checks["P3"] = {"ok": True, "detail": spec}

    # P4
    judge_model = settings.models.judge
    if not mechanical_only:
        var = KEY_ENV.get(provider(judge_model))
        if var and not env.get(var):
            return _fail(res, EXIT_CONFIG, f"integrity quiz: judge model {judge_model} needs {var}, which is not set.\n"
                         "Set it, or use --mechanical-only.\n", "P4")
    res.checks["P4"] = {"ok": True, "detail": "skipped (--mechanical-only)" if mechanical_only else judge_model}

    # P5
    res.checks["P5"] = {"ok": True, "detail": ""}
    if not mechanical_only:
        am = agora_model or settings.models.agora_model_hint
        if provider(am) and provider(am) == provider(judge_model):
            warn = (f"judge {judge_model} is from the same provider family as Agora's answer model {am}; "
                    "self-preference can inflate scores")
            res.warnings.append(warn)
            res.checks["P5"] = {"ok": False, "detail": warn}
            if strict:
                return _fail(res, EXIT_CONFIG, f"integrity quiz: {warn} (--strict).\n", "P5")

    # P6
    runs = data_dir / "runs"
    try:
        runs.mkdir(parents=True, exist_ok=True)
        if not os.access(runs, os.W_OK):
            raise OSError(f"{runs} is not writable")
        lock = storage.FileLock(storage.runs_lock_path(data_dir))
        lock.acquire()
    except (OSError, storage.LockError) as e:
        return _fail(res, EXIT_CONFIG, f"integrity quiz: cannot start a run: {e}\n", "P6")
    res.lock = lock
    res.checks["P6"] = {"ok": True, "detail": str(runs)}

    # P7 (informational)
    res.git_commit, res.git_dirty = git_state(settings.project_root)
    res.checks["P7"] = {"ok": True, "detail": f"{res.git_commit} dirty={res.git_dirty}"}
    return res
