"""Regression tests for the independent code review of the quiz (Part B): B1, M2, m2, m5-m8, m10 and the nits."""

import os
import random

import pytest

from integrity import cli
from integrity.common import storage, textnorm
from integrity.common.llm import FakeModelClient
from integrity.common.schema import Card
from integrity.common.settings import load_settings
from integrity.quiz import api, report, scorecard
from integrity.quiz.agora import validate_result
from integrity.quiz.grading import judge as jd
from integrity.quiz.grading import mechanical, pipeline
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf

SPEC = "integrity.tests.quiz_fake_agora:"
RSPEC = "integrity.tests.quiz_review_agoras:"
LOCKE = next(c for c in qf.all_cards() if c["anchor"]["author"] == "John Locke" and c["type"] == "passage")
FAB = ("Locke says the moon is made of cheese and rulers should be chosen by lottery "
       "(John Locke, Second Treatise of Government, Book II, Chapter 5, §27, paragraph 3 (edition-specific)).")


@pytest.fixture
def env(data_dir):
    qf.write_sheet(data_dir)
    fa.register()
    return data_dir


def settings(controls=2, **over):
    return load_settings({"quiz": {"min_cards": 1, "timeout_s": 5, "retries": 0}, "checks": {"quote_min_words": 5},
                          "judge": {"consistency_sample": 0.5, "controls_per_run": controls}} | over)


def quiz(name="good_agora", spec=SPEC, **kw):
    kw.setdefault("settings", settings())
    kw.setdefault("model_client", qf.RuleJudge())
    return api.run_quiz(agora=spec + name, **kw)


# --------------------------------------------------------------------------- a judge scripted per schema


class Scripted(FakeModelClient):
    def __init__(self, handlers):
        super().__init__()
        self.handlers = handlers

    def structured(self, *, system, user, schema, purpose):
        h = self.handlers[schema.__name__]
        return schema.model_validate(h() if callable(h) else h)


def grade(answer, claims, *, coverage=None, result_claims=None, support="not_supported", refusal=None, answer_ok=True):
    """Grade one fixture card with a scripted judge; returns the card summary."""
    card = Card.model_validate(LOCKE)
    res = fa._good(LOCKE) | {"answer": answer, "claims": result_claims, "declined": None}
    cov = coverage or {"verdict": "covered", "answer_span": " ".join(answer.split()[:4]), "reason": "r"}
    judge = jd.Judge(Scripted({
        "CoverageOut": cov, "ClaimsOut": {"claims": claims},
        "SupportOut": {"verdict": support, "passage_id": "", "passage_span": "", "reason": "r"},
        "RefusalOut": refusal or {"refused": False, "answer_span": ""},
    }), model_id="openai:gpt-4.1", prompt_names={k: f"judge_{k}_v1" for k in jd.KINDS})
    g, _ = pipeline.grade_one(card, validate_result(res), None, judge, 5)
    return scorecard.summarize_card(card, g, {"result": res}), g


def cl(text, span=None, kind="substantive", cited=()):
    return {"text": text, "answer_span": text if span is None else span, "cited_as": list(cited), "kind": kind}


# --------------------------------------------------------------------------- B1


def test_b1_empty_claim_list_is_extraction_failure_not_a_pass():
    s, _ = grade(FAB, [])
    assert s["fully_passing"] is False and s["extraction_failure"] is True
    assert "J2 no verified claims" in s["failed_checks"]


def test_b1_bogus_claim_span_counts_as_unverified_claim():
    s, g = grade(FAB, [cl("cheese moon", "NOT IN ANSWER AT ALL")])
    assert g["judged"]["claims"]["rejected"] and s["claims"]["total"] == 1 and s["claims"]["unverified"] == 1
    assert s["claims_unsupported_any"] is True and s["fully_passing"] is False
    assert "J2 unverified_claim" in s["failed_checks"]


def test_b1_meta_label_on_a_fabrication_cannot_make_the_card_pass():
    # the short, digit-free meta claim is exempt from scoring (rule d) but the answer then has no verified substantive
    # claim and the claims cover a small part of it: the card must not pass (old code: fully_passing True)
    s, g = grade(FAB, [cl("cheese", "Locke says the moon is made of cheese", kind="meta")])
    assert g["judged"]["claims"]["items"][0]["kind"] == "meta"
    assert s["fully_passing"] is False
    assert {"J2 no verified claims", "J2 low extraction coverage"} <= set(s["failed_checks"])


