# ruff: noqa: C408
"""Fixture sheet, settings and a rule-based fake judge for the quiz tests (no network, no models)."""

from __future__ import annotations

import re
from typing import Any

from integrity.common import schema as sc
from integrity.common import sheets as sh
from integrity.common import textnorm
from integrity.common.settings import Settings, load_settings
from integrity.tests.helpers import make_card, make_sheet_dict

CV = "epub-v1-04b8672ea20df6c7"

LOCKE_27 = (
    "Sect. 27. Though the earth, and all inferior creatures, be common to all men, yet every man has a property "
    "in his own person: this no body has any right to but himself. The labour of his body, and the work of his "
    "hands, we may say, are properly his. Whatsoever then he removes out of the state that nature hath provided, "
    "and left it in, he hath mixed his labour with, and joined to it something that is his own, and thereby makes "
    "it his property. It being by him removed from the common state nature hath placed it in, hath by this labour "
    "something annexed to it, that excludes the common right of other men: for this labour being the unquestionable "
    "property of the labourer, no man but he can have a right to what that is once joined to, at least where there "
    "is enough, and as good, left in common for others."
)
HOBBES = (
    "Hereby it is manifest that during the time men live without a common power to keep them all in awe, they are "
    "in that condition which is called warre; and such a warre, as is of every man against every man. And the life "
    "of man, solitary, poore, nasty, brutish, and short."
)
MILL_C0 = ("The only purpose for which power can be rightfully exercised over any member of a civilised community, "
           "against his will, is to prevent harm to others.")
MILL_C1 = "His own good, either physical or moral, is not a sufficient warrant."
BURKE = (
    "Society is indeed a contract. Subordinate contracts for objects of mere occasional interest may be dissolved "
    "at pleasure; but the state ought not to be considered as nothing better than a partnership agreement in a "
    "trade of pepper and coffee, calico or tobacco, or some other such low concern."
)
LOCKE_19 = (
    "And here we have the plain difference between the state of nature and the state of war, which however some "
    "men have confounded, are as far distant, as a state of peace, good will, mutual assistance and preservation, "
    "and a state of enmity, malice, violence and mutual destruction are one from another."
)

# (key, author, work, work_id, locator, chunks, [(statement, quote)], extra)
SPECS: list[dict[str, Any]] = [
    dict(key="locke", author="John Locke", work="Second Treatise of Government", work_id="pg7370:main",
         locator="Book II, Chapter 5, §27, paragraph 3 (edition-specific)", chunks=[LOCKE_27], chapter=5, section=27,
         q="How does Locke explain how a person can rightfully come to own something that nature gave to everyone?",
         kps=[("Each person owns themselves, and so owns their own labour", "every man has a property in his own person"),
              ("Mixing your labour with something makes it your property",
               "he hath mixed his labour with, and joined to it something that is his own"),
              ("The claim holds only where enough, and as good, is left for others",
               "at least where there is enough, and as good, left in common for others")]),
    dict(key="hobbes", author="Thomas Hobbes", work="Leviathan", work_id="pg3207:main",
         locator="Part I, Chapter 13, paragraph 8", chunks=[HOBBES], chapter=13, section=None,
         q="What does Hobbes say men's condition is without a common power?",
         kps=[("Without a common power, men are in a condition of war of every man against every man",
               "they are in that condition which is called warre"),
              ("Life in that condition is miserable", "solitary, poore, nasty, brutish, and short")]),
    dict(key="mill", author="J. S. Mill", work="On Liberty", work_id="pg34901:main",
         locator="Chapter 1, paragraph 9", chunks=[MILL_C0, MILL_C1], chapter=1, section=None,
         q="When does Mill think power may rightfully be used against a member of a civilised community?",
         kps=[("Power may be used against someone only to prevent harm to others",
               "is to prevent harm to others"),
              ("A person's own good is not enough justification", "is not a sufficient warrant")]),
    dict(key="burke", author="Edmund Burke", work="Reflections on the Revolution in France", work_id="pg15679:reflections",
         locator="Reflections, paragraph 172", chunks=[BURKE], chapter=None, section=None, holdout=True,
         q="Does Burke think the state is a mere commercial partnership?",
         kps=[("The state is more than a partnership in trade",
               "ought not to be considered as nothing better than a partnership agreement"),
              ("Minor contracts may be dissolved at pleasure", "may be dissolved at pleasure")]),
    dict(key="fp", author="John Locke", work="Second Treatise of Government", work_id="pg7370:main",
         locator="Book II, Chapter 3, §19, paragraph 1 (edition-specific)", chunks=[LOCKE_19], chapter=3, section=19,
         type="false_premise", premise="Locke says the state of nature is a state of war",
         q="Why does Locke say the state of nature is a state of war?",
         kps=[("Locke distinguishes the state of nature from the state of war",
               "the plain difference between the state of nature and the state of war")]),
]


