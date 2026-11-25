"""Corpus safety checks and deliberately versioned offline snapshots."""
import hashlib
import json
from pathlib import Path

import pytest

import ingest


def record_hashes(chunks):
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()[:20]
    return {d.metadata['passage_id']: {
        'text': digest(d.page_content),
        'metadata': digest(json.dumps({k: v for k, v in d.metadata.items()
                                      if k not in ('corpus_version', 'embedded_text_sha256')}, sort_keys=True)),
    } for d in chunks}


def test_golden_corpus(require_epubs):
    expected = json.loads((Path(__file__).parent / 'golden/g2_hashes.json').read_text())
    chunks, _, _ = ingest.prepare_records()
    actual = record_hashes(chunks)
    assert actual == expected


@pytest.mark.parametrize('field', ['chapter', 'section'])
@pytest.mark.parametrize('value', [True, False, 1.0, 1.5, '1'])
def test_numeric_labels_are_integers(field, value):
    from langchain_core.documents import Document
    d = Document(page_content='Original text.', metadata={key: key for key in ingest.REQUIRED_METADATA})
    d.metadata['passage_id'] = 'test:c0'
    ids = ['test:c0']
    d.metadata[field] = value
    with pytest.raises(ValueError, match='whole number'):
        ingest.validate_records([d], ids[:1])


@pytest.mark.parametrize('field', ['DEFAULT_NAMESPACE', 'ACTIVE_NAMESPACE'])
def test_upload_protects_live_namespace(monkeypatch, field):
    monkeypatch.setattr(ingest, field, 'protected')
    monkeypatch.setattr(ingest, 'remote_index', lambda: pytest.fail('opened network client'))
    with pytest.raises(ValueError, match='default or active'):
        ingest.upload_records([], [], {'corpus_version': 'protected'}, 'protected')


def test_reports_are_write_once_and_partial_paths_differ(tmp_path):
    path = tmp_path / 'report.json'
    ingest.save_report(path, {'a': 1})
    ingest.save_report(path, {'a': 1})
    with pytest.raises(ValueError, match='overwrite'):
        ingest.save_report(path, {'a': 2})
    assert json.loads(path.read_text()) == {'a': 1}
    a = {'corpus_version': 'stage', 'selected_sources': [w['file'] for w in ingest.WORKS]}
    b = dict(a, selected_sources=[ingest.WORKS[0]['file']])
    assert ingest.report_path(a) != ingest.report_path(b)


def test_missing_question_fails_before_upload(monkeypatch, require_epubs):
    monkeypatch.delitem(ingest.QUESTIONS, 'pg11224')
    with pytest.raises(ValueError, match='No verification question'):
        ingest.prepare_records(['pg11224-images-3.epub'])