def test_b1_meta_label_on_the_cited_fabrication_is_reclassified_substantive():
    s, g = grade(FAB, [cl("cheese", FAB, kind="meta")])  # the span carries the inline citation and digits
    item = g["judged"]["claims"]["items"][0]
    assert item["kind"] == "substantive" and item["kind_judge"] == "meta" and item["reclassified"] is True
    assert s["claims"]["total"] == 1 and s["claims"]["not_supported"] == 1 and s["fully_passing"] is False


def test_b1_meta_with_digits_or_citation_is_not_exempt():
    ans = "Locke owns property. See paragraph 3 for details."
    _, g = grade(ans, [cl("Locke owns property", "Locke owns property."), cl("pointer", "See paragraph 3 for details.", kind="meta")])
    kinds = {i["answer_span"]: i["kind"] for i in g["judged"]["claims"]["items"]}
    assert kinds["See paragraph 3 for details."] == "substantive"


def test_b1_short_plain_meta_stays_exempt_but_long_meta_does_not():
    body = "Each person owns their own labour and so owns what they mix it with."
    ans = body + " Here is a short summary."
    _, g = grade(ans, [cl("body", body), cl("intro", "Here is a short summary.", kind="meta")])
    assert [i["kind"] for i in g["judged"]["claims"]["items"]] == ["substantive", "meta"]
    long_meta = "This sentence merely talks about the answer itself without asserting anything: " + "word " * 40
    assert len(long_meta) > jd.META_MAX_CHARS
    _, g = grade(body + " " + long_meta, [cl("body", body), cl("m", long_meta.strip(), kind="meta")])
    assert [i["kind"] for i in g["judged"]["claims"]["items"]] == ["substantive", "substantive"]


def test_b1_meta_claims_over_30_percent_of_the_answer_are_substantive():
    body = "Each person owns their own labour and so owns what they mix it with."
    meta = "Here is a short summary of the matter."
    _, g = grade(body + " " + meta, [cl("body", body), cl("m", meta, kind="meta")])  # meta is about 36% of the answer
    c = g["judged"]["claims"]
    assert c["meta_share"] > jd.META_MAX_SHARE
    assert [i["kind"] for i in c["items"]] == ["substantive", "substantive"]


def test_b1_low_extraction_coverage_blocks_fully_passing():
    body = "Each person owns their own labour and so owns what they mix it with."
    padding = " ".join(f"Padding sentence number {n} wanders off." for n in range(12))
    s, _ = grade(body + " " + padding, [cl("body", body)], support="supported")
    assert s["extraction_coverage"] < 0.5 and "J2 low extraction coverage" in s["failed_checks"]
    assert s["fully_passing"] is False


def test_b1_answer_card_needs_one_verified_substantive_claim():
    body = "Each person owns their own labour."
    s, _ = grade(body, [cl("meta only", body, kind="meta")], support="supported")
    # a lone 'meta' claim covers 100% of the answer: over the 30% share, so it is substantive (scored, unsupported here)
    assert s["claims"]["total"] == 1
    ans = "Here is a short summary."
    s, _ = grade(ans, [cl("intro", ans, kind="meta")])
    assert s["fully_passing"] is False  # nothing substantive at all (expected_behavior=answer)


def test_b1_structured_claims_empty_list_is_extraction_failure():
    s, _ = grade(FAB, [], result_claims=[])
    assert s["extraction_failure"] is True and s["fully_passing"] is False


def test_b1_structured_claim_not_found_in_answer_is_unverified():
    s, g = grade(FAB, [], result_claims=[{"text": "Locke rejects all property", "passage_ids": []},
                                          {"text": "the moon is made of cheese", "passage_ids": []}])
    c = g["judged"]["claims"]
    assert len(c["rejected"]) == 1 and len(c["items"]) == 1 and c["source"] == "result"
    assert s["claims"]["unverified"] >= 1 and s["fully_passing"] is False


def test_b1_honest_answers_still_fully_pass(env):
    r = quiz()
    cards = [c for c in r.scorecard["cards"] if c["expected_behavior"] == "answer"]
    assert len(cards) >= 4 and all(c["fully_passing"] and c["extraction_coverage"] >= 0.9 for c in cards)
    fp = [c for c in r.scorecard["cards"] if c["expected_behavior"] != "answer"]
    assert fp and all(c["fully_passing"] for c in fp)
    assert r.trust == "TRUSTED"


