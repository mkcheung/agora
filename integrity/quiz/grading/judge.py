"""Model judge J1-J5 (plan section 9.4).

Every verdict that cites evidence is verified by code with common.textnorm. A verdict whose evidence
fails becomes ``unverified``; a call that fails becomes ``judge_error``. Both are scored against Agora.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from integrity import TEXTNORM_VERSION
from integrity.common import textnorm
from integrity.common.llm import ModelClient, Prompt, load_prompt
from integrity.common.schema import Card, sha256_hex
from integrity.common.settings import Settings
from integrity.quiz.grading import GRADING_CODE_VERSION

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
KINDS = ("coverage", "claims", "support", "refusal", "premise")
MIN_PASSAGE_SPAN_WORDS = 4
MIN_ANSWER_SPAN_WORDS = 3  # a judge's answer span must be at least this long (or be the whole, shorter answer)
META_MAX_CHARS = 160  # a "meta" claim is exempt from scoring only up to this length ...
META_MAX_SHARE = 0.30  # ... and only while all meta claims together stay within this share of the answer
MIN_CARD_COVERAGE = 0.5  # per-card extraction coverage below this blocks "fully passing"
_CITE_PATTERN = re.compile(r"\([^()]*,[^()]*\)|§|\[[^\]]*\d[^\]]*\]")
POINT_SCORE = {"covered": 1.0, "partial": 0.5}


# --------------------------------------------------------------------------- output schemas (all fields required)


class CoverageOut(BaseModel):
    verdict: Literal["covered", "partial", "absent"]
    answer_span: str
    reason: str


class CoverageItemOut(CoverageOut):
    item: int


class CoverageBatchOut(BaseModel):
    items: list[CoverageItemOut]


class ClaimOut(BaseModel):
    text: str
    answer_span: str
    cited_as: list[str]
    kind: Literal["substantive", "meta"]


class ClaimsOut(BaseModel):
    claims: list[ClaimOut]


class SupportOut(BaseModel):
    verdict: Literal["supported", "not_supported", "contradicted"]
    passage_id: str
    passage_span: str
    reason: str


class SupportItemOut(SupportOut):
    item: int


class SupportBatchOut(BaseModel):
    items: list[SupportItemOut]


class RefusalOut(BaseModel):
    refused: bool
    answer_span: str


class PremiseOut(BaseModel):
    corrects_premise: bool
    answer_span: str
    reason: str


# --------------------------------------------------------------------------- helpers


def grader_version(model_id: str, prompt_texts: list[str], config: list[str] | None = None) -> str:
    """"g-" + sha256(judge model ID + every judge prompt file + GRADING_CODE_VERSION + TEXTNORM_VERSION
    + the grading settings that change what a run measures (granularity, consistency sample, controls))[:6]"""
    blob = "\x1f".join([model_id, *prompt_texts, GRADING_CODE_VERSION, str(TEXTNORM_VERSION), *(config or [])])
    return "g-" + sha256_hex(blob)[:6]


def esc(text: Any) -> str:
    """Make embedded text inert inside the data wrappers: no '<' means no tag can open or close."""
    return str(text).replace("<", "&lt;")


def unesc(text: str) -> str:
    return text.replace("&lt;", "<")


_sk_index = lru_cache(maxsize=256)(textnorm._skeleton_with_index)  # the answer is skeletonised once per card
_sk = lru_cache(maxsize=4096)(textnorm.skeleton)


def _find(quote: str, text: str) -> tuple[int, int] | None:
    """textnorm.find_span with the haystack skeleton cached (identical results, no quadratic re-skeletonising)."""
    if textnorm.has_ellipsis(quote):
        return None
    q = _sk(quote)
    if not q:
        return None
    t, idx = _sk_index(text)
    pos = t.find(q)
    while pos != -1:
        start = idx[pos]
        end = idx[pos + len(q) - 1] + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        if textnorm._start_ok(text, start) and textnorm._end_ok(text, end):
            return (start, end)
        pos = t.find(q, pos + 1)
    return None


def _nonws(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _find_esc(span: str, text: str) -> tuple[int, int] | None:
    """The model sees '<' as '&lt;' and may copy it that way; accept either form."""
    return _find(span, text) or (_find(unesc(span), text) if "&lt;" in span else None)


def span_in(span: str, text: str, min_words: int = 0) -> bool:
    return bool(span and span.strip()) and textnorm.word_count(span) >= min_words and _find_esc(span, text) is not None


_words = lru_cache(maxsize=256)(textnorm.word_count)  # an answer is counted once, not once per span


def answer_span_in(span: str, answer: str) -> bool:
    """A judge's evidence span in the answer: found by textnorm and at least 3 words (or the whole shorter answer)."""
    return span_in(span, answer, min(MIN_ANSWER_SPAN_WORDS, _words(answer)))


