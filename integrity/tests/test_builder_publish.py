import hashlib
import json
import os
import stat

import pytest

from integrity.builder import publish as pub
from integrity.builder.handlers_sheet import cmd_publish, cmd_retire
from integrity.common import schema as sc
from integrity.common import sheets
from integrity.common.settings import load_settings
from integrity.tests.builder_review_helpers import make_real_card, write_batch

B1, B2 = "b-20261121-101500-s7", "b-20261122-101500-s8"


@pytest.fixture
def settings():
    return load_settings()


def approved(key, batch=B1, **kw):
    return make_real_card(key, status="approved", batch_id=batch, **kw)


def second_card_q(q="Why does Locke think reason was given with the world?"):
    return approved("26", B2, question=q)


def test_first_publish_v001(settings):
    write_batch(settings.data_dir, B1, [approved("27"), make_real_card("26")])  # one pending: not published
    r = pub.publish(settings, note="first")
    assert r.version == "v001" and r.sheet.parent is None
    s = sheets.verify_sheet(settings.data_dir, "v001")
    assert s.counts.cards == 1 and s.added == [approved("27").card_id] and s.note == "first"
    assert s.counts.by_author == {"John Locke": 1} and s.counts.by_type == {"passage": 1}
    assert s.corpus.corpus_versions == ["epub-v1-04b8672ea20df6c7"]
    assert s.corpus.sources[0].sha256 == "ab" * 32
    assert s.provenance.batches == [B1] and s.provenance.drafter_prompts == {"drafter_v1": "cd" * 32}
    assert s.content_sha256 == sc.content_sha256(s.cards, version=s.version, parent=s.parent, retired=s.retired)
    mode = stat.S_IMODE(os.stat(r.path).st_mode)
    assert mode == 0o444
    cl = (settings.data_dir / "sheets" / "CHANGELOG.md").read_text()
    assert "## v001" in cl and approved("27").card_id in cl and "first" in cl


def test_publish_nothing_and_empty_refused(settings):
    with pytest.raises(pub.PublishError, match="nothing to publish"):
        pub.publish(settings)
    write_batch(settings.data_dir, B1, [make_real_card("27")])
    with pytest.raises(pub.PublishError, match="nothing to publish"):
        pub.publish(settings)
    assert sheets.list_versions(settings.data_dir) == []


def test_publish_again_refused(settings):
    write_batch(settings.data_dir, B1, [approved("27")])
    pub.publish(settings)
    with pytest.raises(pub.PublishError, match="nothing to publish"):
        pub.publish(settings)
    assert sheets.list_versions(settings.data_dir) == ["v001"]


def test_v002_is_v001_plus_new_minus_retired(settings):
    c27, c26 = approved("27"), second_card_q()
    write_batch(settings.data_dir, B1, [c27])
    pub.publish(settings)
    write_batch(settings.data_dir, B2, [c26])
    pub.stage_retirement(settings, c27.card_id, "wrong attribution found later")
    r = pub.publish(settings, note="second")
    s = sheets.verify_sheet(settings.data_dir, "v002")
    assert s.parent == "v001" and [c.card_id for c in s.cards] == [c26.card_id]
    assert [(x.card_id, x.reason) for x in s.retired] == [(c27.card_id, "wrong attribution found later")]
    assert s.added == [c26.card_id]
    assert pub.read_pending_retirements(settings.data_dir) == []
    # v001 is intact and still holds the retired card
    assert [c.card_id for c in sheets.load_sheet(settings.data_dir, "v001").cards] == [c27.card_id]
    assert "## v002" in (settings.data_dir / "sheets" / "CHANGELOG.md").read_text()
    # retired card that is still approved in its batch does not come back
    with pytest.raises(pub.PublishError, match="nothing to publish"):
        pub.publish(settings)
    assert r.retired[0].card_id == c27.card_id


def test_v002_keeps_v001_cards_plus_new(settings):
    c27, c26 = approved("27"), second_card_q()
    write_batch(settings.data_dir, B1, [c27])
    pub.publish(settings)
    write_batch(settings.data_dir, B2, [c26])
    pub.publish(settings)
    s = sheets.load_sheet(settings.data_dir)
    assert [c.card_id for c in s.cards] == sorted([c27.card_id, c26.card_id])
    assert s.added == [c26.card_id]


def test_retire_validation(settings):
    with pytest.raises(pub.PublishError, match="no published"):
        pub.stage_retirement(settings, "c-x", "r")
    c = approved("27")
    write_batch(settings.data_dir, B1, [c])
    pub.publish(settings)
    with pytest.raises(pub.PublishError, match="not in the latest"):
        pub.stage_retirement(settings, "c-missing", "r")
    with pytest.raises(pub.PublishError, match="non-empty"):
        pub.stage_retirement(settings, c.card_id, "  ")
    pub.stage_retirement(settings, c.card_id, "one")
    pub.stage_retirement(settings, c.card_id, "two")  # restaging replaces
    assert [r["reason"] for r in pub.read_pending_retirements(settings.data_dir)] == ["two"]
    with pytest.raises(pub.PublishError, match="empty"):  # would retire the only card
        pub.publish(settings)