# --------------------------------------------------------------------------- m5


def test_m5_short_judge_spans_are_unverified():
    _, g = grade(FAB, [cl("x", "moon")], coverage={"verdict": "covered", "answer_span": "moon cheese", "reason": "r"})
    assert g["judged"]["coverage"][0]["verdict"] == "unverified"  # two words
    assert g["judged"]["claims"]["rejected"]
    _, g = grade(FAB, [], coverage={"verdict": "covered", "answer_span": "made of cheese", "reason": "r"})
    assert g["judged"]["coverage"][0]["verdict"] == "covered"  # three words


def test_m5_short_answer_needs_the_whole_answer_as_span():
    assert jd.answer_span_in("Yes indeed", "Yes indeed") and not jd.answer_span_in("Yes", "Yes indeed")
    assert not jd.answer_span_in("one two", "one two three four") and jd.answer_span_in("one two three", "one two three four")


def test_m5_short_refusal_and_premise_spans_are_unverified():
    ans = "We simply cannot say anything about this question at all."
    _, g = grade(ans, [cl("c", ans)], refusal={"refused": True, "answer_span": "cannot say"})
    r = g["judged"]["refusal"]
    assert r["status"] == "unverified" and r["refused"] is None
    _, g = grade(ans, [cl("c", ans)], refusal={"refused": True, "answer_span": "cannot say anything"})
    assert g["judged"]["refusal"]["refused"] is True


# --------------------------------------------------------------------------- m6


def test_m6_grader_version_covers_granularity_consistency_and_controls():
    base = settings()
    versions = {
        jd.Judge.from_settings(FakeModelClient(), s).grader_version
        for s in (base, settings(controls=3), settings(judge={"consistency_sample": 0.25, "controls_per_run": 2}),
                  settings(judge={"consistency_sample": 0.5, "controls_per_run": 2, "granularity": "per_card"}))
    }
    assert len(versions) == 4
    assert jd.Judge.from_settings(FakeModelClient(), base).grader_version == jd.Judge.from_settings(FakeModelClient(), settings()).grader_version


# --------------------------------------------------------------------------- m2 (health) / --strict


def test_m2_no_controls_is_unverified_without_check_mark_and_strict_exits_6(env):
    r = quiz(settings=settings(controls=0))
    assert r.trust.startswith("UNVERIFIED") and r.exit_code == 0
    assert r.scorecard["health"]["trusted"] is False
    health_line = next(x for x in report.render_terminal(r.scorecard).splitlines() if x.startswith("GRADER HEALTH"))
    assert "✓" not in health_line and "UNVERIFIED" in health_line
    assert "[UNVERIFIED]" in report.render_terminal(r.scorecard)
    s = quiz(settings=settings(controls=0), strict=True)
    assert s.exit_code == 6 and s.scorecard is not None
    assert quiz(strict=True).exit_code == 0  # controls ran and passed: TRUSTED


def test_m2_mechanical_only_stays_exempt_from_strict(env):
    r = quiz(settings=settings(controls=0), strict=True, mechanical_only=True, model_client=None)
    assert r.exit_code == 0 and r.trust == "NOT RUN (mechanical only)"


# --------------------------------------------------------------------------- m7 / m8


def test_m7_mechanical_only_failures_md_lists_misses_and_declines(env):
    r = quiz("wrong_passage_agora", mechanical_only=True, model_client=None)
    text = (r.run_dir / "failures.md").read_text()
    assert "M1 not_found" in text and "did not fully pass" in text and "0 main card(s)" not in text
    d = quiz("declining_agora", RSPEC, mechanical_only=True, model_client=None)
    text = (d.run_dir / "failures.md").read_text()
    assert "M11 declined" in text and "M9 no_citations" not in text  # a decline needs no citations
    assert d.scorecard["main"]["behaviour"]["wrongful_refusals"] >= 3
    assert "Wrongful refusals" in report.render_terminal(d.scorecard)


def test_m7_never_cited_card_is_listed_in_mechanical_only_mode(env):
    r = quiz("nocite_agora", "integrity.tests.quiz_fix_agoras:", mechanical_only=True, model_client=None)
    assert "M9 no_citations" in (r.run_dir / "failures.md").read_text()


