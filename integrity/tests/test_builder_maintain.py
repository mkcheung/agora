import argparse
import json

import pytest

from integrity.builder import maintain
from integrity.builder import publish as pub
from integrity.builder.corpus import Corpus
from integrity.builder.handlers_sheet import cmd_sheet_check
from integrity.common import schema as sc
from integrity.common import sheets, textnorm
from integrity.common.settings import load_settings
from integrity.tests.builder_helpers import mkpara, prose
from integrity.tests.builder_review_helpers import write_batch

WID = "w1:main"
BATCH = "b-20261121-101500-s7"


@pytest.fixture
def settings():
    return load_settings()


def quotes_of(text, n=2):
    """n disjoint 9-word quotes (word-aligned slices of the first sentences)."""
    words = text.split()
    return [" ".join(words[i * 12 + 2:i * 12 + 11]).strip(".,") for i in range(n)]


def card_for(p, question=None):
    q = question or f"What does Locke say in paragraph {p.position}?"
    kps = []
    for i, quote in enumerate(quotes_of(p.text), 1):
        s, e = textnorm.find_span(quote, p.text)
        kps.append(sc.KeyPoint(id=f"kp{i}", statement=f"Statement {i} about {p.position}.", quote=p.text[s:e],
                               quote_model=quote, span=[s, e],
                               chunk_ids=[pid for pid, t in p.chunks if textnorm.find_span(quote, t)]))
    return sc.Card(
        card_id=sc.make_card_id(p.block_id, "passage", q), type="passage", question=q, key_points=kps,
        anchor=sc.Anchor(**p.anchor_fields(), skeleton_sha256=sc.skeleton_sha256(p.text)),
        provenance=sc.Provenance(batch_id=BATCH, slot="s#1", seed=7, attempt=1, drafter_model="m",
                                 drafter_prompt="drafter_v1", drafter_prompt_sha256="cd" * 32),
        review=sc.Review(status="approved"),
    )


def old_paras():
    return [mkpara(prose(100 + i), work_id=WID, position=i) for i in range(8)]


def corpus_of(paras):
    return Corpus(paragraphs=paras, report={}, corpus_version="epub-v1-test")


@pytest.fixture
def published(settings):
    paras = old_paras()
    cards = [card_for(paras[i]) for i in (0, 1, 2, 3, 5, 6)]
    write_batch(settings.data_dir, BATCH, cards)
    pub.publish(settings, note="first")
    return paras, {i: c for i, c in zip((0, 1, 2, 3, 5, 6), cards)}


def new_corpus(paras):
    """p0 same; p1 edited (same block); p2 shifted id; p3 gone but its quotes duplicated in two paragraphs;
    p5 deleted; p6 re-chunked (same text)."""
    out = [paras[0]]
    out.append(mkpara(paras[1].text + " An appended sentence.", work_id=WID, position=1, block_id=paras[1].block_id))
    out.append(mkpara(paras[2].text, work_id=WID, position=2, block_id=f"{WID}:shifted-2"))
    out.append(mkpara("Prefix. " + paras[3].text, work_id=WID, position=3, block_id=f"{WID}:dupA"))
    out.append(mkpara(paras[3].text + " Suffix.", work_id=WID, position=4, block_id=f"{WID}:dupB"))
    t6 = paras[6].text
    half = len(t6) // 2
    out.append(mkpara(t6, work_id=WID, position=5, block_id=paras[6].block_id,
                      chunks=[(f"{paras[6].block_id}:c0", t6[:half + 100]), (f"{paras[6].block_id}:c1", t6[half:])]))
    out.append(mkpara(prose(999), work_id=WID, position=6, block_id=f"{WID}:filler"))
    return corpus_of(out)


def run(settings, monkeypatch, corpus, apply=False):
    monkeypatch.setattr(maintain, "load_corpus", lambda s, sources=None: corpus)
    return cmd_sheet_check(argparse.Namespace(apply=apply), settings)


def test_every_status(settings, published, monkeypatch):
    paras, cards = published
    monkeypatch.setattr(maintain, "load_corpus", lambda s, sources=None: new_corpus(paras))
    rep = maintain.run_check(settings)
    st = {r.card_id: r for r in rep.results}
    assert st[cards[0].card_id].status == "ok"
    assert st[cards[1].card_id].status == "text_changed"
    assert st[cards[2].card_id].status == "moved" and st[cards[2].card_id].target.block_id == f"{WID}:shifted-2"
    amb = st[cards[3].card_id]
    assert amb.status == "ambiguous" and amb.candidates == [f"{WID}:dupA", f"{WID}:dupB"]
    assert st[cards[5].card_id].status == "missing"
    assert st[cards[6].card_id].status == "ok"  # re-chunked, same text
    assert rep.counts() == {"ok": 2, "text_changed": 1, "moved": 1, "ambiguous": 1, "missing": 1}


