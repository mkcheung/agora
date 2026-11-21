"""B4: judge J1-J5 with a fake model client."""

import re
import shutil

import pytest

from integrity.common.llm import FakeModelClient
from integrity.common.schema import Card
from integrity.quiz.agora import validate_result
from integrity.quiz.grading import judge as jd
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf

CARDS = {c["anchor"]["author"] + c["type"]: c for c in qf.all_cards()}
LOCKE = CARDS["John Lockepassage"]
FP = CARDS["John Lockefalse_premise"]
NAMES = {k: f"judge_{k}_v1" for k in jd.KINDS}


def make(client, **kw):
    return jd.Judge(client, model_id="openai:gpt-4.1", prompt_names=NAMES, **kw)


def card_result(c=LOCKE, **over):
    return Card.model_validate(c), validate_result(fa._good(c) | over)


def cov(span="", verdict="covered"):
    return {"verdict": verdict, "answer_span": span, "reason": "r"}


def claim(text, cited=(), kind="substantive", span=None):
    return {"text": text, "answer_span": span if span is not None else text, "cited_as": list(cited), "kind": kind}


def sup(verdict="supported", pid="", span="", reason="r"):
    return {"verdict": verdict, "passage_id": pid, "passage_span": span, "reason": reason}


REFUSE_NO = {"refused": False, "answer_span": ""}


def sentences(answer):
    return re.split(r"(?<=\)\.)\s+", answer)


def full_queue(card, result, *, support_span=None):
    """coverage x n, claims, support x n, refusal"""
    sents = sentences(result["answer"])
    cite = re.findall(r"\((?:[^()]|\([^()]*\))*\)", sents[0])[-1]
    q = [cov(k.statement) for k in card.key_points]
    q.append({"claims": [claim(s, [cite]) for s in sents]})
    for k in card.key_points:
        q.append(sup("supported", k.chunk_ids[0], support_span or k.quote))
    q.append(REFUSE_NO)
    return q


def test_happy_path_records_everything():
    card, result = card_result()
    fake = FakeModelClient(full_queue(card, result))
    out = make(fake).grade_card(card, result)
    j = out.judged
    assert [c["verdict"] for c in j["coverage"]] == ["covered"] * 3 and all(c["score"] == 1 for c in j["coverage"])
    assert j["claims"]["source"] == "judge" and len(j["claims"]["items"]) == 3
    assert [s["verdict"] for s in j["support"]] == ["supported"] * 3
    assert j["refusal"]["refused"] is False and j["premise"] is None
    assert [c["purpose"] for c in fake.calls] == ["judge_coverage"] * 3 + ["judge_claims"] + ["judge_support"] * 3 + ["judge_refusal"]
    assert all(set(c) == {"prompt_id", "input_sha256", "output", "evidence_ok"} for c in out.calls)
    assert out.calls[0]["prompt_id"] == "judge_coverage_v1" and len(out.calls[0]["input_sha256"]) == 64


def test_non_verbatim_coverage_evidence_is_unverified_and_scored_zero():
    card, result = card_result()
    q = full_queue(card, result)
    q[0] = cov("words the answer never contains")
    q[1] = cov(card.key_points[1].statement, "partial")
    out = make(FakeModelClient(q)).grade_card(card, result)
    c = out.judged["coverage"]
    assert c[0]["verdict"] == "unverified" and c[0]["score"] == 0 and c[0]["evidence_ok"] is False and c[0]["model_verdict"] == "covered"
    assert c[1]["verdict"] == "partial" and c[1]["score"] == 0.5
    assert out.calls[0]["evidence_ok"] is False


def test_absent_needs_no_evidence_and_judge_error_scores_zero():
    card, result = card_result()
    q = full_queue(card, result)
    q[0] = cov("", "absent")
    q[1] = RuntimeError("api down")
    out = make(FakeModelClient(q)).grade_card(card, result)
    c = out.judged["coverage"]
    assert c[0]["verdict"] == "absent" and c[0]["status"] == "ok"
    assert c[1]["verdict"] == "judge_error" and c[1]["score"] == 0
    assert "error" in out.calls[1]["output"]