def test_tampered_sheet_fails_to_load(settings):
    write_batch(settings.data_dir, B1, [approved("27")])
    r = pub.publish(settings)
    os.chmod(r.path, 0o644)
    raw = json.loads(r.path.read_text())
    raw["cards"][0]["question"] = "How does Locke tamper?"
    r.path.write_text(json.dumps(raw))
    with pytest.raises(sheets.SheetIntegrityError):
        sheets.load_sheet(settings.data_dir, "v001")
    write_batch(settings.data_dir, B2, [second_card_q()])
    with pytest.raises(pub.PublishError) as ei:  # a corrupted latest sheet blocks publishing
        pub.publish(settings)
    assert ei.value.exit_code == 2


def test_holdout_deterministic_and_stable(settings):
    percent = settings.publish.holdout_percent
    c27, c26 = approved("27"), second_card_q()
    write_batch(settings.data_dir, B1, [c27])
    pub.publish(settings)
    s1 = sheets.load_sheet(settings.data_dir)
    assert s1.cards
    for c in s1.cards:
        expect = int(hashlib.sha256(c.card_id.encode()).hexdigest(), 16) % 100 < percent
        assert c.holdout is expect
    write_batch(settings.data_dir, B2, [c26])
    # raising the percentage must not change existing cards' flags
    settings.publish.holdout_percent = 100
    pub.publish(settings)
    s2 = sheets.load_sheet(settings.data_dir)
    old = {c.card_id: c.holdout for c in s1.cards}
    assert {c.card_id: c.holdout for c in s2.cards if c.card_id in old} == old
    assert next(c for c in s2.cards if c.card_id == c26.card_id).holdout is True
    assert s2.counts.holdout == sum(c.holdout for c in s2.cards)


def test_holdout_function():
    assert pub.holdout_flag("c-abc", 100) and not pub.holdout_flag("c-abc", 0)
    assert pub.holdout_flag("c-abc", 15) == pub.holdout_flag("c-abc", 15)


def test_revalidation_refuses_bad_card(settings):
    bad = approved("27")
    bad.key_points[0].quote = "every man has a property"  # span/quote mismatch
    write_batch(settings.data_dir, B1, [bad])
    with pytest.raises(pub.PublishError, match="failed validation"):
        pub.publish(settings)
    assert sheets.list_versions(settings.data_dir) == []


def test_validate_card_seam(settings):
    write_batch(settings.data_dir, B1, [approved("27")])
    seen = []
    with pytest.raises(pub.PublishError, match="HCX"):
        pub.publish(settings, validate_card=lambda c: [sc.CheckFailure(check="HCX", detail="nope")] + seen)
    r = pub.publish(settings, validate_card=lambda c: [])
    assert r.version == "v001"


def test_publish_with_replacements(settings):
    c27, c26 = approved("27"), second_card_q()
    write_batch(settings.data_dir, B1, [c27, c26])
    settings.publish.holdout_percent = 100
    pub.publish(settings)
    write_batch(settings.data_dir, B2, [approved("26", B2, question="Another Locke question to be left unpublished?")])
    new = c27.model_copy(deep=True)
    new.anchor.corpus_version = "epub-v1-newer"
    new.holdout = False  # replacement cannot change the flag
    settings.publish.holdout_percent = 0
    r = pub.publish_with_replacements(settings, [new])
    s = sheets.load_sheet(settings.data_dir)
    assert s.version == "v002" and s.reanchored == [c27.card_id] and s.added == []
    assert s.note == "re-anchored 1 cards" and s.counts.cards == 2  # unpublished batch card not swept in
    got = next(c for c in s.cards if c.card_id == c27.card_id)
    assert got.anchor.corpus_version == "epub-v1-newer" and got.holdout is True
    assert set(s.corpus.corpus_versions) == {"epub-v1-04b8672ea20df6c7", "epub-v1-newer"}
    assert r.reanchored == [c27.card_id]
    with pytest.raises(pub.PublishError, match="not in the latest"):
        pub.publish_with_replacements(settings, [approved("26", B2, question="Unknown card here?")])


def test_cli_handlers(settings, capsys):
    import argparse

    write_batch(settings.data_dir, B1, [approved("27")])
    assert cmd_publish(argparse.Namespace(note="n"), settings) == 0
    assert "published v001" in capsys.readouterr().out
    assert cmd_publish(argparse.Namespace(note=None), settings) == 1
    assert "nothing to publish" in capsys.readouterr().err
    cid = approved("27").card_id
    assert cmd_retire(argparse.Namespace(card_id=cid, reason="r"), settings) == 0
    assert cmd_retire(argparse.Namespace(card_id="c-zzz", reason="r"), settings) == 1
    # `sheet check` is implemented in builder/maintain.py (Phase A6) and is tested in test_builder_maintain.py


def test_cli_review_no_pending(settings, capsys):
    from integrity.cli import main

    assert main(["review"]) == 1
    assert "no pending batch" in capsys.readouterr().err
    assert main(["publish"]) == 1
    assert main(["retire", "c-x", "--reason", "r"]) == 1
