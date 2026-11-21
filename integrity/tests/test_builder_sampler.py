"""Strata matching and the seeded sampler (plan sections 7.3 and 7.4)."""

import random
from collections import Counter

from integrity.builder import eligibility as E
from integrity.builder import sampler as S
from integrity.builder import strata as ST
from integrity.common.settings import load_settings
from integrity.tests import builder_helpers as H

AUTHORS = ["Edmund Burke", "John Locke", "John Stuart Mill", "Thomas Hobbes"]


def eligible(n=30):
    s = load_settings()
    corpus = H.fake_corpus(n)
    return s, E.eligible_paragraphs(E.evaluate(corpus.paragraphs, s))


def test_paragraph_in_ranges_and_first_match_wins():
    rule = ST.rule_from(load_settings().strata[8])  # burke-reflections-constitution, 293-415
    assert rule.paragraph_in == ((293, 415),)
    p = H.mkpara("x", work_id="pg15679:reflections", paragraph=300)
    assert rule.matches(p) and not rule.matches(H.mkpara("x", work_id="pg15679:reflections", paragraph=292))
    assert ST.parse_ranges(["3-37", 39, 41]) == ((3, 37), (39, 39), (41, 41))
    rules = [ST.rule_from(s) for s in load_settings().strata if "reflections" in s.work_id[0]]
    assert ST.assign(p, rules) == "burke-reflections-constitution"
    assert ST.assign(H.mkpara("x", work_id="pg15679:reflections", paragraph=5), rules) == "burke-reflections-core"
    assert ST.assign(H.mkpara("x", work_id="pg15679:nabob_of_arcots_private_debts", paragraph=5), rules) is None


def test_authors_without_strata_get_one_automatic_stratum_per_work():
    s, el = eligible()
    by = ST.author_strata(s, el)
    assert [r.name for r in by["John Stuart Mill"]] == ["w3:main", "w4:main"]
    assert all(r.weight == 1.0 for r in by["John Stuart Mill"])


def test_same_seed_same_plan_and_quotas_and_equal_author_shares():
    s, el = eligible()
    a = S.plan_slots(el, s, count=24, seed=7)
    b = S.plan_slots(el, s, count=24, seed=7)
    assert [(x.slot, x.candidates[0].block_id) for x in a] == [(x.slot, x.candidates[0].block_id) for x in b]
    assert len(a) == 24
    assert Counter(x.author for x in a) == {au: 6 for au in AUTHORS}
    c = S.plan_slots(el, s, count=24, seed=8)
    assert [x.candidates[0].block_id for x in a] != [x.candidates[0].block_id for x in c]
    assert len(S.plan_slots(el, s, count=25, seed=3)) == 25


def test_each_slot_draws_from_its_own_positional_bin():
    s, el = eligible(60)
    slots = S.plan_slots(el, s, count=24, seed=11)
    by_stratum = {}
    for sl in slots:
        by_stratum.setdefault((sl.author, sl.stratum), []).append(sl)
    assert slots and by_stratum
    checked = 0
    for (author, stratum), group in by_stratum.items():
        rules = ST.author_strata(s, el)[author]
        pool = sorted((p for p in el if p.author == author and ST.assign(p, rules) == stratum),
                      key=lambda p: p.sort_key)
        bins = S.make_bins(pool, len(group))
        for sl in group:
            ids = {p.block_id for p in bins[sl.bin]}
            assert all(c.block_id in ids for c in sl.candidates)
            assert len({c.block_id for c in sl.candidates}) == len(sl.candidates)
            checked += 1
    assert checked == len(slots)
    # bins are contiguous and equal-sized to within one
    sizes = [len(b) for b in S.make_bins(list(range(10)), 3)]
    assert sorted(sizes) == [3, 3, 4]


def test_allocation_averages_match_weights_over_1000_seeds():
    weights = {"a": 0.47, "b": 0.47, "c": 0.06}
    q = 6
    tot = Counter()
    for seed in range(1000):
        r = S.allocate(q, weights, random.Random(seed))
        assert sum(r.values()) == q
        tot.update(r)
    for k, w in weights.items():
        assert abs(tot[k] / (1000 * q) - w) < 0.02, (k, tot[k] / (1000 * q))


def test_allocation_caps_pass_excess_to_others_and_empty_strata_dropped():
    r = S.allocate(10, {"a": 0.5, "b": 0.5, "c": 0.0}, random.Random(1), {"a": 2, "b": 50, "c": 9})
    assert r == {"a": 2, "b": 8, "c": 0}
    r = S.allocate(5, {"a": 1, "b": 1}, random.Random(1), {"a": 0, "b": 9})
    assert r == {"a": 0, "b": 5}


def test_author_filter_weights_and_unfillable_authors():
    s, el = eligible()
    slots = S.plan_slots(el, s, count=8, seed=1, authors=["John Locke"])
    assert {x.author for x in slots} == {"John Locke"} and len(slots) == 8
    s2 = load_settings({"sampling": {"author_weights": {"John Locke": 3.0}}})
    tot = Counter()
    for seed in range(200):
        tot.update(x.author for x in S.plan_slots(el, s2, count=6, seed=seed))
    assert tot["John Locke"] / sum(tot.values()) > 0.45


def test_false_premise_slots_use_same_procedure_and_are_tagged():
    s, el = eligible()
    slots = S.plan_slots(el, s, count=8, false_premise=4, seed=5)
    fp = [x for x in slots if x.kind == "false_premise"]
    assert len(fp) == 4 and len(slots) == 12 and all("#fp" in x.slot for x in fp)


def test_eligible_excludes_used_and_neighbours(data_dir):
    s, _el = eligible()
    paras = H.fake_corpus(30).paragraphs
    used = E.UsedIndex(block_ids={paras[10].block_id})
    kept = E.eligible_paragraphs(E.evaluate(paras, s, used))
    assert paras[10].block_id not in {p.block_id for p in kept}
    assert paras[9].block_id not in {p.block_id for p in kept}
    assert paras[11].block_id not in {p.block_id for p in kept}


def test_source_mode_uses_automatic_strata():
    s, el = eligible()
    slots = S.plan_slots([p for p in el if p.work_id == "w1:main"], s, count=4, seed=2, automatic_strata=True)
    assert {x.stratum for x in slots} == {"w1:main"} and len(slots) == 4