def build_card(spec: dict[str, Any]) -> dict[str, Any]:
    block = f"{spec['work_id']}:{spec['key']}0000"
    chunks = [{"passage_id": f"{block}:c{i}", "text": t} for i, t in enumerate(spec["chunks"])]
    text = " ".join(spec["chunks"])
    kps = []
    for n, (stmt, quote) in enumerate(spec["kps"], start=1):
        span = textnorm.find_span(quote, text)
        assert span, quote
        ids = [c["passage_id"] for c in chunks if textnorm.find_span(quote, c["text"])]
        assert ids, quote
        kps.append({"id": f"kp{n}", "statement": stmt, "quote": text[span[0]:span[1]], "quote_model": quote,
                    "span": list(span), "chunk_ids": ids[:1]})
    ctype = spec.get("type", "passage")
    anchor = {
        "author": spec["author"], "work": spec["work"], "work_id": spec["work_id"], "source_id": spec["work_id"].split(":")[0],
        "block_id": block, "locator": spec["locator"], "chapter": spec["chapter"], "section": spec["section"],
        "paragraph": 1, "position": 1, "text": text, "chunks": chunks, "skeleton_sha256": sc.skeleton_sha256(text),
        "context_before": "", "context_after": "", "corpus_version": CV, "source_sha256": "y",
    }
    return make_card(
        card_id=sc.make_card_id(block, ctype, spec["q"]), type=ctype, question=spec["q"], premise=spec.get("premise"),
        expected_behavior="correct_premise" if ctype == "false_premise" else "answer",
        key_points=kps, anchor=anchor, holdout=spec.get("holdout", False), flags=[])


def all_cards() -> list[dict[str, Any]]:
    return [build_card(s) for s in SPECS]


def write_sheet(data_dir, version="v001", cards=None, parent=None):
    d = make_sheet_dict(version=version, parent=parent, cards=cards if cards is not None else all_cards())
    sh.write_sheet(data_dir, d)
    return sh.load_sheet(data_dir, version)


def write_sheet_obj():
    """The fixture sheet as a Sheet object, without touching the disk."""
    return sc.Sheet.model_validate(make_sheet_dict(cards=all_cards()))


def settings_for(**quiz_over: Any) -> Settings:
    """Settings from the conftest INTEGRITY_CONFIG (tmp data dir), with a small min_cards for fixtures."""
    q = {"min_cards": 1, "timeout_s": 5, "retries": 0} | quiz_over
    judge = {"consistency_sample": 0.5, "controls_per_run": 2}
    # the fixture quotes are 5-9 words long: pin the minimum so tests do not depend on the shipped default
    return load_settings({"quiz": q, "judge": judge, "checks": {"quote_min_words": 5}})


# --------------------------------------------------------------------------- rule-based fake judge


def _between(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>\n(.*?)\n</{tag}>", text, re.DOTALL)
    return m.group(1) if m else ""


_PAREN = re.compile(r"\((?:[^()]|\([^()]*\))*\)")


class RuleJudge:
    """A ModelClient that grades the fixture answers by simple rules (per_item granularity only)."""

    def __init__(self, cards: list[dict[str, Any]] | None = None, *, rubber_stamp: bool = False, flip_after: int | None = None):
        self.known: list[tuple[str, str]] = []
        self.premise_markers: list[str] = []
        for c in cards or all_cards():
            self.known += [(k["statement"], k["quote"]) for k in c["key_points"]]
            if c["premise"]:
                self.premise_markers.append(c["key_points"][0]["statement"])
        self.rubber_stamp = rubber_stamp
        self.flip_after = flip_after
        self.calls: list[dict[str, Any]] = []

    def structured(self, *, system: str, user: str, schema: type, purpose: str):
        self.calls.append({"purpose": purpose, "user": user, "system": system})
        return schema.model_validate(getattr(self, purpose.replace("judge_", "_"))(user))

    def _coverage(self, user: str) -> dict:
        stmt = re.search(r"Statement: (.*)", user).group(1)
        answer = _between(user, "answer")
        if textnorm.skeleton(stmt) in textnorm.skeleton(answer):
            return {"verdict": "covered", "answer_span": stmt, "reason": "stated"}
        return {"verdict": "absent", "answer_span": "", "reason": "missing"}

    def _claims(self, user: str) -> dict:
        answer = _between(user, "answer")
        claims = []
        for sent in re.split(r"(?<=\)\.)\s+", answer):
            cites = _PAREN.findall(sent)
            meta = "do not answer" in sent
            claims.append({"text": sent, "answer_span": sent, "cited_as": cites[-1:] if cites else [],
                           "kind": "meta" if meta else "substantive"})
        return {"claims": claims}

    def _support(self, user: str) -> dict:
        claim = _between(user, "claim")
        passages = re.findall(r'<passage id="([^"]*)">\n(.*?)\n</passage>', user, re.DOTALL)
        for stmt, quote in self.known:
            if textnorm.skeleton(stmt) in textnorm.skeleton(claim) or self.rubber_stamp:
                for pid, text in passages:
                    if textnorm.find_span(quote, text):
                        return {"verdict": "supported", "passage_id": pid, "passage_span": quote, "reason": "matches"}
                if self.rubber_stamp and passages:
                    pid, text = passages[0]
                    return {"verdict": "supported", "passage_id": pid, "passage_span": " ".join(text.split()[:6]), "reason": "ok"}
        return {"verdict": "not_supported", "passage_id": "", "passage_span": "", "reason": "no match"}

    def _refusal(self, user: str) -> dict:
        answer = _between(user, "answer")
        phrase = "The provided passages do not answer this question"
        if phrase in answer:
            return {"refused": True, "answer_span": phrase}
        return {"refused": False, "answer_span": ""}

    def _premise(self, user: str) -> dict:
        answer = _between(user, "answer")
        for m in self.premise_markers:
            if m in answer:
                return {"corrects_premise": True, "answer_span": m, "reason": "corrected"}
        return {"corrects_premise": False, "answer_span": "", "reason": "accepted"}
