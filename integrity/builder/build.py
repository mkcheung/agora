"""Build orchestration (plan section 7): slot plan -> draft -> checks -> redraw within the bin -> flags and
advisory -> batch directory (section 5.3)."""

from __future__ import annotations

import contextlib
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from integrity.builder import attribution, checks, drafter, eligibility, sampler
from integrity.builder.corpus import (
    Corpus,
    CorpusError,
    Paragraph,
    QuoteIndex,
    load_corpus,
)
from integrity.common import sheets, storage, textnorm
from integrity.common.llm import ModelAuthError, ModelClient
from integrity.common.schema import (
    Anchor,
    BatchRecord,
    Card,
    CheckFailure,
    DiscardedDraft,
    Provenance,
    Review,
    SlotPlanEntry,
    dump,
    make_card_id,
    skeleton_sha256,
)
from integrity.common.settings import Settings

CREDENTIAL_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
MAX_CONSECUTIVE_CALL_ERRORS = 3


class BuildError(Exception):
    """A build problem with the CLI exit code to use (1 usage, 4 configuration/credentials, 5 run failed)."""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class BatchSummary:
    batch_id: str | None
    seed: int
    dry_run: bool
    corpus_version: str | None
    plan: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[dict[str, str]] = field(default_factory=list)  # dry run: rendered prompts per slot
    filled: int = 0
    unfilled: list[str] = field(default_factory=list)
    discarded: int = 0
    discarded_by_reason: dict[str, int] = field(default_factory=dict)
    flags: dict[str, int] = field(default_factory=dict)
    batch_dir: str | None = None
    warnings: list[str] = field(default_factory=list)
    aborted: str | None = None

    def format(self) -> str:
        lines = []
        head = "DRY RUN (no model calls)" if self.dry_run else f"BATCH {self.batch_id}"
        lines.append(f"{head}  seed {self.seed}  corpus {self.corpus_version}")
        lines.append(f"{'SLOT':<44} {'AUTHOR':<17} {'WORK':<30} {'POS':>4}  LOCATOR")
        for r in self.plan:
            lines.append(
                f"{r['slot'][:44]:<44} {r['author'][:17]:<17} {r['work'][:30]:<30} {r['position']:>4}  {r['locator']}"
            )
        if self.dry_run:
            lines.append(f"{len(self.plan)} slots planned; {len(self.prompts)} prompts rendered; no files written.")
            return "\n".join(lines)
        lines.append("")
        lines.append(f"filled {self.filled}/{len(self.plan)} slots; unfilled: {', '.join(self.unfilled) or '-'}")
        lines.append(
            f"discarded {self.discarded}: "
            + (", ".join(f"{k}={v}" for k, v in sorted(self.discarded_by_reason.items())) or "-")
        )
        lines.append("flags: " + (", ".join(f"{k}={v}" for k, v in sorted(self.flags.items())) or "-"))
        for w in self.warnings:
            lines.append(f"warning: {w}")
        if self.aborted:
            lines.append(f"ABORTED: {self.aborted}")
        if self.batch_dir:
            lines.append(f"batch written to {self.batch_dir}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- helpers


def check_credentials(settings: Settings, models: list[str]) -> None:
    """Exit-code-4 problem when an API key for a configured model provider is missing (never reads .env itself)."""
    for m in models:
        provider = m.split(":", 1)[0].lower()
        var = CREDENTIAL_ENV.get(provider)
        if var and not os.environ.get(var):
            raise BuildError(f"model {m!r} needs {var}, which is not set", 4)


def make_client(model_id: str, settings: Settings) -> ModelClient:
    from integrity.common.llm import LangChainModelClient

    return LangChainModelClient(
        model_id, temperature=settings.models.temperature, max_retries=settings.judge.max_retries
    )


def resolve_authors(requested: list[str] | None, corpus: Corpus) -> list[str] | None:
    if not requested:
        return None
    known = corpus.authors()
    out: list[str] = []
    for r in requested:
        hits = [a for a in known if a.casefold() == r.casefold()] or [
            a for a in known if a.split()[-1].casefold() == r.casefold()
        ]
        if not hits:
            raise BuildError(f"unknown author {r!r}; the corpus has: {', '.join(known)}", 1)
        out.extend(h for h in hits if h not in out)
    return out


def plan_rows(slots: list[sampler.Slot]) -> list[dict[str, Any]]:
    return [
        {"slot": s.slot, "kind": s.kind, "author": s.author, "work": s.planned.work, "stratum": s.stratum,
         "bin": s.bin, "locator": s.planned.locator, "position": s.planned.position,
         "block_id": s.planned.block_id}
        for s in slots
    ]


def _published_question_skeletons(settings: Settings) -> set[str]:
    out: set[str] = set()
    with contextlib.suppress(Exception):  # SF10 is advisory; never block a build on it
        for v in sheets.list_versions(settings.data_dir):
            raw = sheets.load_sheet_raw(sheets.sheet_path(settings.data_dir, v))
            out.update(textnorm.skeleton(c.get("question", "")) for c in raw.get("cards", []))
    return out


def _now_iso(now: datetime | None = None) -> str:
    return storage.iso_z(now or storage.utc_now())


# --------------------------------------------------------------------------- build


def run_build(
    settings: Settings,
    *,
    count: int,
    false_premise: int = 0,
    sources: list[str] | None = None,
    authors: list[str] | None = None,
    seed: int | None = None,
    dry_run: bool = False,
    drafter_client: ModelClient | None = None,
    attribution_client: ModelClient | None = None,
    corpus: Corpus | None = None,
    options: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> BatchSummary:
    t0 = time.monotonic()
    seed = sampler.new_seed() if seed is None else seed
    if corpus is None:
        try:
            corpus = load_corpus(settings, sources)
        except CorpusError as e:
            raise BuildError(str(e), e.exit_code) from e
    author_names = resolve_authors(authors, corpus)
    used = eligibility.collect_used(settings.data_dir)
    verdicts = eligibility.evaluate(corpus.paragraphs, settings, used)
    eligible = eligibility.eligible_paragraphs(verdicts)
    slots = sampler.plan_slots(
        eligible, settings, count=count, false_premise=false_premise, seed=seed,
        authors=author_names, automatic_strata=bool(sources),
    )
    summary = BatchSummary(None, seed, dry_run, corpus.corpus_version, plan=plan_rows(slots),
                           warnings=list(used.warnings))
    if dry_run:
        for s in slots:
            kind = s.kind
            system, user = drafter.render(kind, s.planned, settings)
            summary.prompts.append({"slot": s.slot, "system": system, "user": user})
        return summary
    if not slots:
        raise BuildError("no slots could be planned: no eligible paragraphs match the request", 1)

    if drafter_client is None or (attribution_client is None and settings.build.attribution_advisory):
        needed = ([settings.models.drafter] if drafter_client is None else []) + (
            [settings.models.attribution]
            if attribution_client is None and settings.build.attribution_advisory else []
        )
        check_credentials(settings, needed)
        if drafter_client is None:
            drafter_client = make_client(settings.models.drafter, settings)
        if attribution_client is None and settings.build.attribution_advisory:
            attribution_client = make_client(settings.models.attribution, settings)

    batch_id = storage.new_batch_id(seed, now)
    bdir = storage.batch_dir(settings.data_dir, batch_id)
    bdir.mkdir(parents=True, exist_ok=True)
    summary.batch_id, summary.batch_dir = batch_id, str(bdir)

    prompts = {k: drafter.prompt_for(k) for k in ("passage", "false_premise") if any(s.kind == k for s in slots)}
    prompt_hashes = {pr.name: pr.sha256 for pr in prompts.values()}
    if attribution_client is not None:
        prompt_hashes[drafter.ADVISORY_PROMPT] = attribution.load_prompt(
            drafter.PROMPT_DIR / f"{drafter.ADVISORY_PROMPT}.md").sha256

    cards: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    entries: list[SlotPlanEntry] = []
    reasons: Counter = Counter()
    flag_counts: Counter = Counter()
    accepted_blocks: set[str] = set()
    accepted_positions: dict[str, set[int]] = {}  # work_id -> positions of accepted paragraphs (neighbour rule)
    nb = settings.build.neighbor_exclusion
    call_errors = 0
    quote_index = QuoteIndex(corpus.paragraphs)  # HC11, built once per build
    seen_questions = _published_question_skeletons(settings)  # SF10

    def write(status: str, extra: dict[str, Any] | None = None) -> None:
        rec = BatchRecord(
            batch_id=batch_id, seed=seed, created_at=_now_iso(now), options=options or {},
            config=settings.snapshot(), corpus_version=corpus.corpus_version, slots=entries,
            drafter_model=settings.models.drafter,
            attribution_model=settings.models.attribution if attribution_client is not None else None,
            prompt_hashes=prompt_hashes,
            timings={"elapsed_s": round(time.monotonic() - t0, 3)}, discard_counts=dict(reasons),
            status=status, filled=len(cards), unfilled=list(summary.unfilled), warnings=summary.warnings,
            **(extra or {}),
        )
        storage.write_jsonl_atomic(bdir / "cards.jsonl", cards)
        storage.write_jsonl_atomic(bdir / "discarded.jsonl", discarded)
        storage.atomic_write_json(bdir / "batch.json", dump(rec))

    write("in_progress")
    try:
        for slot in slots:
            entry = SlotPlanEntry(
                slot=slot.slot, stratum=slot.stratum, bin=slot.bin, author=slot.author,
                work=slot.planned.work, locator=slot.planned.locator, position=slot.planned.position,
            )
            entries.append(entry)
            kind = slot.kind
            pr = prompts[kind]
            done = False
            for attempt, cand in enumerate(slot.candidates, start=1):
                if cand.block_id in accepted_blocks:
                    entry.candidates_tried.append({"block_id": cand.block_id, "result": "skipped:used_in_batch"})
                    continue
                taken = accepted_positions.get(cand.work_id, ())
                if nb > 0 and any(abs(cand.position - q) <= nb for q in taken):
                    # build.neighbor_exclusion within the batch: counts as an attempt, no model call
                    reasons.update(["neighbor"])
                    discarded.append(dump(DiscardedDraft(
                        slot=slot.slot, block_id=cand.block_id, failed_checks=[CheckFailure(
                            check="neighbor", detail=f"within {nb} paragraphs of an accepted card in this batch")],
                    )) | {"attempt": attempt})
                    entry.candidates_tried.append(
                        {"block_id": cand.block_id, "result": "discarded", "failed": ["neighbor"]})
                    continue
                try:
                    outcome = drafter.draft(drafter_client, kind, cand, settings, pr)
                except ModelAuthError as e:
                    raise BuildError(f"the drafting model rejected its API key ({e})", 4) from e
                if outcome.draft is None:
                    fails = [CheckFailure(check="HC2", detail=outcome.error or "model error")]
                    reason_ids = ["model_call_error" if "call_error" in (outcome.error or "") else "model_output_error"]
                    call_errors = call_errors + 1 if reason_ids[0] == "model_call_error" else 0
                else:
                    call_errors = 0
                    hard = checks.run_hard_checks(outcome.draft, cand, settings, kind, quote_index)
                    fails = hard.failures
                    reason_ids = sorted({f.check for f in fails})
                if fails:
                    reasons.update(reason_ids)
                    discarded.append(dump(DiscardedDraft(
                        slot=slot.slot, block_id=cand.block_id, failed_checks=fails, raw_output=outcome.raw,
                    )) | {"attempt": attempt})
                    entry.candidates_tried.append(
                        {"block_id": cand.block_id, "result": "discarded", "failed": reason_ids})
                    if call_errors >= MAX_CONSECUTIVE_CALL_ERRORS:
                        raise BuildError(
                            f"{call_errors} consecutive model call failures; last: {outcome.error}", 5)
                    continue
                card = _make_card(
                    outcome.draft, hard.key_points, cand, kind, slot, attempt, batch_id, seed, settings,
                    pr, attribution_client, summary, now, seen_questions,
                )
                cards.append(dump(card))
                seen_questions.add(textnorm.skeleton(card.question))
                for f in card.flags:
                    flag_counts[f.split(":")[0]] += 1
                accepted_blocks.add(cand.block_id)
                accepted_positions.setdefault(cand.work_id, set()).add(cand.position)
                entry.candidates_tried.append({"block_id": cand.block_id, "result": "accepted"})
                done = True
                break
            if not done:
                summary.unfilled.append(slot.slot)
            write("in_progress")
    except BuildError as e:
        summary.aborted = str(e)
        write("aborted")
        summary.filled = len(cards)
        summary.discarded = len(discarded)
        summary.discarded_by_reason = dict(reasons)
        summary.flags = dict(flag_counts)
        raise
    except BaseException:
        write("aborted")
        raise
    write("complete")
    summary.filled = len(cards)
    summary.discarded = len(discarded)
    summary.discarded_by_reason = dict(reasons)
    summary.flags = dict(flag_counts)
    return summary


def _make_card(
    draft: drafter.DraftCard, key_points: list, p: Paragraph, kind: str, slot: sampler.Slot, attempt: int,
    batch_id: str, seed: int, settings: Settings, prompt, attribution_client: ModelClient | None,
    summary: BatchSummary, now: datetime | None, seen_questions: set[str] | None = None,
) -> Card:
    question = draft.question.strip()
    flags = checks.soft_flags(question, key_points, p, settings, seen_questions)
    advice = []
    if attribution_client is not None and settings.build.attribution_advisory:
        try:
            advice, _ = attribution.run_advisory(
                attribution_client, p, [(k.id, k.statement, k.quote) for k in key_points], settings)
        except ModelAuthError as e:
            raise BuildError(f"the attribution model rejected its API key; stopping so no card is stored "
                             f"without the speaker check ({e})", 4) from e
        except Exception as e:  # noqa: BLE001  the advisory never discards a card
            summary.warnings.append(f"attribution advisory failed for {slot.slot}: {e}")
        if any(a.speaker not in (None, "author_sincere") for a in advice):
            flags.append("attribution_advice")
    # de-duplicate, keeping order
    flags = list(dict.fromkeys(flags))
    return Card(
        card_id=make_card_id(p.block_id, kind, question),
        type=kind,  # type: ignore[arg-type]
        question=question,
        premise=(getattr(draft, "premise", None) or None) if kind == "false_premise" else None,
        expected_behavior="correct_premise" if kind == "false_premise" else "answer",
        key_points=key_points,
        anchor=Anchor(**p.anchor_fields(), skeleton_sha256=skeleton_sha256(p.text)),
        flags=flags,
        provenance=Provenance(
            batch_id=batch_id, slot=slot.slot, seed=seed, attempt=attempt,
            drafter_model=settings.models.drafter, drafter_prompt=prompt.name, drafter_prompt_sha256=prompt.sha256,
            attribution_model=settings.models.attribution if attribution_client is not None else None,
            attribution_advice=advice, drafted_at=_now_iso(now),
        ),
        review=Review(status="pending"),
    )
