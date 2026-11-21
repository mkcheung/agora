"""Realistic Cards (real Locke text) and batch-directory builders for review/publish tests."""

from __future__ import annotations

import json
from pathlib import Path

from integrity.common import schema as sc
from integrity.common import storage, textnorm

SECT_27 = (
    "Sect. 27. Though the earth, and all inferior creatures, be common to all men, yet every man has a "
    "property in his own person: this no body has any right to but himself. The labour of his body, and "
    "the work of his hands, we may say, are properly his. Whatsoever then he removes out of the state that "
    "nature hath provided, and left it in, he hath mixed his labour with, and joined to it something that "
    "is his own, and thereby makes it his property. It being by him removed from the common state nature "
    "hath placed it in, it hath by this labour something annexed to it, that excludes the common right of "
    "other men: for this labour being the unquestionable property of the labourer, no man but he can have "
    "a right to what that is once joined to, at least where there is enough, and as good, left in common "
    "for others."
)
SECT_26 = (
    "Sect. 26. God, who hath given the world to men in common, hath also given them reason to make use of "
    "it to the best advantage of life, and convenience. The earth, and all that is therein, is given to men "
    "for the support and comfort of their being. And though all the fruits it naturally produces, and "
    "beasts it feeds, belong to mankind in common, as they are produced by the spontaneous hand of nature."
)

PARAS = {
    "27": {
        "text": SECT_27, "block": "pg7370:main:eb5860d372ca4d8ec6a0", "position": 40, "section": 27,
        "question": "How does Locke explain how a person can rightfully come to own something nature gave to everyone?",
        "kps": [
            ("Each person owns themselves.", "every man has a property in his own person"),
            ("Mixing labour with a thing makes it yours.",
             "he hath mixed his labour with, and joined to it something that is his own"),
            ("The claim holds only where enough is left for others.",
             "at least where there is enough, and as good, left in common for others"),
        ],
    },
    "26": {
        "text": SECT_26, "block": "pg7370:main:f8b8e9174f225612c492", "position": 39, "section": 26,
        "question": "Why does Locke say God gave men reason along with the world?",
        "kps": [
            ("Reason is given so the world can be used well.",
             "hath also given them reason to make use of it to the best advantage of life"),
            ("The earth is given for human support and comfort.",
             "The earth, and all that is therein, is given to men for the support and comfort of their being"),
        ],
    },
}


def make_real_card(key: str = "27", *, status: str = "pending", batch_id: str = "b-20261121-101500-s7",
                   question: str | None = None, **over) -> sc.Card:
    p = PARAS[key]
    text, block = p["text"], p["block"]
    pid = f"{block}:c0"
    q = question or p["question"]
    kps = []
    for i, (stmt, quote) in enumerate(p["kps"], 1):
        s, e = textnorm.find_span(quote, text)
        kps.append(sc.KeyPoint(id=f"kp{i}", statement=stmt, quote=text[s:e], quote_model=quote,
                               span=[s, e], chunk_ids=[pid]))
    card = sc.Card(
        card_id=sc.make_card_id(block, "passage", q), type="passage", question=q, key_points=kps,
        anchor=sc.Anchor(
            author="John Locke", work="Second Treatise of Government", work_id="pg7370:main",
            source_id="pg7370", block_id=block,
            locator=f"Book II, Chapter 5, §{p['section']}, paragraph 3 (edition-specific)",
            chapter=5, section=p["section"], paragraph=3, position=p["position"], text=text,
            chunks=[sc.ChunkRef(passage_id=pid, text=text)], skeleton_sha256=sc.skeleton_sha256(text),
            context_before="…the previous paragraph ends here.", context_after="The next paragraph begins…",
            corpus_version="epub-v1-04b8672ea20df6c7", source_sha256="ab" * 32,
        ),
        flags=["split_paragraph"],
        provenance=sc.Provenance(
            batch_id=batch_id, slot="locke-treatise#1", seed=7, attempt=1, drafter_model="openai:gpt-4.1",
            drafter_prompt="drafter_v1", drafter_prompt_sha256="cd" * 32,
            attribution_advice=[sc.AttributionAdvice(key_point_id="kp1", speaker="author_sincere",
                                                     explanation="e", evidence="v", evidence_verified=True)],
        ),
        review=sc.Review(status=status),
    )
    return card.model_copy(update=over) if over else card


def write_batch(data_dir: Path, batch_id: str, cards: list[sc.Card]) -> Path:
    d = storage.batch_dir(data_dir, batch_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "batch.json").write_text(json.dumps({"batch_id": batch_id, "seed": 7}), encoding="utf-8")
    storage.write_jsonl_atomic(d / "cards.jsonl", [sc.dump(c) for c in cards])
    return d


def scripted(*lines: str):
    """input_fn that returns the lines in order, then raises EOFError."""
    it = iter(lines)

    def _in(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return _in


def locke_corpus(*extra_texts: str):
    """A tiny offline Corpus holding Sect. 26 and 27 (plus optional extra paragraphs) of pg7370:main."""
    from integrity.builder.corpus import Corpus
    from integrity.tests.builder_helpers import mkpara

    texts = [SECT_26, SECT_27, *extra_texts]
    paras = [mkpara(t, work_id="pg7370:main", position=i) for i, t in enumerate(texts)]
    return Corpus(paragraphs=paras, report={}, corpus_version="epub-v1-test")
