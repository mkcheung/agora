"""Builders for the Part A tests: a synthetic corpus (split paragraphs with overlap, notes, Latin,
quote-led paragraphs, objection plus rebuttal, a Burke-style quoted opponent, a page-split word) and
scripted model clients."""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from integrity.builder.corpus import Corpus, Paragraph, build_paragraphs

WORDS = ["the", "of", "and", "to", "in", "that", "which", "men", "power", "government", "people", "law", "nature", "reason", "property", "right", "natural", "society", "consent", "common", "good", "state", "labour", "hold", "would", "hath", "whole", "other", "every", "any", "may", "such", "with", "for", "from", "they", "their", "is", "are", "be", "not", "it", "by", "as", "on", "all", "but", "one", "these", "those", "when", "then", "than", "also", "where", "there", "whom", "shall"]


def prose(i: int, n_sent: int = 12) -> str:
    rnd = random.Random(i)
    sents = []
    for _ in range(n_sent):
        ws = [rnd.choice(WORDS) for _ in range(14)]
        sents.append(" ".join(ws).capitalize() + ".")
    return " ".join(sents)


def mkpara(
    text: str, *, author: str = "John Locke", work: str = "Treatise", work_id: str = "w1:main", position: int = 0,
    paragraph: int | None = None, locator: str | None = None, content_type: str = "prose",
    context_before: str = "", context_after: str = "", chunks: list[tuple[str, str]] | None = None,
    block_id: str | None = None,
) -> Paragraph:
    bid = block_id or f"{work_id}:b{position:04d}"
    return Paragraph(
        author=author, work=work, work_id=work_id, source_id=work_id.split(":")[0], block_id=bid,
        locator=locator or f"Chapter 1, paragraph {position + 1}", content_type=content_type,
        paragraph=paragraph if paragraph is not None else position + 1, position=position, text=text,
        chunks=chunks or [(f"{bid}:c0", text)], corpus_version="epub-v1-test", source_sha256="sha",
        context_before=context_before, context_after=context_after,
    )


def split_text(text: str, size: int = 2000, overlap: int = 200) -> list[str]:
    """Mimic the chunker: size-character pieces overlapping by `overlap` characters."""
    if len(text) <= size:
        return [text]
    out, i = [], 0
    while True:
        out.append(text[i:i + size])
        if i + size >= len(text):
            return out
        i += size - overlap


WORKS = [
    ("John Locke", "Second Treatise", "w1:main", "ws1"),
    ("Thomas Hobbes", "Leviathan", "w2:main", "ws2"),
    ("John Stuart Mill", "On Liberty", "w3:main", "ws3"),
    ("John Stuart Mill", "Utilitarianism", "w4:main", "ws4"),
    ("Edmund Burke", "Reflections", "w5:main", "ws5"),
]


def fake_chunks(n_per_work: int = 30) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """A provider result: (chunks, ids, report). Chunks are dict records with page_content and metadata."""
    chunks: list[dict[str, Any]] = []
    for author, work, wid, sid in WORKS:
        for i in range(n_per_work):
            text = prose(sum(map(ord, wid)) * 100 + i, n_sent=12 if i % 7 else 40)  # every 7th is long (split)
            if i == 3:
                text = "Note: see the edition."
            pieces = split_text(text)
            bid = f"{wid}:blk{i:03d}"
            for c, piece in enumerate(pieces):
                chunks.append({
                    "page_content": piece,
                    "metadata": {
                        "author": author, "work": work, "source_id": sid, "work_id": wid, "block_id": bid,
                        "passage_id": f"{bid}:c{c}", "locator": f"Chapter {i // 5 + 1}, paragraph {i + 1}",
                        "content_type": "note" if i == 3 else "prose", "chunk": float(c),
                        "chunk_count": len(pieces), "paragraph": float(i + 1), "corpus_version": "epub-v1-test",
                        "chapter": float(i // 5 + 1),
                    },
                })
    report = {
        "corpus_version": "epub-v1-test",
        "manifest": {"sources": [{"file": f"{sid}.epub", "sha256": f"sha-{sid}"} for *_, sid in WORKS]},
        "sources": [{"file": f"{sid}.epub", "source_id": sid} for *_, sid in WORKS],
    }
    return chunks, [c["metadata"]["passage_id"] for c in chunks], report


def fake_corpus(n_per_work: int = 30, context_chars: int = 300) -> Corpus:
    chunks, _ids, report = fake_chunks(n_per_work)
    paras = build_paragraphs(chunks, report, context_chars)
    return Corpus(paragraphs=paras, report=report, corpus_version=report["corpus_version"])


# --------------------------------------------------------------------------- scripted clients


class ScriptedClient:
    """ModelClient whose answers come from fn(call_dict, call_index) -> BaseModel | dict | Exception."""

    def __init__(self, fn: Callable[[dict[str, Any], int], Any]):
        self.fn = fn
        self.calls: list[dict[str, Any]] = []

    def structured(self, *, system: str, user: str, schema: type[BaseModel], purpose: str) -> BaseModel:
        call = {"system": system, "user": user, "schema": schema, "purpose": purpose}
        self.calls.append(call)
        out = self.fn(call, len(self.calls) - 1)
        if isinstance(out, BaseException):
            raise out
        if isinstance(out, dict):
            return schema.model_validate(out)
        return out


def paragraph_of(call: dict[str, Any]) -> str:
    m = re.search(r"PARAGRAPH:\n(.*?)\n\nCONTEXT AFTER", call["user"], re.DOTALL)
    assert m, call["user"][:200]
    return m.group(1)


def surname_of(call: dict[str, Any]) -> str:
    return re.search(r"AUTHOR: (.*)", call["user"]).group(1).split()[-1]


def good_draft(call: dict[str, Any], i: int = 0, *, premise: str | None = None) -> dict[str, Any]:
    toks = paragraph_of(call).split()
    out = {
        "status": "ok", "unsuitable_reason": None,
        "question": f"What does {surname_of(call)} claim about the matter discussed here?",
        "key_points": [
            {"statement": "First claim, restated.", "quote": " ".join(toks[3:11]), "speaker": "author_sincere"},
            {"statement": "Second claim, restated.", "quote": " ".join(toks[30:38]), "speaker": "author_sincere"},
        ],
    }
    if premise is not None:
        out["premise"] = premise
    return out


def advisory_ok(call: dict[str, Any], i: int = 0) -> dict[str, Any]:
    ids = re.findall(r"^(kp\d+):", call["user"], re.MULTILINE)
    ev = paragraph_of(call).split(".")[0]
    return {"items": [{"key_point_id": k, "speaker": "author_sincere", "explanation": "own voice",
                       "evidence": ev} for k in ids]}


def ns(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)
