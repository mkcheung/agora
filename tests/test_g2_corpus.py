"""Intentional G2 deltas; five G1 additions must remain byte-identical."""
import json
from pathlib import Path

import pytest

import ingest
from parsers import parse_epub
from scripts.corpus_snapshot import record_hashes

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("require_epubs")


def test_g2_preserves_every_new_book_record():
    chunks, _, _ = ingest.prepare_records()
    g1 = json.loads((ROOT / 'tests/golden/g1_hashes.json').read_text())
    current = record_hashes(chunks)
    new = ('pg3300:', 'pg3420:', 'pg4280:', 'pg5682:', 'pg9662:')
    assert {k:v for k,v in current.items() if k.startswith(new)} == {k:v for k,v in g1.items() if k.startswith(new)}


def test_g2_intended_counts_and_dedications():
    chunks, _, report = ingest.prepare_records()
    assert len(chunks) == 8937
    assert sum(s['blocks'] for s in report['sources']) == 7913
    for file, heading, count in [('pg10615-images-3.epub','THE EPISTLE DEDICATORY',3),
                                 ('pg3207-images-3.epub','THE EPISTLE DEDICATORY',5),
                                 ('pg34901-images-3.epub','DEDICATION',1)]:
        ds=parse_epub(ROOT/file)
        assert sum(d.metadata.get('heading') == heading for d in ds) == count
        assert len({(d.metadata['work_id'],d.metadata['locator']) for d in ds if d.metadata['content_type']!='note'}) == sum(d.metadata['content_type']!='note' for d in ds)


def test_burke_other_speakers_and_strata_move_together():
    from integrity.common.settings import load_settings
    ds=parse_epub(ROOT/'pg15679-images-3.epub')
    army=[d for d in ds if d.metadata['work_id']=='pg15679:substance_of_the_speech' and d.metadata['content_type']!='note']
    assert len(army)==38
    forbidden=('MR. BURKE\'S SPEECH ON THE REPORT OF THE ARMY ESTIMATES', 'MR. FOX THEN ROSE', 'MR. SHERIDAN THEN ROSE', 'N.B. AS TO THE PARTICULAR GENTLEMEN', 'MR. PITT CONCLUDED THE DEBATE')
    assert not any(d.page_content.upper().startswith(forbidden) for d in army)
    rule=next(r for r in load_settings().strata if r.name=='burke-army-estimates')
    assert rule.paragraph_in==['2-36',37,38]


def test_essay_restored_section_and_small_cleanups():
    ds=parse_epub(ROOT/'pg10615-images-3.epub')
    assert any(d.metadata.get('chapter')==21 and d.metadata.get('section')==59 and d.page_content.startswith('1.') for d in ds)
    hobbes=parse_epub(ROOT/'pg3207-images-3.epub')
    assert not any(d.page_content=='FINIS' for d in hobbes)
    assert any(d.metadata.get('chapter')==9 and d.metadata['content_type']=='table' and '\n' in d.page_content for d in hobbes)
    mill=parse_epub(ROOT/'pg27083-images-3.epub')
    assert not any(d.page_content.startswith(': ') for d in mill if d.metadata['content_type']=='note')
