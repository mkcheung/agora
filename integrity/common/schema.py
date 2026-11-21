"""Pydantic v2 models for the full data model (plan section 5) and the Agora contract (section 4.2).

Records allow extra keys so that later phases can add fields without breaking older files.
Field names match the plan's JSON examples exactly.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from integrity import CONTRACT_VERSION, SCHEMA_VERSION, TEXTNORM_VERSION
from integrity.common import textnorm

# --------------------------------------------------------------------------- hashing helpers


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def skeleton_sha256(text: str) -> str:
    return sha256_hex(textnorm.skeleton(text))


def make_card_id(block_id: str, card_type: str, original_question: str) -> str:
    """"c-" + sha256(block_id + newline + type + newline + original question)[:10]"""
    return "c-" + sha256_hex(f"{block_id}\n{card_type}\n{original_question}")[:10]


def dump(model: BaseModel) -> dict[str, Any]:
    """JSON-ready dict of a model (the form written to disk and hashed)."""
    return model.model_dump(mode="json")


def content_sha256(
    cards: list[Any], *, version: str | None = None, parent: str | None = None, retired: list[Any] | None = None
) -> str:
    """Sheet content hash: sha256 of the canonical JSON of {"version", "parent", "retired", "cards"}.

    Cards and retired entries may be models or already-dumped dicts. Deliberately NOT covered (free text
    or derived): created_at, note, added, reanchored, corpus, provenance. ``counts`` is not hashed but is
    recomputed from the cards and compared on load (see common/sheets.py).
    """

    def d(x: Any) -> Any:
        return dump(x) if isinstance(x, BaseModel) else x

    return canonical_sha256({
        "version": version, "parent": parent,
        "retired": [d(r) for r in (retired or [])], "cards": [d(c) for c in cards],
    })


def _int_or_none(v: Any) -> Any:
    """Pinecone returns floats such as 2.0; convert integral numbers to int."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


class Rec(BaseModel):
    model_config = ConfigDict(extra="allow")


# --------------------------------------------------------------------------- 5.1 Card


class KeyPoint(Rec):
    id: str
    statement: str
    quote: str
    quote_model: str | None = None
    span: list[int] = Field(default_factory=lambda: [0, 0])
    chunk_ids: list[str] = Field(default_factory=list)


class ChunkRef(Rec):
    passage_id: str
    text: str


class Anchor(Rec):
    author: str
    work: str
    work_id: str
    source_id: str | None = None
    block_id: str
    locator: str
    chapter: int | None = None
    section: int | None = None
    paragraph: int | None = None
    position: int | None = None
    text: str
    chunks: list[ChunkRef] = Field(default_factory=list)
    skeleton_sha256: str | None = None
    context_before: str = ""
    context_after: str = ""
    corpus_version: str | None = None
    source_sha256: str | None = None
    source_file: str | None = None  # e.g. "pg3207-images-3.epub", from the corpus report manifest
    content_type: str | None = None
    # In the real corpus these are labels such as "Part I", "Book II", "Volume 1" (text), not numbers.
    part: str | None = None
    book: str | None = None
    volume: str | None = None
    heading: str | None = None
    chapter_title: str | None = None
    section_title: str | None = None

    @field_validator("part", "book", "volume", mode="before")
    @classmethod
    def _label(cls, v: Any) -> Any:
        return None if v is None else str(v)

    @field_validator("chapter", "section", "paragraph", "position", mode="before")
    @classmethod
    def _num(cls, v: Any) -> Any:
        return _int_or_none(v)


class AttributionAdvice(Rec):
    key_point_id: str | None = None
    speaker: Literal["author_sincere", "reported_view", "ironic", "unclear"] | None = None
    explanation: str = ""
    evidence: str = ""
    evidence_verified: bool | None = None


class Provenance(Rec):
    batch_id: str | None = None
    slot: str | None = None
    seed: int | None = None
    attempt: int | None = None
    drafter_model: str | None = None
    drafter_prompt: str | None = None
    drafter_prompt_sha256: str | None = None
    attribution_model: str | None = None
    attribution_advice: list[AttributionAdvice] = Field(default_factory=list)
    textnorm_version: int = TEXTNORM_VERSION
    drafted_at: str | None = None