def test_other_work_does_not_count(settings, published, monkeypatch):
    paras, cards = published
    other = mkpara(paras[5].text, work_id="w2:main", position=0)
    rep_corpus = corpus_of([p for p in old_paras() if p.position != 5] + [other])
    monkeypatch.setattr(maintain, "load_corpus", lambda s, sources=None: rep_corpus)
    st = {r.card_id: r.status for r in maintain.run_check(settings).results}
    assert st[cards[5].card_id] == "missing"


def test_dry_check_writes_nothing(settings, published, monkeypatch, capsys):
    paras, cards = published
    before = sorted(p.name for p in (settings.data_dir / "sheets").iterdir())
    assert run(settings, monkeypatch, new_corpus(paras)) == 0
    out = capsys.readouterr().out
    assert "text_changed" in out and "AMBIGUOUS" in out and f"retire {cards[5].card_id}" in out
    assert sorted(p.name for p in (settings.data_dir / "sheets").iterdir()) == before


def test_apply_reanchors_without_changing_wording(settings, published, monkeypatch, capsys):
    paras, cards = published
    assert run(settings, monkeypatch, new_corpus(paras), apply=True) == 0
    assert "published v002" in capsys.readouterr().out
    v1, v2 = sheets.verify_sheet(settings.data_dir, "v001"), sheets.verify_sheet(settings.data_dir, "v002")
    assert v2.note == "re-anchored 3 cards" and v2.parent == "v001"
    assert sorted(v2.reanchored) == sorted([cards[1].card_id, cards[2].card_id, cards[6].card_id])
    old = {c.card_id: c for c in v1.cards}
    new = {c.card_id: c for c in v2.cards}
    assert old.keys() == new.keys()
    for cid, c in new.items():
        assert c.question == old[cid].question
        assert [k.statement for k in c.key_points] == [k.statement for k in old[cid].key_points]
        assert [k.id for k in c.key_points] == [k.id for k in old[cid].key_points]
        assert c.holdout == old[cid].holdout
    # unchanged labels, ambiguous and missing stay untouched
    for i in (0, 3, 5):
        assert new[cards[i].card_id] == old[cards[i].card_id]
    edited = new[cards[1].card_id]
    assert edited.anchor.text.endswith("An appended sentence.")
    assert edited.anchor.skeleton_sha256 == sc.skeleton_sha256(edited.anchor.text)
    assert edited.key_points
    for kp in edited.key_points:
        assert edited.anchor.text[kp.span[0]:kp.span[1]] == kp.quote
    moved = new[cards[2].card_id]
    assert moved.anchor.block_id == f"{WID}:shifted-2" and moved.anchor.position == 2
    assert moved.key_points[0].chunk_ids == [f"{WID}:shifted-2:c0"]
    # a second check is clean (apply is idempotent)
    monkeypatch.setattr(maintain, "load_corpus", lambda s, sources=None: new_corpus(paras))
    counts = maintain.run_check(settings).counts()
    assert counts["text_changed"] == 0 and counts["moved"] == 0
    assert run(settings, monkeypatch, new_corpus(paras), apply=True) == 0
    assert sheets.list_versions(settings.data_dir) == ["v001", "v002"]


def test_apply_with_nothing_to_do_publishes_nothing(settings, published, monkeypatch, capsys):
    paras, _ = published
    assert run(settings, monkeypatch, corpus_of(paras), apply=True) == 0
    assert "nothing to re-anchor" in capsys.readouterr().out
    assert sheets.list_versions(settings.data_dir) == ["v001"]


def test_apply_skips_cards_failing_hard_checks(settings, published, monkeypatch, capsys):
    paras, cards = published
    # edit changes the quoted words so that the card still matches but make the validator reject it
    monkeypatch.setattr(maintain, "make_validator",
                        lambda s: (lambda c: [sc.CheckFailure(check="HC6", detail="boom")] if c.anchor.block_id.endswith("shifted-2") else []))
    assert run(settings, monkeypatch, new_corpus(paras), apply=True) == 1
    cap = capsys.readouterr()
    assert "could not re-anchor" in cap.err and "boom" in cap.err
    v2 = sheets.load_sheet(settings.data_dir, "v002")
    assert sorted(v2.reanchored) == sorted([cards[1].card_id, cards[6].card_id])


def test_no_sheet_exit_2(settings, monkeypatch, capsys):
    assert run(settings, monkeypatch, corpus_of(old_paras())) == 2
    assert "no valid published answer sheet" in capsys.readouterr().err
    assert run(settings, monkeypatch, corpus_of(old_paras()), apply=True) == 2