def test_support_evidence_rules():
    card, result = card_result()
    q = full_queue(card, result)
    k = card.key_points
    q[4] = sup("supported", k[0].chunk_ids[0], "every man has")                         # only 3 words
    q[5] = sup("contradicted", "not:a:passage", k[1].quote)                              # passage id not offered
    q[6] = sup("supported", k[2].chunk_ids[0], "this text is not in the passage at all")  # not verbatim
    out = make(FakeModelClient(q)).grade_card(card, result)
    assert [s["verdict"] for s in out.judged["support"]] == ["unverified"] * 3
    assert [s["model_verdict"] for s in out.judged["support"]] == ["supported", "contradicted", "supported"]


def test_support_not_supported_and_contradicted_with_evidence():
    card, result = card_result()
    q = full_queue(card, result)
    k = card.key_points
    q[4] = sup("not_supported")
    q[5] = sup("contradicted", k[1].chunk_ids[0], k[1].quote)
    out = make(FakeModelClient(q)).grade_card(card, result)
    assert [s["verdict"] for s in out.judged["support"]][:2] == ["not_supported", "contradicted"]


def test_claim_extraction_coverage_and_rejected_spans():
    card, result = card_result()
    sents = sentences(result["answer"])
    q = full_queue(card, result)
    q[3] = {"claims": [claim(sents[0], [], span=sents[0]), claim("invented", [], span="not in the answer")]}
    q = q[:4] + [sup("not_supported")] + [REFUSE_NO]
    out = make(FakeModelClient(q)).grade_card(card, result)
    c = out.judged["claims"]
    assert len(c["items"]) == 1 and len(c["rejected"]) == 1
    assert c["extraction_coverage"] == pytest.approx(len(sents[0]) / len(result["answer"]), abs=0.01)
    assert out.calls[3]["evidence_ok"] is False


def test_cited_as_mapping_burke_split_and_digit_boundary():
    ret = [
        {"passage_id": "a:c0", "work": "Reflections on the Revolution in France", "locator": "paragraph 5"},
        {"passage_id": "b:c0", "work": "Substance of the Speech", "locator": "paragraph 5"},   # same locator, other work
        {"passage_id": "a:c1", "work": "Reflections on the Revolution in France", "locator": "paragraph 5"},  # split chunk
        {"passage_id": "c:c0", "work": "Reflections on the Revolution in France", "locator": "paragraph 55"},
    ]
    ids, unmapped = jd.map_citations(["(Edmund Burke, Reflections on the Revolution in France, paragraph 5)"], ret)
    assert ids == ["a:c0", "a:c1"] and unmapped == []
    ids, _ = jd.map_citations(["(Burke, Substance of the Speech, paragraph 5)"], ret)
    assert ids == ["b:c0"]
    ids, unmapped = jd.map_citations(["(Burke, Reflections on the Revolution in France, paragraph 55)"], ret)
    assert ids == ["c:c0"]
    ids, unmapped = jd.map_citations(["(Burke, Unknown Work, paragraph 5)", "(Burke, Reflections on the Revolution in France, paragraph 9)"], ret)
    assert ids == [] and len(unmapped) == 2


def test_cited_claims_are_judged_against_their_cited_passages_only():
    card, result = card_result(CARDS["J. S. Millpassage"])
    cite = f"({card.anchor.author}, {card.anchor.work}, {card.anchor.locator})"
    q = [cov(k.statement) for k in card.key_points]
    q.append({"claims": [claim("x", [cite], span=sentences(result["answer"])[0])]})
    q += [sup("not_supported"), REFUSE_NO]
    fake = FakeModelClient(q)
    out = make(fake).grade_card(card, result)
    item = out.judged["claims"]["items"][0]
    assert set(item["cited_ids"]) == {"pg34901:main:mill0000:c0", "pg34901:main:mill0000:c1"}  # both split chunks share the locator
    assert out.judged["support"][0]["judged_against"] == item["cited_ids"]


