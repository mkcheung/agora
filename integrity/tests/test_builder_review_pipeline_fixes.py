"""Fixes from the independent review: corpus --source validation without private coupling (M4), source_file
in anchors and sheets (m4), neighbour exclusion inside one batch (m9), publish with drifted settings (m11)."""

import sys
import types

import pytest

from integrity.builder import corpus as C
from integrity.builder import publish as pub
from integrity.builder.build import run_build
from integrity.common import sheets
from integrity.common.settings import load_settings
from integrity.tests import builder_helpers as H
from integrity.tests.builder_review_helpers import make_real_card, write_batch

# --------------------------------------------------------------------------- M4


class StrictProvider:
    """A callable object (no __globals__) that rejects unknown sources the way ingest.prepare_records does."""

    def __init__(self):
        self.calls = []

    def __call__(self, sources=None):
        self.calls.append(sources)
        valid = {"a.epub", "b.epub"}
        if set(sources or valid) - valid:
            raise ValueError(f"Unknown sources: {sorted(set(sources) - valid)}")
        chunks, ids, report = H.fake_chunks(3)
        report["manifest"]["sources"] = [{"file": "a.epub", "sha256": "1"}, {"file": "b.epub", "sha256": "2"}]
        return chunks, ids, report


def install(monkeypatch, provider):
    mod = types.ModuleType("builder_strict_provider")
    mod.provide = provider
    monkeypatch.setitem(sys.modules, "builder_strict_provider", mod)
    monkeypatch.setenv("INTEGRITY_SEAMS__CORPUS_PROVIDER", "builder_strict_provider:provide")


def test_unknown_source_maps_provider_error_to_exit_1_and_lists_valid_names(monkeypatch):
    prov = StrictProvider()
    assert not hasattr(prov, "__globals__")  # the old code relied on provider.__globals__['WORKS']
    install(monkeypatch, prov)
    with pytest.raises(C.UnknownSourceError) as e:
        C.load_corpus(load_settings(), ["nope.epub"])
    assert e.value.exit_code == 1
    assert "nope.epub" in str(e.value) and "a.epub, b.epub" in str(e.value)
    assert prov.calls == [["nope.epub"], None]  # the listing call happens only on the error path
    prov.calls.clear()
    C.load_corpus(load_settings(), ["a.epub"])
    assert prov.calls == [["a.epub"]]


def test_other_provider_value_errors_stay_corpus_errors(monkeypatch):
    def boom(sources=None):
        raise ValueError("Passage/vector identity mismatch")

    install(monkeypatch, boom)
    with pytest.raises(C.CorpusError) as e:
        C.load_corpus(load_settings(), ["a.epub"])
    assert not isinstance(e.value, C.UnknownSourceError) and e.value.exit_code == 4


def test_unknown_source_cli_exit_1(monkeypatch, capsys):
    from integrity import cli

    install(monkeypatch, StrictProvider())
    assert cli.main(["corpus", "--source", "zzz.epub"]) == 1
    assert "zzz.epub" in capsys.readouterr().err


# --------------------------------------------------------------------------- m4


def real_name_report():
    chunks, _ids, report = H.fake_chunks(3)
    report["manifest"]["sources"] = [{"file": "pg3207-images-3.epub", "sha256": "ff" * 32}] + report["manifest"]["sources"]
    report["sources"] = [{"file": "pg3207-images-3.epub", "source_id": "ws1"}] + report["sources"][1:]
    return chunks, report


def test_source_file_travels_from_report_to_paragraph_and_anchor():
    chunks, report = real_name_report()
    paras = C.build_paragraphs(chunks, report)
    p = next(q for q in paras if q.source_id == "ws1")
    assert p.source_file == "pg3207-images-3.epub" and p.anchor_fields()["source_file"] == "pg3207-images-3.epub"


def test_publish_uses_the_real_source_file_name_with_fallback():
    settings = load_settings()
    a = make_real_card("27", status="approved")
    a.anchor.source_file = "pg7370-images-3.epub"
    b = make_real_card("26", status="approved", batch_id="b-20261121-101500-s7")
    b.anchor.source_id, b.anchor.source_sha256 = "pg9999", "ee" * 32  # an old card without source_file
    write_batch(settings.data_dir, "b-20261121-101500-s7", [a, b])
    r = pub.publish(settings)
    files = {s.file for s in r.sheet.corpus.sources}
    assert files == {"pg7370-images-3.epub", "pg9999.epub"}


# --------------------------------------------------------------------------- m9


def accepted_positions(settings, corpus):
    s = run_build(settings, count=100, seed=7, corpus=corpus, drafter_client=H.ScriptedClient(H.good_draft),
                  attribution_client=H.ScriptedClient(H.advisory_ok))
    from integrity.builder.review import load_batch_cards

    cards = load_batch_cards(settings.data_dir, s.batch_id)
    by_work = {}
    for c in cards:
        by_work.setdefault(c.anchor.work_id, []).append(c.anchor.position)
    return s, by_work


def adjacent_pairs(by_work, gap=1):
    return sum(1 for ps in by_work.values() for i in ps for j in ps if 0 < j - i <= gap)


def test_neighbour_exclusion_is_enforced_within_one_batch():
    import shutil

    corpus = H.fake_corpus(30)
    off = load_settings({"build": {"neighbor_exclusion": 0}})
    _s, by_work = accepted_positions(off, corpus)
    assert adjacent_pairs(by_work) > 0  # control: without the rule the dense batch DOES contain neighbours
    shutil.rmtree(off.data_dir / "drafts")  # earlier batches would count as 'used' for the next build

    on = load_settings()
    assert on.build.neighbor_exclusion == 1
    summary, by_work = accepted_positions(on, corpus)
    assert sum(len(v) for v in by_work.values()) > 20  # the batch is not vacuously empty
    assert adjacent_pairs(by_work) == 0
    assert summary.discarded_by_reason.get("neighbor", 0) > 0  # reported, not silent
    assert "neighbor" in summary.format()


# --------------------------------------------------------------------------- m11


def test_tightened_setting_does_not_block_publishing_a_new_card():
    settings = load_settings()
    write_batch(settings.data_dir, "b-20261121-101500-s7", [make_real_card("27", status="approved")])
    assert pub.publish(settings).version == "v001"
    tight = load_settings({"checks": {"max_question_chars": 80}})  # the carried card's question is now too long
    assert len(make_real_card("27").question) > 80
    write_batch(tight.data_dir, "b-20261122-101500-s8",
                [make_real_card("26", status="approved", batch_id="b-20261122-101500-s8")])
    r = pub.publish(tight)
    assert r.version == "v002" and r.added and r.sheet.counts.cards == 2
    assert sheets.verify_sheet(tight.data_dir, "v002").counts.cards == 2


def test_new_cards_are_still_validated_against_current_settings():
    settings = load_settings()
    write_batch(settings.data_dir, "b-20261121-101500-s7", [make_real_card("27", status="approved")])
    pub.publish(settings)
    tight = load_settings({"checks": {"max_question_chars": 30}})
    write_batch(tight.data_dir, "b-20261122-101500-s8",
                [make_real_card("26", status="approved", batch_id="b-20261122-101500-s8")])
    with pytest.raises(pub.PublishError, match="HC2"):
        pub.publish(tight)