def test_corpus_error_exit_4(settings, published, monkeypatch, capsys):
    def boom(s, sources=None):
        raise maintain.CorpusError("provider exploded")

    monkeypatch.setattr(maintain, "load_corpus", boom)
    assert cmd_sheet_check(argparse.Namespace(apply=False), settings) == 4
    assert "provider exploded" in capsys.readouterr().err


def test_cli_dispatch(settings, published, monkeypatch, capsys):
    from integrity.cli import main

    paras, _ = published
    monkeypatch.setattr(maintain, "load_corpus", lambda s, sources=None: corpus_of(paras))
    assert main(["sheet", "check"]) == 0
    assert "ok" in capsys.readouterr().out


# --------------------------------------------------------------------------- real corpus


def test_real_locke_card_is_ok(settings):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if not any(root.glob("*.epub")):
        pytest.skip("EPUBs not present")
    from integrity.builder.corpus import load_corpus
    from integrity.tests.builder_review_helpers import PARAS, make_real_card

    corpus = load_corpus(settings)
    p = next(x for x in corpus.paragraphs if x.work_id == "pg7370:main" and x.position == 40)
    assert p.text.startswith("Sect. 27.")
    spec = PARAS["27"]
    kps = []
    for i, (stmt, quote) in enumerate(spec["kps"], 1):
        s, e = textnorm.find_span(quote, p.text)
        kps.append(sc.KeyPoint(id=f"kp{i}", statement=stmt, quote=p.text[s:e], quote_model=quote, span=[s, e],
                               chunk_ids=[pid for pid, t in p.chunks if textnorm.find_span(quote, t)]))
    base = make_real_card("27", status="approved", batch_id=BATCH)
    card = base.model_copy(update={
        "key_points": kps, "anchor": sc.Anchor(**maintain.anchor_kwargs(p), skeleton_sha256=sc.skeleton_sha256(p.text)),
        "card_id": sc.make_card_id(p.block_id, "passage", base.question),
    })
    write_batch(settings.data_dir, BATCH, [card])
    pub.publish(settings, note="real")
    rep = maintain.run_check(settings, corpus)
    assert [r.status for r in rep.results] == ["ok"]
    assert json.loads(json.dumps(rep.counts()))["ok"] == 1


def test_reanchor_keeps_text_labels_book_part_volume():
    paras = old_paras()
    card = card_for(paras[0])
    p = mkpara(paras[0].text, work_id=WID, position=0, block_id=paras[0].block_id)
    p.meta.update({"book": "Book II", "part": "Part I", "volume": "Volume 1", "chapter": 5, "section": 27})
    kw = maintain.anchor_kwargs(p)
    assert kw["book"] == "Book II" and kw["part"] == "Part I" and kw["volume"] == "Volume 1"
    new = maintain.reanchor_card(card, p)
    assert (new.anchor.book, new.anchor.part, new.anchor.volume) == ("Book II", "Part I", "Volume 1")
    assert new.anchor.chapter == 5 and new.anchor.section == 27
    p.meta["chapter"] = "five"  # a non-numeric value in a numeric field is still dropped
    assert "chapter" not in maintain.anchor_kwargs(p)


def test_sheet_check_prints_attention_for_missing_and_ambiguous_but_exits_0(settings, published, monkeypatch, capsys):
    paras, _cards = published
    assert run(settings, monkeypatch, new_corpus(paras)) == 0
    out = capsys.readouterr().out
    assert "ATTENTION: 1 missing and 1 ambiguous" in out
    assert run(settings, monkeypatch, corpus_of(old_paras())) == 0  # nothing missing here (all 8 present)
    out = capsys.readouterr().out
    assert "ATTENTION" not in out and "ok" in out


def test_ok_cards_refresh_labels_and_version_only_when_applied(settings, published, monkeypatch):
    paras, cards = published
    p = paras[0]
    p.locator = 'Corrected printed locator'
    p.corpus_version = 'new-generation'
    rep = maintain.run_check(settings, corpus_of(paras))
    assert all(r.status == 'ok' for r in rep.results)
    result = maintain.apply_reanchoring(settings, rep)
    assert result.version == 'v002' and result.reanchored == [cards[0].card_id]
    refreshed = next(c for c in sheets.load_sheet(settings.data_dir,'v002').cards if c.card_id == cards[0].card_id)
    assert refreshed.anchor.locator == p.locator
    assert refreshed.anchor.corpus_version == 'new-generation'
    assert refreshed.question == cards[0].question
    assert refreshed.key_points == cards[0].key_points
    assert maintain.apply_reanchoring(settings, maintain.run_check(settings,corpus_of(paras))).version is None