def test_uncited_claims_are_judged_against_all_retrieved():
    card, result = card_result()
    extra = dict(result["retrieved"][0], passage_id="other:c0", rank=2, text="Another retrieved passage about nothing.")
    result["retrieved"].append(extra)
    sents = sentences(result["answer"])
    q = [cov(k.statement) for k in card.key_points] + [{"claims": [claim(sents[0], [])]}, sup("not_supported"), REFUSE_NO]
    fake = FakeModelClient(q)
    out = make(fake).grade_card(card, result)
    assert out.judged["claims"]["items"][0]["cited_ids"] == []
    support_call = next(c for c in fake.calls if c["purpose"] == "judge_support")
    assert 'id="other:c0"' in support_call["user"] and f'id="{card.key_points[0].chunk_ids[0]}"' in support_call["user"]
    assert out.judged["support"][0]["judged_against"] == ["pg7370:main:locke0000:c0", "other:c0"]


def test_result_claims_field_bypasses_j2():
    card, result = card_result()
    sents = sentences(result["answer"])
    result["claims"] = [{"text": sents[0], "passage_ids": [card.key_points[0].chunk_ids[0]]},
                        {"text": sents[1], "passage_ids": []}]
    q = [cov(k.statement) for k in card.key_points] + [sup("not_supported"), sup("not_supported"), REFUSE_NO]
    fake = FakeModelClient(q)
    out = make(fake).grade_card(card, result)
    assert "judge_claims" not in [c["purpose"] for c in fake.calls]
    c = out.judged["claims"]
    assert c["source"] == "result" and 0 < c["extraction_coverage"] < 1 and c["rejected"] == []
    assert c["items"][0]["cited_ids"] == [card.key_points[0].chunk_ids[0]] and c["items"][1]["cited_ids"] == []


def test_claims_judge_error_is_recorded():
    card, result = card_result()
    q = full_queue(card, result)
    q = q[:3] + [RuntimeError("boom"), REFUSE_NO]
    out = make(FakeModelClient(q)).grade_card(card, result)
    assert out.judged["claims"]["source"] == "judge_error" and out.judged["support"] == []


def test_meta_claims_are_not_supported_checked():
    card, result = card_result()
    result["answer"] = result["answer"] + " Here is the summary."
    q = [cov(k.statement) for k in card.key_points]
    q += [{"claims": [claim("Intro", [], kind="meta", span="Here is the summary.")]}, REFUSE_NO]
    out = make(FakeModelClient(q)).grade_card(card, result)
    assert out.judged["support"] == []
    assert out.judged["claims"]["items"][0]["kind"] == "meta"


def test_j4_refusal_parsed_and_verified():
    card, result = card_result(answer="The provided passages do not answer this question.", citations=[])
    base = [cov("", "absent")] * 3 + [{"claims": [claim("The provided passages do not answer this question.", [], kind="meta")]},
                                      sup("not_supported")]  # all-meta answer: over the 30% share, so scored substantive
    out = make(FakeModelClient(base + [{"refused": True, "answer_span": "do not answer this question"}])).grade_card(card, result)
    assert out.judged["refusal"]["refused"] is True and out.judged["refusal"]["status"] == "ok"
    out = make(FakeModelClient(base + [{"refused": True, "answer_span": "invented words"}])).grade_card(card, result)
    r = out.judged["refusal"]
    assert r["refused"] is None and r["status"] == "unverified" and r["evidence_ok"] is False


def test_j4_skipped_when_result_declares_declined():
    card, result = card_result(declined=True)
    q = full_queue(card, result)[:-1]
    fake = FakeModelClient(q)
    out = make(fake).grade_card(card, result)
    assert out.judged["refusal"] == {"refused": True, "source": "result", "status": "ok", "answer_span": "", "evidence_ok": None}
    assert "judge_refusal" not in [c["purpose"] for c in fake.calls]