def _loc_found(needle: str, hay: str) -> bool:
    """Skeleton containment with digit boundaries ("paragraph 1" must not match "paragraph 12")."""
    if not needle:
        return False
    pos = hay.find(needle)
    while pos != -1:
        end = pos + len(needle)
        before_bad = pos > 0 and needle[0].isdigit() and hay[pos - 1].isdigit()
        after_bad = end < len(hay) and needle[-1].isdigit() and hay[end].isdigit()
        if not before_bad and not after_bad:
            return True
        pos = hay.find(needle, pos + 1)
    return False


def map_citations(cited_as: list[str], retrieved: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Map inline citation strings to retrieved passage ids by (work, locator) skeletons.

    Both work and locator must match (Burke locators are not unique across works). All chunks of a split
    paragraph share a locator, so every matching chunk is returned. Returns (passage_ids, unmapped_strings).
    """
    ids: list[str] = []
    unmapped: list[str] = []
    for cite in cited_as:
        s = _sk(cite)
        hit = [
            it["passage_id"] for it in retrieved
            if _loc_found(_sk(it.get("work", "")), s) and _loc_found(_sk(it.get("locator", "")), s)
        ]
        if not hit:
            unmapped.append(cite)
        for h in hit:
            if h not in ids:
                ids.append(h)
    return ids, unmapped


def _union_nonws(intervals: list[tuple[int, int]], text: str) -> int:
    """Non-whitespace characters of ``text`` covered by the union of the intervals."""
    total, end = 0, -1
    for s, e in sorted(intervals):
        s = max(s, end)
        if e > s:
            total += _nonws(text[s:e])
            end = e
    return total


@dataclass
class ReplayItem:
    card_id: str
    kind: str
    key: str
    original: str
    fn: Callable[[], tuple[str, dict[str, Any]]]


@dataclass
class JudgeOutcome:
    judged: dict[str, Any] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    replays: list[ReplayItem] = field(default_factory=list)


def _set_ok(call: dict[str, Any], ok: bool) -> None:
    call["evidence_ok"] = ok if call["evidence_ok"] is None else (call["evidence_ok"] and ok)


# --------------------------------------------------------------------------- the judge


class Judge:
    def __init__(self, client: ModelClient, *, model_id: str, prompt_names: dict[str, str],
                 granularity: str = "per_item", prompts_dir: Path = PROMPTS_DIR,
                 consistency_sample: float = 0.0, controls_per_run: int = 0):
        self.client = client
        self.model_id = model_id
        self.granularity = granularity
        self.prompts: dict[str, Prompt] = {k: load_prompt(prompts_dir / f"{prompt_names[k]}.md") for k in KINDS}
        self.prompt_hashes = {p.name: p.sha256 for p in self.prompts.values()}
        self.grader_version = grader_version(
            model_id, [self.prompts[k].text for k in KINDS],
            [f"granularity={granularity}", f"consistency_sample={consistency_sample}", f"controls_per_run={controls_per_run}"])

    @classmethod
    def from_settings(cls, client: ModelClient, settings: Settings, prompts_dir: Path = PROMPTS_DIR) -> Judge:
        names = {k: f"judge_{k}_v1" for k in KINDS} | dict(settings.judge.prompts)
        return cls(client, model_id=settings.models.judge, prompt_names=names,
                   granularity=settings.judge.granularity, prompts_dir=prompts_dir,
                   consistency_sample=settings.judge.consistency_sample, controls_per_run=settings.judge.controls_per_run)

    # ---- one model call

    def _call(self, kind: str, user: str, schema: type[BaseModel], out: JudgeOutcome) -> tuple[Any, dict[str, Any]]:
        prompt = self.prompts[kind]
        call: dict[str, Any] = {"prompt_id": prompt.name, "input_sha256": sha256_hex(prompt.text + "\n\n" + user),
                                "output": None, "evidence_ok": None}
        try:
            res = self.client.structured(system=prompt.text, user=user, schema=schema, purpose=f"judge_{kind}")
            call["output"] = res.model_dump(mode="json")
        except Exception as e:  # noqa: BLE001
            res = None
            call["output"] = {"error": f"{type(e).__name__}: {e}"[:500]}
        out.calls.append(call)
        return res, call

    def _batched(self, kind: str, entries: list[Any], render: Callable[[Any, int | None], str],
                 single: type[BaseModel], batch: type[BaseModel], out: JudgeOutcome) -> list[tuple[Any, dict[str, Any]]]:
        """One (output | None, call) per entry. per_item: a call each; per_card: one call for all."""
        if not entries:
            return []
        if self.granularity == "per_item":
            return [self._call(kind, render(e, None), single, out) for e in entries]
        user = "\n".join(render(e, n) for n, e in enumerate(entries, start=1))
        res, call = self._call(kind, user, batch, out)
        if res is None:
            return [(None, call)] * len(entries)
        by_item = {it.item: it for it in res.items}
        return [(by_item.get(n), call) for n in range(1, len(entries) + 1)]

    # ---- J1

    def _coverage_records(self, card_id: str, kps: list[Any], answer: str, out: JudgeOutcome) -> list[dict[str, Any]]:
        def render(kp: Any, n: int | None) -> str:
            tag = f' item="{n}"' if n else ""
            return (f"<key_point{tag}>\nStatement: {esc(kp.statement)}\nSupporting quote from the source: {esc(kp.quote)}\n"
                    f"</key_point>\n<answer>\n{esc(answer)}\n</answer>\n")

        recs = []
        for kp, (res, call) in zip(kps, self._batched("coverage", kps, render, CoverageOut, CoverageBatchOut, out), strict=True):
            rec: dict[str, Any] = {"kp_id": kp.id, "verdict": "judge_error", "model_verdict": None, "answer_span": "",
                                   "reason": "", "status": "judge_error", "evidence_ok": None, "score": 0.0}
            if res is not None:
                rec.update(model_verdict=res.verdict, answer_span=res.answer_span, reason=res.reason)
                if res.verdict == "absent":
                    rec.update(verdict="absent", status="ok")
                else:
                    ok = answer_span_in(res.answer_span, answer)
                    _set_ok(call, ok)
                    rec.update(verdict=res.verdict if ok else "unverified", status="ok" if ok else "unverified", evidence_ok=ok)
            rec["score"] = POINT_SCORE.get(rec["verdict"], 0.0)
            recs.append(rec)
        return recs

    # ---- J2 / J3

    def _extract_claims(self, result: dict[str, Any], out: JudgeOutcome) -> dict[str, Any]:
        """Claims of the answer. Every claim that was returned but could not be verified in the answer goes to
        ``rejected`` and is scored as an unverified (not supported) claim; none may silently leave the denominator."""
        answer, retrieved = result["answer"], result.get("retrieved") or []
        rids = {it["passage_id"] for it in retrieved}
        items: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        if result.get("claims") is not None:  # structured claims bypass J2
            returned = len(result["claims"])
            for c in result["claims"]:
                span = _find_esc(c["text"], answer)
                if span is None:
                    rejected.append({"text": c["text"], "answer_span": c["text"], "evidence_ok": False})
                    continue
                ids = [p for p in c.get("passage_ids", []) if p in rids]
                items.append({"claim_id": f"cl{len(items) + 1}", "text": c["text"], "answer_span": c["text"],
                              "span": list(span), "cited_as": [], "kind": "substantive", "kind_judge": "substantive",
                              "cited_ids": ids, "citation_unmapped": bool(c.get("passage_ids")) and not ids,
                              "unmapped": [p for p in c.get("passage_ids", []) if p not in rids], "evidence_ok": None})
            return self._claims_record("result", answer, items, rejected, returned)
        res, call = self._call("claims", f"<answer>\n{esc(answer)}\n</answer>\n", ClaimsOut, out)
        if res is None:
            rec = self._claims_record("judge_error", answer, [], [], 0)
            rec["extraction_coverage"] = None
            return rec
        all_ok = True
        for c in res.claims:
            span = _find_esc(c.answer_span, answer) if answer_span_in(c.answer_span, answer) else None
            if span is None:
                rejected.append({"text": c.text, "answer_span": c.answer_span, "evidence_ok": False})
                all_ok = False
                continue
            ids, unmapped = map_citations(c.cited_as, retrieved)
            items.append({"claim_id": f"cl{len(items) + 1}", "text": c.text, "answer_span": c.answer_span,
                          "span": list(span), "cited_as": c.cited_as, "kind": c.kind, "kind_judge": c.kind,
                          "cited_ids": ids, "citation_unmapped": bool(c.cited_as) and not ids,
                          "unmapped": unmapped, "evidence_ok": True})
        _set_ok(call, all_ok)
        return self._claims_record("judge", answer, items, rejected, len(res.claims))

    @staticmethod
    def _claims_record(source: str, answer: str, items: list[dict[str, Any]], rejected: list[dict[str, Any]],
                       returned: int) -> dict[str, Any]:
        """Coverage, and the meta-claim rule: a verified 'meta' claim is exempt from scoring only when it is short,
        has no digits or inline citation, and all meta claims together cover at most 30% of the answer."""
        total = _nonws(answer)
        cov = _union_nonws([tuple(i["span"]) for i in items], answer) / total if total else 1.0
        exempt = []
        for i in items:
            if i["kind"] != "meta":
                continue
            text = answer[i["span"][0]:i["span"][1]]
            if len(text) <= META_MAX_CHARS and not re.search(r"\d", text) and not _CITE_PATTERN.search(text):
                exempt.append(i)
        share = _union_nonws([tuple(i["span"]) for i in exempt], answer) / total if total else 0.0
        keep = share <= META_MAX_SHARE
        for i in items:
            if i["kind"] == "meta" and not (keep and i in exempt):
                i["kind"] = "substantive"
                i["reclassified"] = True
        return {"source": source, "items": items, "rejected": rejected, "returned": returned,
                "extraction_coverage": round(cov, 4), "answer_chars": total, "meta_share": round(share, 4)}

    def _support_records(self, claims: list[dict[str, Any]], retrieved: list[dict[str, Any]], out: JudgeOutcome) -> list[dict[str, Any]]:
        entries = []
        for c in claims:
            ps = [it for it in retrieved if it["passage_id"] in c["cited_ids"]] if c["cited_ids"] else list(retrieved)
            entries.append((c, ps))

        def render(e: tuple[dict, list], n: int | None) -> str:
            c, ps = e
            tag = f' item="{n}"' if n else ""
            body = "\n".join(f'<passage id="{esc(p["passage_id"])}">\n{esc(p["text"])}\n</passage>' for p in ps)
            return f'<claim{tag}>\n{esc(c["text"])}\n</claim>\n<answer_span>\n{esc(c["answer_span"])}\n</answer_span>\n{body}\n'

        recs, todo = [], []
        for e in entries:
            if not e[1]:  # nothing to judge against
                recs.append({"claim_id": e[0]["claim_id"], "verdict": "not_supported", "model_verdict": None,
                             "passage_id": "", "passage_span": "", "reason": "no retrieved passages", "status": "ok",
                             "evidence_ok": None, "judged_against": []})
            else:
                todo.append(e)
        done = self._batched("support", todo, render, SupportOut, SupportBatchOut, out)
        by_claim = {}
        for (c, ps), (res, call) in zip(todo, done, strict=True):
            rec = {"claim_id": c["claim_id"], "verdict": "judge_error", "model_verdict": None, "passage_id": "",
                   "passage_span": "", "reason": "", "status": "judge_error", "evidence_ok": None,
                   "judged_against": [p["passage_id"] for p in ps]}
            if res is not None:
                rec.update(model_verdict=res.verdict, passage_id=res.passage_id, passage_span=res.passage_span, reason=res.reason)
                if res.verdict == "not_supported":
                    rec.update(verdict="not_supported", status="ok")
                else:
                    p = next((p for p in ps if p["passage_id"] in (res.passage_id, unesc(res.passage_id))), None)
                    ok = p is not None and span_in(res.passage_span, p["text"], MIN_PASSAGE_SPAN_WORDS)
                    _set_ok(call, ok)
                    rec.update(verdict=res.verdict if ok else "unverified", status="ok" if ok else "unverified", evidence_ok=ok)
            by_claim[c["claim_id"]] = rec
        out_recs = {r["claim_id"]: r for r in recs} | by_claim
        return [out_recs[c["claim_id"]] for c in claims]

    # ---- J4 / J5

    def _refusal(self, result: dict[str, Any], out: JudgeOutcome) -> dict[str, Any]:
        if result.get("declined") is not None:
            return {"refused": bool(result["declined"]), "source": "result", "status": "ok", "answer_span": "", "evidence_ok": None}
        answer = result["answer"]
        res, call = self._call("refusal", f"<answer>\n{esc(answer)}\n</answer>\n", RefusalOut, out)
        rec: dict[str, Any] = {"refused": None, "source": "judge", "status": "judge_error", "answer_span": "", "evidence_ok": None}
        if res is not None:
            rec["answer_span"] = res.answer_span
            if res.refused:
                ok = answer_span_in(res.answer_span, answer)
                _set_ok(call, ok)
                rec.update(refused=True if ok else None, status="ok" if ok else "unverified", evidence_ok=ok)
            else:
                rec.update(refused=False, status="ok")
        return rec

    def _premise(self, card: Card, answer: str, out: JudgeOutcome) -> dict[str, Any]:
        user = f"<premise>\n{esc(card.premise)}\n</premise>\n<answer>\n{esc(answer)}\n</answer>\n"
        res, call = self._call("premise", user, PremiseOut, out)
        rec: dict[str, Any] = {"corrects_premise": None, "status": "judge_error", "answer_span": "", "reason": "", "evidence_ok": None}
        if res is not None:
            rec.update(answer_span=res.answer_span, reason=res.reason)
            if res.corrects_premise:
                ok = answer_span_in(res.answer_span, answer)
                _set_ok(call, ok)
                rec.update(corrects_premise=True if ok else None, status="ok" if ok else "unverified", evidence_ok=ok)
            else:
                rec.update(corrects_premise=False, status="ok")
        return rec

    # ---- one card

    def grade_card(self, card: Card, result: dict[str, Any]) -> JudgeOutcome:
        out = JudgeOutcome()
        answer, retrieved = result["answer"], result.get("retrieved") or []
        cid = card.card_id
        coverage = self._coverage_records(cid, list(card.key_points), answer, out)
        claims = self._extract_claims(result, out)
        substantive = [c for c in claims["items"] if c["kind"] == "substantive"]
        support = self._support_records(substantive, retrieved, out)
        refusal = self._refusal(result, out)
        premise = None
        if card.type == "false_premise" or card.expected_behavior == "correct_premise":
            premise = self._premise(card, answer, out)
        out.judged = {"coverage": coverage, "claims": claims, "support": support, "refusal": refusal, "premise": premise}

        # consistency replays (fresh calls, same inputs)
        for kp, rec in zip(card.key_points, coverage, strict=True):
            out.replays.append(ReplayItem(cid, "coverage", kp.id, rec["verdict"],
                                          lambda kp=kp: self._replay_coverage(cid, kp, answer)))
        for c, rec in zip(substantive, support, strict=True):
            out.replays.append(ReplayItem(cid, "support", c["claim_id"], rec["verdict"],
                                          lambda c=c: self._replay_support(c, retrieved)))
        if refusal["source"] == "judge":
            out.replays.append(ReplayItem(cid, "refusal", "refusal", _eff_refusal(refusal),
                                          lambda: self._replay_refusal(result)))
        if premise is not None:
            out.replays.append(ReplayItem(cid, "premise", "premise", _eff_premise(premise),
                                          lambda: self._replay_premise(card, answer)))
        return out

    def _replay_coverage(self, cid: str, kp: Any, answer: str) -> tuple[str, dict]:
        o = JudgeOutcome()
        rec = self._coverage_records(cid, [kp], answer, o)[0]
        return rec["verdict"], {"replay_of": kp.id, "calls": o.calls}

    def _replay_support(self, claim: dict, retrieved: list[dict]) -> tuple[str, dict]:
        o = JudgeOutcome()
        rec = self._support_records([claim], retrieved, o)[0]
        return rec["verdict"], {"replay_of": claim["claim_id"], "calls": o.calls}

    def _replay_refusal(self, result: dict) -> tuple[str, dict]:
        o = JudgeOutcome()
        return _eff_refusal(self._refusal(result, o)), {"replay_of": "refusal", "calls": o.calls}

    def _replay_premise(self, card: Card, answer: str) -> tuple[str, dict]:
        o = JudgeOutcome()
        return _eff_premise(self._premise(card, answer, o)), {"replay_of": "premise", "calls": o.calls}


def _eff_refusal(r: dict[str, Any]) -> str:
    return {True: "refused", False: "not_refused"}.get(r["refused"], r["status"])


def _eff_premise(r: dict[str, Any]) -> str:
    return {True: "corrects", False: "does_not_correct"}.get(r["corrects_premise"], r["status"])