def test_m7_unverified_refusal_fails_the_card_but_is_not_wrongful():
    ans = "We simply cannot say anything about this question at all."
    s, _ = grade(ans, [cl("c", ans)], refusal={"refused": True, "answer_span": "NOT IN THE ANSWER"}, support="supported")
    assert s["wrongful_refusal"] is False and s["refusal_ok"] is False and s["fully_passing"] is False
    assert "J4 unverified" in s["failed_checks"]


def test_m8_scorecard_counts_and_never_retrieved_follow_the_cards_run(env):
    r = quiz(authors=["Hobbes"], limit=1)
    sh = r.scorecard["sheet"]
    assert sh["cards"] == 1 and sh["holdout"] == 0 and sh["whole_sheet"] == {"cards": 5, "holdout": 1}
    assert r.scorecard["never_retrieved"] == []
    assert not any("never retrieved" in w for w in r.scorecard["warnings"])
    assert "sheet has 5 cards, 1 sealed" in report.render_terminal(r.scorecard)
    full = quiz().scorecard["sheet"]
    assert full["cards"] == 5 and full["holdout"] == 1


def test_m8_never_retrieved_is_limited_to_works_asked():
    sheet = qf.write_sheet_obj()
    works = sorted({c.anchor.work for c in sheet.cards})
    assert len(works) >= 3
    asked = [c for c in sheet.cards if c.anchor.work == works[0]][:1]
    res = fa._good(next(c for c in qf.all_cards() if c["card_id"] == asked[0].card_id))
    recs = [{"card_id": asked[0].card_id, "result": validate_result(res), "error": None}]
    g = pipeline.grade_run(sheet=sheet, cards=sheet.cards, records=recs, judge=None, settings=settings())
    assert g.never_retrieved == []
    assert mechanical.never_retrieved(works, [res]) != []  # the whole-sheet computation would have warned


# --------------------------------------------------------------------------- M2 / m10: .env and tracing


