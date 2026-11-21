import json
import os

import pytest

from integrity.common import sheets as sh
from integrity.tests.helpers import make_card, make_sheet_dict


def publish(data_dir, **kw):
    d = make_sheet_dict(**kw)
    return sh.write_sheet(data_dir, d), d


def test_empty_dir_lists_nothing_and_resolve_raises(data_dir):
    assert sh.list_versions(data_dir) == [] and sh.latest_version(data_dir) is None
    with pytest.raises(sh.SheetNotFoundError) as e:
        sh.resolve(data_dir, "latest")
    assert e.value.exit_code == 2


def test_write_load_roundtrip_read_only(data_dir):
    path, d = publish(data_dir)
    assert path.name == "sheet-v001.json" and (path.stat().st_mode & 0o777) == 0o444
    sheet = sh.load_sheet(data_dir, "v001")
    assert sheet.version == "v001" and sheet.counts.cards == 1
    assert sheet.content_sha256 == sh.compute_content_sha256(d["cards"], version="v001", parent=None, retired=[])
    assert sh.verify_sheet(data_dir).version == "v001"


def test_write_once(data_dir):
    publish(data_dir)
    with pytest.raises(sh.SheetIntegrityError, match="already exists"):
        sh.write_sheet(data_dir, make_sheet_dict())


def test_write_refuses_bad_hash(data_dir):
    d = make_sheet_dict()
    d["content_sha256"] = "0" * 64
    with pytest.raises(sh.SheetIntegrityError):
        sh.write_sheet(data_dir, d)
    assert sh.list_versions(data_dir) == []


def test_latest_is_highest_and_version_spellings(data_dir):
    for n in (1, 2, 10):
        publish(data_dir, version=f"v{n:03d}")
    assert sh.list_versions(data_dir) == ["v001", "v002", "v010"]
    assert sh.resolve(data_dir)[0] == "v010"
    assert sh.resolve(data_dir, "2")[0] == "v002"
    assert sh.resolve(data_dir, "V001")[0] == "v001"
    with pytest.raises(sh.SheetNotFoundError):
        sh.resolve(data_dir, "v003")
    with pytest.raises(sh.SheetNotFoundError):
        sh.resolve(data_dir, "banana")


def test_tampered_sheet_refused(data_dir):
    path, _ = publish(data_dir)
    os.chmod(path, 0o644)
    raw = json.loads(path.read_text())
    raw["cards"][0]["question"] = "Tampered?"
    path.write_text(json.dumps(raw))
    with pytest.raises(sh.SheetIntegrityError, match="content_sha256 mismatch"):
        sh.load_sheet(data_dir, "v001")


def test_corrupt_unsupported_and_mislabelled(data_dir):
    path, _ = publish(data_dir)
    os.chmod(path, 0o644)
    raw = json.loads(path.read_text())
    path.write_text("{not json")
    with pytest.raises(sh.SheetIntegrityError, match="cannot read"):
        sh.load_sheet(data_dir)
    for key, val, msg in (("schema_version", 99, "schema_version"), ("version", "v009", "does not match")):
        r = dict(raw, **{key: val})
        path.write_text(json.dumps(r))
        with pytest.raises(sh.SheetIntegrityError, match=msg):
            sh.load_sheet(data_dir)


def test_unapproved_card_refused(data_dir):
    card = make_card(review={"status": "pending"})
    publish(data_dir, cards=[card])
    with pytest.raises(sh.SheetIntegrityError, match="not approved"):
        sh.load_sheet(data_dir)


def test_summarize_marks_invalid(data_dir):
    publish(data_dir)
    path, _ = publish(data_dir, version="v002", parent="v001")
    os.chmod(path, 0o644)
    path.write_text("x")
    rows = sh.summarize_versions(data_dir)
    assert rows[0]["cards"] == 1 and rows[0]["version"] == "v001"
    assert "error" in rows[1]


def test_changelog_append(data_dir):
    sh.append_changelog(data_dir, "## v001\nfirst")
    sh.append_changelog(data_dir, "## v002\nsecond")
    text = (data_dir / "sheets" / "CHANGELOG.md").read_text()
    assert text.index("## v001") < text.index("## v002")
    assert "first\n\n## v002" in text


def _tamper(data_dir, mutate):
    path, _ = publish(data_dir, version="v001")
    os.chmod(path, 0o644)
    raw = json.loads(path.read_text())
    mutate(raw)
    path.write_text(json.dumps(raw))


def test_hash_covers_retired_and_version_and_counts(data_dir):
    import pytest as _p

    def retire(raw):
        raw["retired"] = [{"card_id": "c-x", "reason": "r"}]

    def counts(raw):
        raw["counts"]["cards"] = 99

    def counts_author(raw):
        raw["counts"]["by_author"] = {"Somebody": 1}

    def version(raw):
        raw["version"] = "v002"

    cases = (retire, counts, counts_author, version)
    ran = 0
    for fn in cases:
        d = data_dir / f"case{ran}"
        d.mkdir()
        _tamper(d, fn)
        with _p.raises(sh.SheetIntegrityError):
            sh.load_sheet(d, "v001")
        ran += 1
    assert ran == len(cases)


def test_free_text_fields_may_be_edited(data_dir):
    def edit(raw):
        raw["note"] = "edited note"
        raw["created_at"] = "2030-01-01T00:00:00Z"

    _tamper(data_dir, edit)
    assert sh.load_sheet(data_dir, "v001").note == "edited note"


def test_parent_is_hashed(data_dir):
    publish(data_dir, version="v001")
    path, _ = publish(data_dir, version="v002", parent="v001")
    os.chmod(path, 0o644)
    raw = json.loads(path.read_text())
    raw["parent"] = None
    path.write_text(json.dumps(raw))
    with pytest.raises(sh.SheetIntegrityError, match="content_sha256 mismatch"):
        sh.load_sheet(data_dir, "v002")


def test_write_refuses_wrong_counts(data_dir):
    d = make_sheet_dict()
    d["counts"]["cards"] = 5
    with pytest.raises(sh.SheetIntegrityError, match="counts"):
        sh.write_sheet(data_dir, d)
