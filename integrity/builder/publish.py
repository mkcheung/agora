"""Publish a new answer-sheet version and retire cards (plan section 7.9)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from integrity.builder.card_validation import (
    ValidateCard,
    format_failures,
    make_validator,
)
from integrity.common import sheets, storage
from integrity.common.schema import (
    Card,
    RetiredEntry,
    Sheet,
    SheetCorpus,
    SheetProvenance,
    SourceRef,
    compute_counts,
    dump,
)
from integrity.common.settings import Settings


class PublishError(Exception):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class PublishResult:
    version: str
    path: Path
    sheet: Sheet
    added: list[str]
    retired: list[RetiredEntry]
    reanchored: list[str]


def pending_retirements_path(data_dir: Path) -> Path:
    return storage.sheets_dir(data_dir) / "pending_retirements.json"


def read_pending_retirements(data_dir: Path) -> list[dict]:
    p = pending_retirements_path(data_dir)
    if not p.is_file():
        return []
    try:
        data = storage.read_json(p)
    except (ValueError, OSError) as e:
        raise PublishError(f"pending_retirements.json is corrupt ({str(e).splitlines()[0]})") from e
    return [r for r in data if isinstance(r, dict) and "card_id" in r] if isinstance(data, list) else []


def holdout_flag(card_id: str, percent: int) -> bool:
    return int(hashlib.sha256(card_id.encode("utf-8")).hexdigest(), 16) % 100 < percent


def _latest(data_dir: Path) -> Sheet | None:
    try:
        return sheets.load_sheet(data_dir, "latest")
    except sheets.SheetNotFoundError:
        return None
    except sheets.SheetError as e:
        raise PublishError(f"the latest published sheet is invalid: {e}", e.exit_code) from e


def _already_retired_ids(data_dir: Path) -> set[str]:
    """Card ids retired by any published version (the 'retired' lists of the sheets)."""
    ids: set[str] = set()
    for v in sheets.list_versions(data_dir):
        try:
            raw = sheets.load_sheet_raw(sheets.sheet_path(data_dir, v))
        except sheets.SheetError as e:
            raise PublishError(f"published sheet {v} is invalid: {e}", e.exit_code) from e
        ids.update(r.get("card_id") for r in raw.get("retired", []) if isinstance(r, dict))
    return ids


def _ever_published_ids(data_dir: Path) -> set[str]:
    ids: set[str] = set()
    for v in sheets.list_versions(data_dir):
        try:
            raw = sheets.load_sheet_raw(sheets.sheet_path(data_dir, v))
        except sheets.SheetError as e:
            raise PublishError(f"published sheet {v} is invalid: {e}", e.exit_code) from e
        ids.update(c["card_id"] for c in raw["cards"])
    return ids


def approved_unpublished(data_dir: Path, published: set[str]) -> list[Card]:
    """Approved cards from every batch whose id is not in any published sheet (oldest batch first)."""
    from integrity.builder.review import ReviewError, list_batches, load_batch_cards

    out: dict[str, Card] = {}
    for b in sorted(list_batches(data_dir)):
        try:
            batch_cards = load_batch_cards(data_dir, b)
        except ReviewError as e:
            raise PublishError(str(e)) from e
        for c in batch_cards:
            if c.review.status == "approved" and c.card_id not in published and c.card_id not in out:
                out[c.card_id] = c
    return list(out.values())


def stage_retirement(settings: Settings, card_id: str, reason: str) -> str:
    """Stage a retirement for the next publish. The card must be in the latest sheet."""
    try:
        storage.check_safe_id(card_id, "card id")
    except ValueError as e:
        raise PublishError(str(e)) from e
    if not reason.strip():
        raise PublishError("a retirement needs a non-empty --reason")
    latest = _latest(settings.data_dir)
    if latest is None:
        raise PublishError("no published answer sheet: nothing to retire from")
    if card_id not in {c.card_id for c in latest.cards}:
        raise PublishError(f"card {card_id} is not in the latest sheet ({latest.version})")
    pend = [r for r in read_pending_retirements(settings.data_dir) if r.get("card_id") != card_id]
    pend.append({"card_id": card_id, "reason": reason.strip(), "staged_at": storage.iso_z(storage.utc_now())})
    storage.atomic_write_json(pending_retirements_path(settings.data_dir), pend, mode=0o644)
    return latest.version


def _clear_pending(data_dir: Path, done: set[str]) -> None:
    left = [r for r in read_pending_retirements(data_dir) if r["card_id"] not in done]
    storage.atomic_write_json(pending_retirements_path(data_dir), left, mode=0o644)


def _provenance(cards: Iterable[Card]) -> tuple[SheetCorpus, SheetProvenance]:
    versions, sources, batches, prompts = set(), {}, set(), {}
    for c in cards:
        a, p = c.anchor, c.provenance
        if a.corpus_version:
            versions.add(a.corpus_version)
        if a.source_id:
            sources[(a.source_id, a.source_sha256, a.source_file)] = None
        if p.batch_id:
            batches.add(p.batch_id)
        if p.drafter_prompt and p.drafter_prompt_sha256:
            key = p.drafter_prompt
            if key in prompts and prompts[key] != p.drafter_prompt_sha256:
                key = f"{key}#{p.drafter_prompt_sha256[:8]}"
            prompts[key] = p.drafter_prompt_sha256
    refs = [
        SourceRef(file=f or f"{sid}.epub", sha256=sha)  # fall back to the id only for cards without source_file
        for sid, sha, f in sorted(sources, key=lambda t: (t[0], t[1] or "", t[2] or ""))
    ]
    return (SheetCorpus(corpus_versions=sorted(versions), sources=refs),
            SheetProvenance(batches=sorted(batches), drafter_prompts=dict(sorted(prompts.items()))))


def _changelog_entry(sheet: Sheet) -> str:
    c = sheet.counts
    lines = [
        f"## {sheet.version} ({sheet.created_at})",
        f"Parent: {sheet.parent or '-'}",
        f"Note: {sheet.note or '-'}",
        f"Cards: {c.cards} (holdout {c.holdout})",
        f"Added ({len(sheet.added)}): {', '.join(sheet.added) or '-'}",
        f"Retired ({len(sheet.retired)}): " + (", ".join(f"{r.card_id} ({r.reason})" for r in sheet.retired) or "-"),
        f"Re-anchored ({len(sheet.reanchored)}): {', '.join(sheet.reanchored) or '-'}",
    ]
    return "\n".join(lines)


def publish(
    settings: Settings,
    *,
    note: str = "",
    replacements: list[Card] | None = None,
    include_new: bool = True,
    apply_retirements: bool = True,
    validate_card: ValidateCard | None = None,
    now: Callable[[], datetime] | None = None,
) -> PublishResult:
    """Build, validate, write and verify the next sheet version. Raises PublishError on any refusal."""
    data_dir = settings.data_dir
    validate = validate_card or make_validator(settings)
    try:
        lock = storage.FileLock(storage.sheets_dir(data_dir) / ".publish.lock")
        lock.acquire()
    except storage.LockError as e:
        raise PublishError(f"another publish is running ({e})") from e
    try:
        latest = _latest(data_dir)
        by_id = {c.card_id: c for c in (latest.cards if latest else [])}
        published = _ever_published_ids(data_dir)

        retired: list[RetiredEntry] = []
        if apply_retirements:
            stale: list[str] = []
            already = None
            for r in read_pending_retirements(data_dir):
                if r["card_id"] not in by_id:
                    # Self-healing after a crash between writing a sheet and clearing the pending file:
                    # a card already retired by a published version is dropped; an unknown id is an error.
                    already = _already_retired_ids(data_dir) if already is None else already
                    if r["card_id"] in already:
                        print(f"note: pending retirement {r['card_id']} was already retired by a published "
                              "version; dropping it")
                        stale.append(r["card_id"])
                        continue
                    raise PublishError(f"pending retirement {r['card_id']} is not in the latest sheet")
                retired.append(RetiredEntry(card_id=r["card_id"], reason=r.get("reason", "")))
        retired_ids = {r.card_id for r in retired}
        if apply_retirements and stale:
            _clear_pending(data_dir, set(stale))

        reanchored: list[str] = []
        for rc in replacements or []:
            if rc.card_id not in by_id:
                raise PublishError(f"cannot re-anchor {rc.card_id}: not in the latest sheet")
            if rc.card_id in retired_ids:
                raise PublishError(f"card {rc.card_id} is both retired and re-anchored")
            rc = rc.model_copy(deep=True)
            rc.holdout = by_id[rc.card_id].holdout  # existing cards keep their flag
            by_id[rc.card_id] = rc
            reanchored.append(rc.card_id)

        new_cards = approved_unpublished(data_dir, published) if include_new else []
        for c in new_cards:
            c.holdout = holdout_flag(c.card_id, settings.publish.holdout_percent)

        if not new_cards and not retired and not reanchored:
            raise PublishError("nothing to publish: no newly approved cards, retirements or re-anchored cards")

        final = [c for cid, c in by_id.items() if cid not in retired_ids] + new_cards
        if not final:
            raise PublishError("refusing to publish an empty answer sheet")
        # Carried-over cards are not re-validated against the CURRENT settings (a tightened check would
        # otherwise block every publish); they are covered by the sheet content hash verified on load.
        to_validate = {c.card_id for c in new_cards} | set(reanchored)
        problems = []
        for c in final:
            if c.review.status != "approved":
                problems.append(f"{c.card_id}: review status is {c.review.status}, not approved")
            fails = validate(c) if c.card_id in to_validate else []
            if fails:
                problems.append(f"{c.card_id}:\n{format_failures(fails)}")
        if problems:
            raise PublishError("refusing to publish; cards failed validation:\n" + "\n".join(problems))

        final.sort(key=lambda c: c.card_id)
        version = sheets.format_version(sheets.parse_version(latest.version) + 1 if latest else 1)
        corpus, prov = _provenance(final)
        created = storage.iso_z(now() if now else storage.utc_now())
        sheet = Sheet(
            version=version, parent=latest.version if latest else None, created_at=created, note=note,
            counts=compute_counts(final), added=sorted(c.card_id for c in new_cards), retired=retired,
            reanchored=sorted(reanchored), corpus=corpus, provenance=prov,
        )
        raw = dump(sheet)
        raw["cards"] = [dump(c) for c in final]
        sheets.seal_sheet(raw)
        try:
            path = sheets.write_sheet(data_dir, raw)
            verified = sheets.verify_sheet(data_dir, version)
        except sheets.SheetError as e:
            raise PublishError(f"could not write the sheet: {e}", e.exit_code) from e
        cl = sheets.append_changelog(data_dir, _changelog_entry(verified))
        try:
            os.chmod(cl, 0o644)
        except OSError:
            pass
        if retired:
            _clear_pending(data_dir, {r.card_id for r in retired})
        return PublishResult(version=version, path=path, sheet=verified, added=verified.added,
                             retired=retired, reanchored=verified.reanchored)
    finally:
        lock.release()


def publish_with_replacements(
    settings: Settings,
    replacements: list[Card],
    *,
    note: str | None = None,
    include_new: bool = False,
    apply_retirements: bool = False,
    validate_card: ValidateCard | None = None,
    now: Callable[[], datetime] | None = None,
) -> PublishResult:
    """Publish the next version with ``replacements`` (re-anchored cards) replacing cards by card_id.

    Same path as ``publish``; the replaced ids are recorded in ``reanchored`` and keep their holdout flag.
    By default new approved cards and staged retirements are NOT swept in (sheet check --apply only
    re-anchors); pass include_new / apply_retirements to combine.
    """
    return publish(
        settings, note=note if note is not None else f"re-anchored {len(replacements)} cards",
        replacements=replacements, include_new=include_new, apply_retirements=apply_retirements,
        validate_card=validate_card, now=now,
    )