@pytest.fixture
def dotenv_root(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".env").write_text("OPENAI_API_KEY=sk-test-from-dotenv\nLANGSMITH_TRACING=true\nLANGCHAIN_TRACING_V2=true\n")
    monkeypatch.setenv("ALLOW_DOTENV_IN_TESTS", "on")
    for var in ("OPENAI_API_KEY", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(var, "x")
        monkeypatch.delenv(var)  # registers the restore; the variable is absent for the test
    return root


def with_root(root, **over):
    return settings(**({"seams": {"project_root": str(root)}} | over))


def test_m2_run_quiz_sees_a_key_that_only_lives_in_dotenv(env, dotenv_root):
    assert "OPENAI_API_KEY" not in os.environ
    r = quiz(settings=with_root(dotenv_root))
    assert r.exit_code == 0 and r.scorecard is not None
    assert os.environ["OPENAI_API_KEY"] == "sk-test-from-dotenv"


def test_m2_without_dotenv_the_missing_key_still_fails_preflight(env, dotenv_root, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = quiz(settings=with_root(empty))
    assert r.exit_code == 4 and "OPENAI_API_KEY" in r.message


def test_m2_regrade_sees_a_key_that_only_lives_in_dotenv(env, dotenv_root, monkeypatch, tmp_path):
    first = quiz()
    assert first.exit_code == 0
    os.environ.pop("OPENAI_API_KEY", None)

    def stop(settings, client):  # the key check is before this point; never build a real model client in a test
        raise RuntimeError("stub")

    monkeypatch.setattr(api, "_make_judge", stop)
    r = api.regrade(first.run_id, settings=with_root(dotenv_root), model_client=None)
    assert r.exit_code == 4 and "stub" in r.message  # EXIT_CONFIG from the stub, not from a missing key
    empty = tmp_path / "empty"
    empty.mkdir()
    os.environ.pop("OPENAI_API_KEY", None)
    r = api.regrade(first.run_id, settings=with_root(empty), model_client=None)
    assert r.exit_code == 4 and "needs OPENAI_API_KEY" in r.message


def test_m2_dotenv_never_overrides_an_exported_variable(env, dotenv_root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "exported")
    cli.apply_env_file(with_root(dotenv_root))
    assert os.environ["OPENAI_API_KEY"] == "exported"


def test_m2_cli_main_loads_dotenv_and_tracing_off_still_wins(env, dotenv_root, tmp_path, monkeypatch):
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'[paths]\ndata_dir = "{env.as_posix()}"\n[seams]\nproject_root = "{dotenv_root.as_posix()}"\n'
                   '[models]\ntracing = "off"\n')
    monkeypatch.setenv("INTEGRITY_CONFIG", str(cfg))
    assert cli.main(["sheet", "list"]) == 0
    assert os.environ["OPENAI_API_KEY"] == "sk-test-from-dotenv"
    assert os.environ["LANGSMITH_TRACING"] == "false" and os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_m10_tracing_off_applies_to_the_python_apis(env, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    r = quiz(settings=settings(models={"tracing": "off"}))
    assert r.exit_code == 0 and os.environ["LANGSMITH_TRACING"] == "false" and os.environ["LANGCHAIN_TRACING_V2"] == "false"
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    api.regrade(r.run_id, settings=settings(models={"tracing": "off"}), model_client=qf.RuleJudge())
    assert os.environ["LANGSMITH_TRACING"] == "false"
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    quiz(settings=settings(models={"tracing": "inherit"}))
    assert os.environ["LANGSMITH_TRACING"] == "true"


# --------------------------------------------------------------------------- nits: SystemExit / KeyboardInterrupt


def test_systemexit_in_agora_is_an_error_for_that_card(env):
    r = quiz("sysexit_agora", RSPEC)
    assert r.exit_code == 5  # every card errored
    run = storage.read_json(r.run_dir / "run.json")
    raw = storage.read_jsonl(r.run_dir / "raw.jsonl")
    assert run["status"] == "failed" and len(raw) == 5 and all(x["error"]["type"] == "SystemExit" for x in raw)


def test_keyboard_interrupt_finalises_run_json_and_resume_continues(env):
    with pytest.raises(KeyboardInterrupt):
        quiz("interrupt_second_agora", RSPEC)
    run_dir = next(p for p in (env / "runs").iterdir() if p.name.startswith("r-"))
    run = storage.read_json(run_dir / "run.json")
    assert run["status"] == "interrupted" and run["finished_at"]
    assert len(storage.read_jsonl(run_dir / "raw.jsonl")) == 1
    fa.register()
    r = quiz("good_agora", resume=run_dir.name)
    assert r.exit_code == 0 and len(storage.read_jsonl(run_dir / "raw.jsonl")) == 5
    assert storage.read_json(run_dir / "run.json")["status"] == "complete"


def test_cli_turns_keyboard_interrupt_into_exit_130(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_cmd_sheet_list", lambda a, s: (_ for _ in ()).throw(KeyboardInterrupt()))
    parser_handler = cli.build_parser()
    assert parser_handler is not None
    monkeypatch.setattr(cli, "load_env", lambda s: None, raising=False)
    # sheet list is bound at parser build time inside main, so patch via a quiz command instead
    import integrity.quiz.handlers as h
    monkeypatch.setattr(h, "cmd_report", lambda a, s: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert cli.main(["report"]) == 130
    assert "interrupted" in capsys.readouterr().err


# --------------------------------------------------------------------------- parity: judge._find vs textnorm.find_matches

HAZARDS = ["ﬁne", "Æsthetic", "café", "café", "poore", "state-of-nature", "“quoted”", "it’s", "naïve", "x & y",
           "paß", "2nd", "日本語", "e.g.", "so—called", "a b", "...", "—"]


def _random_text(rng):
    words = ["the", "state", "of", "nature", "and", "the", "law", "of", "reason", "which", "teaches", "all", "mankind", "that", "being", "all", "equal", "and", "independent", "no", "one", "ought", "to", "harm", "another", "in", "his", "life", "health", "liberty", "or", "possessions"]
    out = []
    for _ in range(rng.randint(3, 40)):
        out.append(rng.choice(HAZARDS) if rng.random() < 0.25 else rng.choice(words))
    return " ".join(out)


def test_judge_find_agrees_with_textnorm_find_matches_on_300_strings():
    rng = random.Random(7)
    checked = found = 0
    for _ in range(300):
        text = _random_text(rng)
        toks = text.split()
        i = rng.randrange(len(toks))
        quote = " ".join(toks[i:i + rng.randint(1, 6)])
        if rng.random() < 0.3:  # a cut that can start or end mid-word
            quote = quote[rng.randint(0, 2): len(quote) - rng.randint(0, 2)]
        if rng.random() < 0.15:
            quote = "unrelated words that are not here"
        matches = textnorm.find_matches(quote, text)
        got = jd._find(quote, text)
        assert got == (matches[0] if matches else None), (quote, text)
        checked += 1
        found += got is not None
    assert checked == 300 and found > 100
