"""Shared test builders."""

from integrity.common import schema as sc
from integrity.common import sheets as sh


def make_card(**over):
    base = {
        "card_id": sc.make_card_id("pg7370:main:abc", "passage", "How does Locke explain property?"),
        "type": "passage",
        "question": "How does Locke explain property?",
        "premise": None,
        "expected_behavior": "answer",
        "key_points": [
            {"id": "kp1", "statement": "s1", "quote": "every man has a property in his own person",
             "quote_model": "every man has a property in his own person", "span": [96, 139],
             "chunk_ids": ["pg7370:main:abc:c0"]},
            {"id": "kp2", "statement": "s2", "quote": "q2 q2 q2 q2 q2"},
        ],
        "anchor": {
            "author": "John Locke", "work": "Second Treatise of Government", "work_id": "pg7370:main",
            "source_id": "pg7370", "block_id": "pg7370:main:abc", "locator": "Book II, Chapter 5, §27",
            "chapter": 5.0, "section": 27, "paragraph": 3, "position": 40, "text": "Sect. 27. ...",
            "chunks": [{"passage_id": "pg7370:main:abc:c0", "text": "Sect. 27. ..."}],
            "skeleton_sha256": "x", "context_before": "", "context_after": "",
            "corpus_version": "epub-v1-04b8672ea20df6c7", "source_sha256": "y",
        },
        "holdout": False,
        "flags": ["split_paragraph"],
        "provenance": {"batch_id": "b-1", "slot": "locke#2", "seed": 7, "attempt": 1,
                       "attribution_advice": [{"speaker": "author_sincere", "explanation": "e", "evidence": "v"}],
                       "textnorm_version": 1},
        "review": {"status": "approved", "reviewed_at": "t", "edited": False, "original": None,
                   "reject_reason": None, "notes": ""},
    }
    base.update(over)
    return base


def make_sheet_dict(version="v001", parent=None, cards=None, **over):
    """A valid, sealed sheet dict (cards sorted by card_id)."""
    cards = cards if cards is not None else [make_card()]
    cards = sorted((sc.dump(sc.Card.model_validate(c)) for c in cards), key=lambda c: c["card_id"])
    sheet = sc.Sheet(
        version=version, parent=parent, created_at="2026-11-21T11:30:00Z", note="n",
        counts=sc.compute_counts(cards), added=[c["card_id"] for c in cards],
    )
    d = sc.dump(sheet)
    d["cards"] = cards
    d.update(over)
    return sh.seal_sheet(d)
