"""Python API for the quiz (plan section 9.9): run_quiz(), regrade(), load_scorecard()."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from integrity import MODULE_VERSION, TEXTNORM_VERSION
from integrity.cli import apply_env_file
from integrity.common import llm, sheets, storage
from integrity.common.llm import ModelClient
from integrity.common.schema import Card, Sheet
from integrity.common.settings import Settings, load_settings
from integrity.quiz import preflight as pf
from integrity.quiz import report, runner, scorecard
from integrity.quiz.grading import health
from integrity.quiz.grading.judge import Judge
from integrity.quiz.grading.pipeline import grade_run

ProgressFn = Callable[[dict[str, Any]], None]


@dataclass
class RunSummary:
    exit_code: int
    run_id: str | None = None
    run_dir: Path | None = None
    message: str = ""
    sheet_version: str | None = None
    trust: str | None = None
    warnings: list[str] = field(default_factory=list)
    scorecard: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


# --------------------------------------------------------------------------- run lookup


def list_run_ids(data_dir: Path) -> list[str]:
    runs = data_dir / "runs"
    if not runs.is_dir():
        return []
    return sorted(p.name for p in runs.iterdir() if p.is_dir() and p.name.startswith("r-") and (p / "run.json").exists())


def resolve_run(data_dir: Path, run_id: str | None) -> str:
    ids = list_run_ids(data_dir)
    if not run_id or run_id == "latest":
        done = [r for r in ids if (data_dir / "runs" / r / "scorecard.json").exists()]
        if not done:
            raise FileNotFoundError(f"no completed runs in {data_dir / 'runs'}")
        return done[-1]
    if run_id not in ids:
        raise FileNotFoundError(f"run {run_id} not found in {data_dir / 'runs'}")
    return run_id


def load_scorecard(run_id: str = "latest", *, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    rid = resolve_run(settings.data_dir, run_id)
    path = storage.run_dir(settings.data_dir, rid) / "scorecard.json"
    if not path.exists():
        raise FileNotFoundError(f"run {rid} has no scorecard.json (it did not finish)")
    try:
        return storage.read_json(path)
    except ValueError as e:
        raise ValueError(f"run {rid}: scorecard.json is corrupt ({e})") from e


# --------------------------------------------------------------------------- shared helpers


def _unique_run_id(data_dir: Path, now: datetime | None = None) -> str:
    base = now or storage.utc_now()
    from datetime import timedelta
    while True:
        rid = storage.new_run_id(base)
        if not (data_dir / "runs" / rid).exists():
            return rid
        base += timedelta(seconds=1)


def _make_judge(settings: Settings, client: ModelClient | None) -> Judge:
    if client is None:
        from integrity.common.llm import LangChainModelClient
        client = LangChainModelClient(settings.models.judge, temperature=settings.models.temperature,
                                      max_retries=settings.judge.max_retries)
    return Judge.from_settings(client, settings)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _vs_previous(settings: Settings, sc: dict[str, Any]) -> dict[str, Any] | None:
    rid = sc["run"]["run_id"]
    for prev in reversed(list_run_ids(settings.data_dir)):
        if prev >= rid:
            continue
        p = storage.run_dir(settings.data_dir, prev) / "scorecard.json"
        if not p.exists():
            continue
        try:
            old = storage.read_json(p)
            if old["run"].get("sheet_version") != sc["run"].get("sheet_version"):
                continue
            if report.main_card_ids(old) != report.main_card_ids(sc):  # only an identical card set is comparable
                continue
            cmp = report.compare_scorecards(old, sc)
        except (ValueError, KeyError, TypeError):
            continue
        return {"run_id": prev, "text": report.brief(cmp)} if cmp["ok"] else None
    return None


def _grade_and_write(
    *, settings: Settings, rdir: Path, run_json: dict[str, Any], sheet: Sheet, cards: list[Card],
    records: list[dict[str, Any]], judge: Judge | None, warnings: list[str], on_progress: ProgressFn | None,
) -> dict[str, Any]:
    cal = health.calibration_summary(settings.data_dir, judge.grader_version) if judge else None
    graded = grade_run(sheet=sheet, cards=cards, records=records, judge=judge, settings=settings,
                       calibration=cal, on_progress=on_progress)
    storage.write_jsonl_atomic(rdir / "grades.jsonl", graded.grades)
    info = run_json.get("agora_info") or {}
    run_json["finished_at"] = storage.iso_z(storage.utc_now())
    meta = {
        "run_id": run_json["run_id"], "started_at": run_json["started_at"], "finished_at": run_json["finished_at"],
        "sheet_version": run_json["sheet_version"], "grader_version": run_json["grader_version"],
        "judge_model": run_json["judge_model"], "mechanical_only": run_json["options"].get("mechanical_only", False),
        "entrypoint": run_json["entrypoint"], "namespace": run_json["namespace"] or info.get("namespace"),
        "agora_model": info.get("model"), "k": info.get("k"), "git_commit": run_json["git_commit"],
        "git_dirty": run_json["git_dirty"], "textnorm_version": TEXTNORM_VERSION, "module_version": MODULE_VERSION,
        "source_run": run_json.get("source_run"), "files_dir": _rel(rdir, settings.project_root),
    }
    sc = scorecard.build_scorecard(run=meta, sheet=sheet, cards=cards, grades=graded.grades, raw=records,
                                   health=graded.health, never_retrieved=graded.never_retrieved,
                                   warnings=list(warnings))
    sc["vs_previous"] = _vs_previous(settings, sc)
    storage.atomic_write_json(rdir / "scorecard.json", sc)
    storage.atomic_write_text(rdir / "scorecard.md", report.render_scorecard_md(sc))
    storage.atomic_write_text(rdir / "failures.md", report.render_failures_md(sc))
    run_json["status"] = "complete"
    storage.atomic_write_json(rdir / "run.json", run_json)
    storage.append_jsonl(settings.data_dir / "runs" / "index.jsonl", {
        "run_id": meta["run_id"], "sheet_version": meta["sheet_version"], "grader_version": meta["grader_version"],
        "headline": scorecard.headline(sc)})
    return sc


def _summary(code: int, sc: dict[str, Any] | None, rid: str, rdir: Path, sheet_version: str | None,
             message: str = "", warnings: list[str] | None = None) -> RunSummary:
    return RunSummary(code, rid, rdir, message, sheet_version, sc["trust"]["label"] if sc else None,
                      warnings or [], sc)


# --------------------------------------------------------------------------- run_quiz


def run_quiz(
    sheet: str | None = None, limit: int | None = None, authors: str | Sequence[str] | None = None,
    cards: Sequence[str] | None = None, agora: str | None = None, namespace: str | None = None,
    mechanical_only: bool = False, resume: str | None = None, strict: bool = False,
    on_progress: ProgressFn | None = None, *, settings: Settings | None = None,
    model_client: ModelClient | None = None,
) -> RunSummary:
    settings = settings or load_settings()
    apply_env_file(settings)
    llm.apply_tracing_setting(settings.models.tracing)
    strict = strict or settings.quiz.strict
    authors_l = [authors] if isinstance(authors, str) else (list(authors) if authors else None)
    data_dir = settings.data_dir
    prior: dict[str, Any] | None = None
    if resume:
        try:
            resume = resolve_run(data_dir, resume)
        except FileNotFoundError as e:
            return RunSummary(pf.EXIT_USAGE, message=f"integrity quiz: {e}\n")
        try:
            prior = storage.read_json(storage.run_dir(data_dir, resume) / "run.json")
        except ValueError as e:
            return RunSummary(pf.EXIT_USAGE, message=f"integrity quiz: run {resume}: run.json is corrupt ({e})\n")
        if sheet and sheets.format_version(sheets.parse_version(sheet)) != prior["sheet_version"]:
            return RunSummary(pf.EXIT_USAGE, message=f"integrity quiz: run {resume} used sheet {prior['sheet_version']}, not {sheet}\n")
        sheet = prior["sheet_version"]

    pre = pf.run_preflight(settings, sheet=sheet, limit=limit, authors=authors_l, cards=cards, agora=agora,
                           namespace=namespace, mechanical_only=mechanical_only, strict=strict)
    if not pre.ok:
        return RunSummary(pre.exit_code, message=pre.message)
    try:
        assert pre.sheet is not None and pre.adapter is not None
        if prior and prior.get("sheet_content_sha256") != pre.sheet.content_sha256:
            return RunSummary(pf.EXIT_NO_SHEET, message=f"integrity quiz: sheet {pre.sheet.version} changed since run {resume}\n")
        try:
            judge = None if mechanical_only else _make_judge(settings, model_client)
        except Exception as e:  # noqa: BLE001
            return RunSummary(pf.EXIT_CONFIG, message=f"integrity quiz: cannot create the judge model client: {e}\n")
        rid = resume or _unique_run_id(data_dir)
        rdir = storage.run_dir(data_dir, rid)
        rdir.mkdir(parents=True, exist_ok=True)
        run_json: dict[str, Any] = prior or {
            "run_id": rid, "started_at": storage.iso_z(storage.utc_now()), "finished_at": None,
            "sheet_version": pre.sheet.version, "sheet_content_sha256": pre.sheet.content_sha256,
            "grader_version": judge.grader_version if judge else None,
            "judge_model": settings.models.judge if judge else None,
            "prompt_hashes": judge.prompt_hashes if judge else {}, "entrypoint": pre.adapter.spec,
            "namespace": namespace, "agora_info": None, "git_commit": pre.git_commit, "git_dirty": pre.git_dirty,
            "module_version": MODULE_VERSION, "textnorm_version": TEXTNORM_VERSION,
            "options": {"sheet": sheet, "limit": limit, "authors": authors_l, "cards": list(cards) if cards else None,
                        "agora": agora, "namespace": namespace, "mechanical_only": mechanical_only,
                        "resume": resume, "strict": strict},
            "preflight": {"checks": pre.checks, "warnings": pre.warnings}, "status": "running", "timeouts": [],
        }
        if prior:
            run_json.setdefault("resumed_at", []).append(storage.iso_z(storage.utc_now()))
            run_json["status"] = "running"
        storage.atomic_write_json(rdir / "run.json", run_json)

        try:
            out = runner.run_cards(pre.cards, pre.adapter, rdir, timeout_s=settings.quiz.timeout_s,
                                   retries=settings.quiz.retries, on_progress=on_progress)
        except storage.JsonlError as e:
            return RunSummary(pf.EXIT_USAGE, rid, rdir, f"integrity quiz: cannot resume run {rid}: {e}\n")
        run_json["timeouts"] = sorted(set(run_json.get("timeouts", [])) | set(out.timeouts))
        run_json["agora_info"] = run_json.get("agora_info") or out.first_info
        if out.interrupted:  # keep raw.jsonl (so --resume works), record the state, then let Ctrl-C stop the run
            run_json.update(status="interrupted", finished_at=storage.iso_z(storage.utc_now()))
            storage.atomic_write_json(rdir / "run.json", run_json)
            raise KeyboardInterrupt
        if out.aborted:
            run_json.update(status="aborted", finished_at=storage.iso_z(storage.utc_now()))
            storage.atomic_write_json(rdir / "run.json", run_json)
            return _summary(out.aborted[0], None, rid, rdir, pre.sheet.version, out.aborted[1])
        if out.all_errored:
            run_json.update(status="failed", finished_at=storage.iso_z(storage.utc_now()))
            storage.atomic_write_json(rdir / "run.json", run_json)
            return _summary(runner.EXIT_RUN_FAILED, None, rid, rdir, pre.sheet.version,
                            "integrity quiz: every card errored; see raw.jsonl\n")
        warnings = list(pre.warnings)
        if out.dropped_lines:
            warnings.append(f"resume: dropped {out.dropped_lines} incomplete line from raw.jsonl (the card was asked again)")
        model = (out.first_info or {}).get("model")
        if judge and model and pf.provider(model) == pf.provider(settings.models.judge) \
                and pf.provider(model) != pf.provider(settings.models.agora_model_hint):
            w = f"judge {settings.models.judge} is from the same provider family as Agora's answer model {model}"
            warnings.append(w)
            if strict:
                run_json.update(status="aborted", finished_at=storage.iso_z(storage.utc_now()))
                storage.atomic_write_json(rdir / "run.json", run_json)
                return _summary(pf.EXIT_CONFIG, None, rid, rdir, pre.sheet.version, f"integrity quiz: {w} (--strict).\n", warnings)
        sc = _grade_and_write(settings=settings, rdir=rdir, run_json=run_json, sheet=pre.sheet, cards=pre.sheet.cards,
                              records=out.records, judge=judge, warnings=warnings, on_progress=on_progress)
        # --strict needs a fully TRUSTED grader; "no controls ran" (UNVERIFIED) is not enough. NOT RUN (mechanical) is exempt.
        code = pf.EXIT_UNTRUSTED if strict and not mechanical_only and sc["trust"]["label"] != "TRUSTED" else 0
        return _summary(code, sc, rid, rdir, pre.sheet.version, warnings=sc["warnings"])
    finally:
        pre.release()


# --------------------------------------------------------------------------- regrade


def regrade(run_id: str, *, settings: Settings | None = None, model_client: ModelClient | None = None,
            on_progress: ProgressFn | None = None, env: dict[str, str] | None = None) -> RunSummary:
    """Grade a run's raw.jsonl again with the current grader into a NEW run directory. Makes no Agora calls."""
    settings = settings or load_settings()
    if env is None:  # an explicit env mapping (tests) is used as given
        apply_env_file(settings)
    llm.apply_tracing_setting(settings.models.tracing)
    data_dir = settings.data_dir
    try:
        src = resolve_run(data_dir, run_id)
    except FileNotFoundError as e:
        return RunSummary(pf.EXIT_USAGE, message=f"integrity regrade: {e}\n")
    sdir = storage.run_dir(data_dir, src)
    try:
        src_json = storage.read_json(sdir / "run.json")
        raw_lines, dropped = storage.read_jsonl_ex(sdir / "raw.jsonl", tolerate_torn_tail=True)
        raw = {r["card_id"]: r for r in raw_lines}
    except (ValueError, KeyError, TypeError) as e:
        return RunSummary(pf.EXIT_USAGE, message=f"integrity regrade: run {src} has corrupt files ({e})\n")
    if not raw:
        return RunSummary(pf.EXIT_USAGE, message=f"integrity regrade: run {src} has no raw answers\n")
    try:
        sheet = sheets.load_sheet(data_dir, src_json["sheet_version"])
    except sheets.SheetError as e:
        return RunSummary(pf.EXIT_NO_SHEET, message=f"integrity regrade: {e}\n")
    if src_json.get("sheet_content_sha256") != sheet.content_sha256:
        return RunSummary(pf.EXIT_NO_SHEET, message=f"integrity regrade: sheet {sheet.version} differs from the one run {src} used\n")
    environ = os.environ if env is None else env
    var = pf.KEY_ENV.get(pf.provider(settings.models.judge))
    if model_client is None and var and not environ.get(var):
        return RunSummary(pf.EXIT_CONFIG, message=f"integrity regrade: judge model {settings.models.judge} needs {var}\n")
    try:
        lock = storage.FileLock(storage.runs_lock_path(data_dir))
        lock.acquire()
    except (OSError, storage.LockError) as e:
        return RunSummary(pf.EXIT_CONFIG, message=f"integrity regrade: cannot start: {e}\n")
    try:
        try:
            judge = _make_judge(settings, model_client)
        except Exception as e:  # noqa: BLE001
            return RunSummary(pf.EXIT_CONFIG, message=f"integrity regrade: cannot create the judge model client: {e}\n")
        rid = _unique_run_id(data_dir)
        rdir = storage.run_dir(data_dir, rid)
        rdir.mkdir(parents=True, exist_ok=True)
        if dropped:
            storage.write_jsonl_atomic(rdir / "raw.jsonl", raw_lines)
        else:
            shutil.copyfile(sdir / "raw.jsonl", rdir / "raw.jsonl")
        run_json = dict(src_json)
        opts = dict(src_json.get("options", {}))
        opts["mechanical_only"] = False
        run_json.update(run_id=rid, started_at=storage.iso_z(storage.utc_now()), finished_at=None, source_run=src,
                        grader_version=judge.grader_version, judge_model=settings.models.judge,
                        prompt_hashes=judge.prompt_hashes, options=opts, status="running")
        run_json.pop("resumed_at", None)
        storage.atomic_write_json(rdir / "run.json", run_json)
        records = [raw[c.card_id] for c in sheet.cards if c.card_id in raw]
        sc = _grade_and_write(settings=settings, rdir=rdir, run_json=run_json, sheet=sheet, cards=sheet.cards,
                              records=records, judge=judge,
                              warnings=[f"dropped {dropped} incomplete line from the source raw.jsonl"] if dropped else [],
                              on_progress=on_progress)
        return _summary(0, sc, rid, rdir, sheet.version, warnings=sc["warnings"])
    finally:
        lock.release()
