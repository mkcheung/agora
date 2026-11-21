"""Seam 1 adapter (plan section 4.1) and the corpus command."""

import sys
import types

import pytest

from integrity.builder import corpus as C
from integrity.common.settings import load_settings
from integrity.tests import builder_helpers as H


def test_rebuild_removes_overlap_exactly():
    text = H.prose(1, 60)
    pieces = H.split_text(text)
    assert len(pieces) > 1
    assert C.rebuild_text(pieces) == (text, False)


def test_rebuild_whitespace_fallback_and_uncertain():
    a = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma"
    b = "kappa  lambda\nmu nu xi omicron pi rho sigma tau upsilon phi"  # overlap differs in whitespace only
    text, uncertain = C.rebuild_text([a, b])
    assert not uncertain and text.endswith("tau upsilon phi") and text.count("kappa") == 1
    text, uncertain = C.rebuild_text(["one two three", "completely different"])
    assert uncertain and text == "one two three completely different"


def test_build_paragraphs_groups_orders_positions_context_and_ints():
    chunks, _ids, report = H.fake_chunks(10)
    chunks.reverse()  # arrival order must not matter within a block
    paras = C.build_paragraphs(chunks, report, context_chars=50)
    w1 = [p for p in paras if p.work_id == "w1:main"]
    assert [p.position for p in w1] == list(range(10)) or sorted(p.position for p in w1) == list(range(10))
    p = next(p for p in paras if p.work_id == "w1:main" and p.paragraph == 5)
    assert isinstance(p.paragraph, int) and isinstance(p.meta["chapter"], int)
    prev = next(q for q in paras if q.work_id == "w1:main" and q.position == p.position - 1)
    nxt = next(q for q in paras if q.work_id == "w1:main" and q.position == p.position + 1)
    assert p.context_before == prev.text[-50:] and p.context_after == nxt.text[:50]
    assert p.source_sha256 == "sha-ws1" and p.corpus_version == "epub-v1-test"
    first = next(q for q in paras if q.work_id == "w1:main" and q.position == 0)
    assert first.context_before == ""


def test_split_paragraph_chunks_kept():
    corpus = H.fake_corpus(10)
    long = next(p for p in corpus.paragraphs if len(p.chunks) > 1)
    assert not long.rebuild_uncertain
    assert all(t in long.text for _, t in long.chunks)


def test_missing_required_field_names_field_and_passage():
    chunks, _i, report = H.fake_chunks(2)
    del chunks[0]["metadata"]["locator"]
    with pytest.raises(C.CorpusError, match=r"locator.*|.*locator"):
        C.build_paragraphs(chunks, report)
    try:
        C.build_paragraphs(chunks, report)
    except C.CorpusError as e:
        assert chunks[0]["metadata"]["passage_id"] in str(e)


def test_load_corpus_through_the_seam(monkeypatch):
    mod = types.ModuleType("builder_fake_provider")
    calls = []

    def provide(sources=None):
        calls.append(sources)
        return H.fake_chunks(5)

    mod.provide = provide
    monkeypatch.setitem(sys.modules, "builder_fake_provider", mod)
    monkeypatch.setenv("INTEGRITY_SEAMS__CORPUS_PROVIDER", "builder_fake_provider:provide")
    s = load_settings()
    corpus = C.load_corpus(s, ["ws1.epub"])
    assert calls == [["ws1.epub"]] and corpus.corpus_version == "epub-v1-test"
    assert len(corpus.paragraphs) == 25


def test_provider_failure_is_a_corpus_error(monkeypatch):
    monkeypatch.setenv("INTEGRITY_SEAMS__CORPUS_PROVIDER", "no_such_module_xyz:f")
    with pytest.raises(C.CorpusError):
        C.load_corpus(load_settings())