class Review(Rec):
    status: Literal["pending", "approved", "rejected"] = "pending"
    reviewed_at: str | None = None
    edited: bool = False
    original: dict[str, Any] | None = None
    reject_reason: str | None = None
    notes: str = ""


class Card(Rec):
    card_id: str
    type: Literal["passage", "false_premise"] = "passage"
    question: str
    premise: str | None = None
    expected_behavior: Literal["answer", "correct_premise"] = "answer"
    key_points: list[KeyPoint] = Field(default_factory=list)
    anchor: Anchor
    holdout: bool = False
    flags: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    review: Review = Field(default_factory=Review)


# --------------------------------------------------------------------------- 5.2 Sheet


class SheetCounts(Rec):
    cards: int = 0
    holdout: int = 0
    by_author: dict[str, int] = Field(default_factory=dict)
    by_work: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)


class RetiredEntry(Rec):
    card_id: str
    reason: str = ""


class SourceRef(Rec):
    file: str
    sha256: str | None = None


class SheetCorpus(Rec):
    corpus_versions: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


class SheetProvenance(Rec):
    batches: list[str] = Field(default_factory=list)
    drafter_prompts: dict[str, str] = Field(default_factory=dict)


class Sheet(Rec):
    schema_version: int = SCHEMA_VERSION
    textnorm_version: int = TEXTNORM_VERSION
    version: str
    parent: str | None = None
    created_at: str = ""
    note: str = ""
    counts: SheetCounts = Field(default_factory=SheetCounts)
    added: list[str] = Field(default_factory=list)
    retired: list[RetiredEntry] = Field(default_factory=list)
    reanchored: list[str] = Field(default_factory=list)
    corpus: SheetCorpus = Field(default_factory=SheetCorpus)
    provenance: SheetProvenance = Field(default_factory=SheetProvenance)
    content_sha256: str = ""
    cards: list[Card] = Field(default_factory=list)


def compute_counts(cards: list[Card | dict[str, Any]]) -> SheetCounts:
    """Counts block for a sheet from its cards."""
    cs = [c if isinstance(c, Card) else Card.model_validate(c) for c in cards]
    counts = SheetCounts(cards=len(cs), holdout=sum(1 for c in cs if c.holdout))
    for c in cs:
        counts.by_author[c.anchor.author] = counts.by_author.get(c.anchor.author, 0) + 1
        counts.by_work[c.anchor.work] = counts.by_work.get(c.anchor.work, 0) + 1
        counts.by_type[c.type] = counts.by_type.get(c.type, 0) + 1
    return counts


# --------------------------------------------------------------------------- 5.3 Batch


class SlotPlanEntry(Rec):
    slot: str
    stratum: str | None = None
    bin: int | None = None
    author: str | None = None
    work: str | None = None
    locator: str | None = None
    position: int | None = None
    candidates_tried: list[Any] = Field(default_factory=list)


class BatchRecord(Rec):
    """batch.json"""

    batch_id: str
    seed: int
    created_at: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    corpus_version: str | None = None
    slots: list[SlotPlanEntry] = Field(default_factory=list)
    drafter_model: str | None = None
    attribution_model: str | None = None
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    timings: dict[str, Any] = Field(default_factory=dict)
    discard_counts: dict[str, int] = Field(default_factory=dict)


class CheckFailure(Rec):
    check: str
    detail: str = ""


class DiscardedDraft(Rec):
    """One line of discarded.jsonl."""

    slot: str | None = None
    block_id: str | None = None
    failed_checks: list[CheckFailure] = Field(default_factory=list)
    raw_output: Any = None


# --------------------------------------------------------------------------- 5.4 Run


class RunRecord(Rec):
    """run.json"""

    run_id: str
    started_at: str | None = None
    finished_at: str | None = None
    sheet_version: str | None = None
    sheet_content_sha256: str | None = None
    grader_version: str | None = None
    judge_model: str | None = None
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    entrypoint: str | None = None
    namespace: str | None = None
    agora_info: dict[str, Any] | None = None
    git_commit: str | None = None
    git_dirty: bool | None = None
    module_version: str | None = None
    textnorm_version: int = TEXTNORM_VERSION
    options: dict[str, Any] = Field(default_factory=dict)
    preflight: dict[str, Any] = Field(default_factory=dict)


