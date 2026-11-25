"""Structural assertions against the exact twelve locally backed-up EPUB inputs."""
import re
from collections import Counter

import pytest

from ingest import ROOT, WORKS
from parsers import parse_epub


@pytest.fixture(scope='module')
def books():
    return {w['profile']: parse_epub(ROOT / w['file'], w['profile']) for w in WORKS[7:]}


def body(docs):
    return [d for d in docs if d.metadata['content_type'] != 'note']


def find(docs, start):
    return next(d for d in docs if d.page_content.startswith(start))


def test_every_new_book_labels_and_notes(books):
    for docs in books.values():
        b = body(docs)
        locators = [d.metadata['locator'] for d in b]
        assert len(set(locators)) == len(locators)
        assert all('—' not in l and 'Æ' not in l for l in locators)
        assert all(isinstance(d.metadata[k], int) and not isinstance(d.metadata[k], bool)
                   for d in docs for k in ('chapter', 'section') if k in d.metadata)
        by_id = {d.metadata['block_id']: d for d in b}
        for note in [d for d in docs if d.metadata['content_type'] == 'note']:
            assert note.metadata['reference_block_id'] in by_id


def test_smith_structure(books):
    ds = books['smith']
    for prefix, locator in [
        ('The annual labour of every nation is the fund', 'Introduction and Plan of the Work, paragraph 1'),
        ('In that rude state of society', 'Book II, Introduction, paragraph 1'),
        ('Political economy, considered as a branch', 'Book IV, paragraph 1'),
    ]:
        assert find(ds, prefix).metadata['locator'].startswith(locator + ' (')
    for book, chapters in [('I', 11), ('II', 5), ('III', 4), ('IV', 9), ('V', 3)]:
        assert {d.metadata['chapter'] for d in ds if d.metadata.get('book') == 'Book ' + book and 'chapter' in d.metadata} == set(range(1, chapters + 1))
    assert {d.metadata.get('heading') for d in ds if d.metadata.get('book') == 'Book V' and d.metadata.get('chapter') == 1} >= {'Part I', 'Part II', 'Part III', 'Part IV', 'Conclusion'}
    assert all('part' not in d.metadata for d in ds)
    assert Counter(d.metadata['content_type'] for d in ds)['table'] == 10
    assert len(ds) == 2098


def test_wollstonecraft_structure(books):
    ds = books['wollstonecraft']
    assert all('M. Wollstonecraft was born in 1759' not in d.page_content and 'memoir written by her afflicted husband' not in d.page_content and '2001' not in d.page_content for d in ds)
    assert find(ds, 'Having read with great pleasure a pamphlet').metadata['locator'].startswith('Dedication, paragraph 2 ')
    assert find(ds, 'After considering the historic page').metadata['locator'].startswith('Introduction, paragraph 1 ')
    assert {d.metadata['chapter'] for d in ds if 'chapter' in d.metadata} == set(range(1, 14))
    assert {(d.metadata['chapter'], d.metadata['section']) for d in ds if 'section' in d.metadata} == {(5, i) for i in range(1, 6)} | {(13, i) for i in range(1, 7)}
    assert sum(d.metadata['content_type'] == 'note' for d in ds) == 22
    assert not any('*' in d.page_content or '>From' in d.page_content for d in ds)
    assert all(d.metadata['work'] == 'A Vindication of the Rights of Woman' for d in ds)


def test_critique_structure(books):
    ds = books['critique']
    b = body(ds)
    assert sum(d.metadata.get('division') == 'Preface to the First Edition' for d in b) == 17
    assert sum(d.metadata.get('division') == 'Preface to the Second Edition' for d in b) == 26
    assert {d.metadata.get('heading') for d in b if d.metadata.get('division') == 'Introduction'} == {'Section ' + n for n in ('I','II','III','IV','V','VI','VII')}
    method = [d for d in b if d.metadata.get('division') == 'Doctrine of Method']
    assert all('book' not in d.metadata for d in method)
    assert {d.metadata['chapter'] for d in method if 'chapter' in d.metadata} == {1, 2, 3, 4}
    for name, end in [('Transcendental Aesthetic', 10), ('Transcendental Analytic', 23)]:
        assert {d.metadata['section'] for d in ds if d.metadata.get('division') == name and 'section' in d.metadata} == set(range(1, end + 1))
    assert all('division' in d.metadata for d in ds)
    assert not any(re.search(r'\[\d+\]', d.page_content) for d in ds)
    assert find(ds, 'FIRST CONFLICT').page_content.startswith('FIRST CONFLICT OF THE TRANSCENDENTAL IDEAS. THESIS.')
    assert not any(d.page_content in {'PROOF.', 'ANTITHESIS.'} for d in ds)
    assert sum(d.metadata['content_type'] == 'table' for d in ds) == 7
    assert sum(d.metadata['content_type'] == 'note' for d in ds) == 76  # five translator glosses excluded


def test_groundwork_structure(books):
    ds = books['groundwork']
    assert Counter(d.metadata['division'] for d in body(ds)) == {'Preface': 17, 'First Section': 21, 'Second Section': 90, 'Third Section': 35}
    assert not any('*' in d.page_content or 'chapter' in d.metadata or 'section' in d.metadata for d in ds)
    assert body(ds)[-1].metadata['subheading'] == 'CONCLUDING REMARK'
    assert body(ds)[-1].metadata['division'] == 'Third Section'
    assert sum(d.metadata['content_type'] == 'note' for d in ds) == 18


def test_hume_structure(books):
    ds = books['hume']
    assert {d.metadata['section'] for d in body(ds)} == set(range(1, 133))
    assert not any(re.match(r'^\d+\. ', d.page_content) or 'Extracted from' in d.page_content for d in ds)
    nine = next(d for d in ds if d.metadata['locator'].startswith('Note footnote9 '))
    assert nine.metadata['section'] == 46 and nine.metadata['paragraph'] == 1
    assert sum(d.metadata['content_type'] == 'note' for d in ds) == 34
    assert not any(d.page_content.startswith('Footnote') for d in ds)
    assert {d.metadata['division'] for d in body(ds) if 'part' in d.metadata} == {'Section ' + n for n in ('IV','V','VII','VIII','X','XII')}
    assert all(d.metadata['division'] == 'Section XII' for d in body(ds) if d.metadata.get('part') == 'Part III')
    report = {}
    parse_epub(ROOT / 'pg9662-images-3.epub', report=report)
    index = next(e for e in report['excluded_locations'] if e['preview'] == 'INDEX.')
    excluded = [e for e in report['excluded_locations'] if e['source_href'] == index['source_href']
                and e['source_block'] > index['source_block'] and e['reason'] != 'navigation/license/formatting']
    assert len(excluded) == 1425


def test_new_profiles_reject_unknown_selected_headings(tmp_path):
    from tests.test_epub_pipeline import make_epub
    path = make_epub(tmp_path, ['<h2>INTRODUCTION AND PLAN OF THE WORK.</h2><p>Body.</p><h3>Unrecognised appendix</h3>'], source='3300')
    with pytest.raises(ValueError, match='Unrecognised Smith heading'):
        parse_epub(path)