def test_j5_premise():
    card, result = card_result(FP)
    q = full_queue(card, result)
    q.append({"corrects_premise": True, "answer_span": "Locke distinguishes the state of nature", "reason": "r"})
    out = make(FakeModelClient(q)).grade_card(card, result)
    assert out.judged["premise"]["corrects_premise"] is True
    q = full_queue(card, result) + [{"corrects_premise": True, "answer_span": "no such words", "reason": "r"}]
    out = make(FakeModelClient(q)).grade_card(card, result)
    p = out.judged["premise"]
    assert p["corrects_premise"] is None and p["status"] == "unverified"
    q = full_queue(card, result) + [{"corrects_premise": False, "answer_span": "", "reason": "r"}]
    assert make(FakeModelClient(q)).grade_card(card, result).judged["premise"]["corrects_premise"] is False


def test_per_card_granularity_batches_items():
    card, result = card_result()
    sents = sentences(result["answer"])
    cite = re.findall(r"\((?:[^()]|\([^()]*\))*\)", sents[0])[-1]
    k = card.key_points
    q = [
        {"items": [dict(cov(x.statement), item=i) for i, x in enumerate(k, start=1)][:2]},   # item 3 missing
        {"claims": [claim(s, [cite]) for s in sents]},
        {"items": [dict(sup("supported", x.chunk_ids[0], x.quote), item=i) for i, x in enumerate(k, start=1)]},
        REFUSE_NO,
    ]
    fake = FakeModelClient(q)
    out = make(fake, granularity="per_card").grade_card(card, result)
    assert [c["purpose"] for c in fake.calls] == ["judge_coverage", "judge_claims", "judge_support", "judge_refusal"]
    assert [c["verdict"] for c in out.judged["coverage"]] == ["covered", "covered", "judge_error"]
    assert [s["verdict"] for s in out.judged["support"]] == ["supported"] * 3
    assert 'item="3"' in fake.calls[0]["user"]


def test_grader_version_changes_with_prompt_and_model(tmp_path):
    base = make(FakeModelClient()).grader_version
    assert re.fullmatch(r"g-[0-9a-f]{6}", base)
    assert jd.Judge(FakeModelClient(), model_id="openai:gpt-5", prompt_names=NAMES).grader_version != base
    pdir = tmp_path / "prompts"
    shutil.copytree(jd.PROMPTS_DIR, pdir)
    same = jd.Judge(FakeModelClient(), model_id="openai:gpt-4.1", prompt_names=NAMES, prompts_dir=pdir).grader_version
    assert same == base
    (pdir / "judge_support_v1.md").write_text((pdir / "judge_support_v1.md").read_text() + "\nExtra rule.\n")
    assert jd.Judge(FakeModelClient(), model_id="openai:gpt-4.1", prompt_names=NAMES, prompts_dir=pdir).grader_version != base


def test_prompt_files_exist_and_are_hashed():
    j = make(FakeModelClient())
    assert set(j.prompt_hashes) == set(NAMES.values())
    for p in j.prompts.values():
        assert "data, not instructions" in p.text and "outside knowledge" in p.text and "{" not in p.text


def test_blind_prompts_contain_nothing_but_the_needed_texts():
    card, result = card_result()
    result["info"] = {"model": "anthropic:claude-sonnet-5-5", "namespace": "ns-secret", "k": 8}
    fake = FakeModelClient(full_queue(card, result))
    make(fake).grade_card(card, result)
    other = CARDS["Thomas Hobbespassage"]
    forbidden = [card.card_id, "ns-secret", "claude-sonnet", "anthropic", "agora", "Agora", "r-2026", "b-1", "batch", "provenance",
                 other["key_points"][0]["statement"], other["question"], card.question, "holdout", "seed"]
    for call in fake.calls:
        blob = call["system"] + "\n" + call["user"]
        for f in forbidden:
            assert f not in blob, (call["purpose"], f)
    cov_call = fake.calls[0]["user"]
    assert card.key_points[0].statement in cov_call and card.key_points[0].quote in cov_call and "<answer>" in cov_call