class RawError(Rec):
    type: str
    message: str = ""


class RawRecord(Rec):
    """One line of raw.jsonl."""

    card_id: str
    question: str = ""
    started_at: str | None = None
    latency_s: float | None = None
    result: dict[str, Any] | None = None
    error: RawError | None = None


class JudgeCall(Rec):
    prompt_id: str
    input_sha256: str = ""
    output: Any = None
    evidence_ok: bool | None = None


class GradeRecord(Rec):
    """One line of grades.jsonl."""

    card_id: str
    is_control: bool = False
    control_kind: str | None = None
    mechanical: dict[str, Any] = Field(default_factory=dict)
    judged: dict[str, Any] = Field(default_factory=dict)
    judge_calls: list[JudgeCall] = Field(default_factory=list)


class RunIndexEntry(Rec):
    """One line of runs/index.jsonl."""

    run_id: str
    sheet_version: str | None = None
    grader_version: str | None = None
    headline: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- 4.2 Agora contract


class RetrievedItem(Rec):
    passage_id: str
    text: str
    author: str
    work: str
    locator: str
    rank: int | None = Field(default=None, ge=1)  # 1-based; 0 / negative is a contract violation
    block_id: str | None = None
    work_id: str | None = None
    corpus_version: str | None = None
    chapter: int | None = None
    section: int | None = None
    score: float | None = None

    @field_validator("rank", "chapter", "section", mode="before")
    @classmethod
    def _num(cls, v: Any) -> Any:
        return _int_or_none(v)


class CitationItem(Rec):
    passage_id: str
    author: str
    work: str
    locator: str
    quote: str
    chapter: int | None = None
    section: int | None = None

    @field_validator("chapter", "section", mode="before")
    @classmethod
    def _num(cls, v: Any) -> Any:
        return _int_or_none(v)


class SelfCheckItem(Rec):
    passage_id: str
    quote: str
    status: str


class ClaimItem(Rec):
    text: str
    passage_ids: list[str] = Field(default_factory=list)


class AgoraInfo(Rec):
    model: str | None = None
    namespace: str | None = None
    k: int | None = None
    filters: Any = None
    code_sha256: str | None = None

    @field_validator("k", mode="before")
    @classmethod
    def _num(cls, v: Any) -> Any:
        return _int_or_none(v)


class AgoraResult(Rec):
    """Contract version CONTRACT_VERSION of ask.answer_question's return value."""

    answer: str
    citations: list[CitationItem]
    retrieved: list[RetrievedItem]
    declined: bool | None = None
    self_check: list[SelfCheckItem] | None = None
    attempts: int | None = None
    claims: list[ClaimItem] | None = None
    info: dict[str, Any] | None = None

    @field_validator("attempts", mode="before")
    @classmethod
    def _num(cls, v: Any) -> Any:
        return _int_or_none(v)

    @field_validator("retrieved", mode="after")
    @classmethod
    def _fill_rank(cls, items: list[RetrievedItem]) -> list[RetrievedItem]:
        for i, it in enumerate(items, start=1):
            if it.rank is None:
                it.rank = i
        return items


__all__ = [
    "CONTRACT_VERSION",
    "AgoraInfo",
    "AgoraResult",
    "Anchor",
    "AttributionAdvice",
    "BatchRecord",
    "Card",
    "CheckFailure",
    "ChunkRef",
    "CitationItem",
    "ClaimItem",
    "DiscardedDraft",
    "GradeRecord",
    "JudgeCall",
    "KeyPoint",
    "Provenance",
    "RawError",
    "RawRecord",
    "RetiredEntry",
    "RetrievedItem",
    "Review",
    "RunIndexEntry",
    "RunRecord",
    "SelfCheckItem",
    "Sheet",
    "SheetCorpus",
    "SheetCounts",
    "SheetProvenance",
    "SlotPlanEntry",
    "SourceRef",
    "canonical_json",
    "canonical_sha256",
    "compute_counts",
    "content_sha256",
    "dump",
    "make_card_id",
    "sha256_hex",
    "skeleton_sha256",
]
