"""Published answer sheets: list, load, verify, resolve (read-only) and a write-once writer.

Callers map SheetError to exit code 2 (``SheetError.exit_code``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from integrity import SCHEMA_VERSION
from integrity.common import storage
from integrity.common.schema import Sheet, SheetCounts, compute_counts, content_sha256

_FILE_RE = re.compile(r"^sheet-v(\d{3,})\.json$")


class SheetError(Exception):
    """Base class: no valid published answer sheet (exit code 2)."""

    exit_code = 2


class SheetNotFoundError(SheetError):
    pass


class SheetIntegrityError(SheetError):
    """The file is unreadable, fails validation, or its content hash does not match."""


def format_version(n: int) -> str:
    return f"v{n:03d}"


def parse_version(v: str | int) -> int:
    """'v002', 'V2', '2', 2 -> 2. 'latest' is not accepted here (use resolve)."""
    if isinstance(v, int):
        return v
    m = re.fullmatch(r"[vV]?(\d+)", str(v).strip())
    if not m:
        raise SheetNotFoundError(f"invalid sheet version {v!r} (expected e.g. v002 or latest)")
    return int(m.group(1))


def sheet_path(data_dir: str | Path, version: str | int) -> Path:
    return storage.sheets_dir(data_dir) / f"sheet-{format_version(parse_version(version))}.json"


def list_versions(data_dir: str | Path) -> list[str]:
    """Published versions in ascending order, e.g. ['v001', 'v002']. Does not verify them."""
    d = storage.sheets_dir(data_dir)
    if not d.is_dir():
        return []
    nums = sorted(int(m.group(1)) for p in d.iterdir() if (m := _FILE_RE.match(p.name)))
    return [format_version(n) for n in nums]


def latest_version(data_dir: str | Path) -> str | None:
    vs = list_versions(data_dir)
    return vs[-1] if vs else None


def resolve(data_dir: str | Path, version: str | int | None = "latest") -> tuple[str, Path]:
    """Resolve 'latest' (highest version) or an explicit version to (version, path)."""
    if version is None or str(version).lower() == "latest":
        v = latest_version(data_dir)
        if v is None:
            raise SheetNotFoundError(f"no published answer sheet found in {storage.sheets_dir(data_dir)}")
    else:
        v = format_version(parse_version(version))
    path = sheet_path(data_dir, v)
    if not path.is_file():
        raise SheetNotFoundError(f"answer sheet {v} not found at {path}")
    return v, path


def compute_content_sha256(
    cards: list[Any], *, version: str | None = None, parent: str | None = None, retired: list[Any] | None = None
) -> str:
    """Hash of {"version", "parent", "retired", "cards"}. ``note``, ``created_at``, ``added``, ``reanchored``,
    ``corpus`` and ``provenance`` are free text / derived and are NOT covered (editing them is allowed);
    ``counts`` is not hashed but is recomputed from the cards on load and must match."""
    return content_sha256(cards, version=version, parent=parent, retired=retired)


def _hash_of(raw: dict[str, Any]) -> str:
    return compute_content_sha256(
        raw["cards"], version=raw.get("version"), parent=raw.get("parent"), retired=raw.get("retired") or []
    )


def _check_counts(raw: dict[str, Any], name: str) -> None:
    try:
        expected = compute_counts(raw["cards"]).model_dump(mode="json")
        stored = raw.get("counts")
        stored = SheetCounts.model_validate(stored).model_dump(mode="json") if stored is not None else None
    except ValidationError as e:
        raise SheetIntegrityError(f"{name}: cards or counts fail schema validation: {e}") from e
    if stored != expected:
        raise SheetIntegrityError(f"{name}: counts mismatch (stored {stored}, recomputed from the cards {expected})")


def load_sheet_raw(path: str | Path) -> dict[str, Any]:
    """Read and verify one sheet file; returns the raw dict. Refuses on any mismatch."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SheetIntegrityError(f"{path.name}: cannot read sheet: {e}") from e
    if not isinstance(raw, dict) or not isinstance(raw.get("cards"), list):
        raise SheetIntegrityError(f"{path.name}: not an answer sheet (no cards list)")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise SheetIntegrityError(
            f"{path.name}: unsupported schema_version {raw.get('schema_version')!r} (expected {SCHEMA_VERSION})"
        )
    m = _FILE_RE.match(path.name)
    if m and raw.get("version") != format_version(int(m.group(1))):
        raise SheetIntegrityError(f"{path.name}: version field {raw.get('version')!r} does not match the file name")
    actual = _hash_of(raw)
    if actual != raw.get("content_sha256"):
        raise SheetIntegrityError(
            f"{path.name}: content_sha256 mismatch (file says {raw.get('content_sha256')!r}, version/parent/retired/"
            f"cards hash to {actual}); the sheet has been modified"
        )
    _check_counts(raw, path.name)
    return raw


def load_sheet(data_dir: str | Path, version: str | int | None = "latest") -> Sheet:
    """Load, hash-verify and schema-validate a published sheet."""
    _, path = resolve(data_dir, version)
    raw = load_sheet_raw(path)
    try:
        sheet = Sheet.model_validate(raw)
    except ValidationError as e:
        raise SheetIntegrityError(f"{path.name}: schema validation failed: {e}") from e
    bad = [c.card_id for c in sheet.cards if c.review.status != "approved"]
    if bad:
        raise SheetIntegrityError(f"{path.name}: cards that are not approved: {', '.join(bad)}")
    return sheet


def verify_sheet(data_dir: str | Path, version: str | int | None = "latest") -> Sheet:
    """Alias of load_sheet (loading always verifies)."""
    return load_sheet(data_dir, version)


def summarize_versions(data_dir: str | Path) -> list[dict[str, Any]]:
    """One row per published sheet; invalid ones get an 'error' key instead of failing the listing."""
    rows = []
    for v in list_versions(data_dir):
        try:
            s = load_sheet(data_dir, v)
            rows.append(
                {"version": v, "parent": s.parent, "created_at": s.created_at, "note": s.note,
                 "cards": s.counts.cards, "holdout": s.counts.holdout}
            )
        except SheetError as e:
            rows.append({"version": v, "error": str(e)})
    return rows


def seal_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    """Set content_sha256 on a sheet dict (cards must already be sorted by card_id) and return it."""
    sheet["content_sha256"] = _hash_of(sheet)
    return sheet


def write_sheet(data_dir: str | Path, sheet: dict[str, Any] | Sheet) -> Path:
    """Write a new sheet version: atomic, write-once, then read-only (0o444).

    Refuses to overwrite an existing version, and refuses a sheet whose hash is missing or wrong.
    """
    raw = sheet.model_dump(mode="json") if isinstance(sheet, Sheet) else dict(sheet)
    if raw.get("content_sha256") != _hash_of(raw):
        raise SheetIntegrityError("refusing to write a sheet whose content_sha256 does not match its version/parent/retired/cards")
    _check_counts(raw, "sheet")
    path = sheet_path(data_dir, raw["version"])
    try:
        storage.atomic_write_json(path, raw, overwrite=False, mode=0o444)
    except FileExistsError as e:
        raise SheetIntegrityError(f"{path.name} already exists; published sheets are never changed") from e
    return path


def append_changelog(data_dir: str | Path, entry: str) -> Path:
    """Append one human-readable entry to sheets/CHANGELOG.md."""
    path = storage.sheets_dir(data_dir) / "CHANGELOG.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    sep = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    storage.atomic_write_text(path, existing + sep + entry.rstrip("\n") + "\n\n")
    return path
