"""Offline regression and contract tests; real EPUB integration is skipped if absent."""

import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from ebooklib import epub
from langchain_core.documents import Document

import ingest
from ask import Citation, assemble_context, build_verification_index, verify_citations
from chunking import CHUNK_SIZE, chunk_paragraphs
from parsers import parse_epub, table_text

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected network access in offline tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(scope="module")
def corpus():
    if not all((ROOT / w['file']).exists() for w in ingest.WORKS):
        pytest.skip("Downloaded Gutenberg EPUBs are local, ignored input files")
    return ingest.prepare_records()


def make_epub(tmp_path, bodies, source="11224"):
    book = epub.EpubBook()
    book.set_identifier(f"http://www.gutenberg.org/{source}")
    book.set_title("Fixture work")
    book.set_language("en")
    book.add_author("Fixture author")
    pages = []
    for n, body in enumerate(bodies):
        page = epub.EpubHtml(title=f"Page {n}", file_name=f"part{n}.xhtml", lang="en")
        page.content = f"<html><body>{body}</body></html>"
        book.add_item(page)
        pages.append(page)
    nav = epub.EpubNav()
    nav.content = '<html><body><h2>CHAPTER XCIX.</h2><p>Navigation should never appear.</p></body></html>'
    book.add_item(nav)
    book.spine = pages
    path = tmp_path / "fixture.epub"
    epub.write_epub(str(path), book)
    return path


def test_spine_continuity_and_nonspine_exclusion(tmp_path):
    path = make_epub(tmp_path, ['<h2>CHAPTER I.</h2><p>Opening argument.</p>', '<p>Continuing argument.</p>'])
    docs = parse_epub(path)
    assert [d.page_content for d in docs] == ['Opening argument.', 'Continuing argument.']
    assert [d.metadata['chapter'] for d in docs] == [1, 1]
    assert [d.metadata['paragraph'] for d in docs] == [1, 2]


def test_book_resets_and_real_sections(tmp_path):
    path = make_epub(tmp_path, ['<h2>BOOK I</h2><h2>CHAPTER I. First</h2><p>1. Topic one.</p><p>First argument.</p>',
                               '<h2>BOOK II</h2><h2>CHAPTER I. Second</h2><p>1. Topic two.</p><p>Second argument.</p>'], '10615')
    docs, ids = chunk_paragraphs(parse_epub(path))
    assert len(set(ids)) == 2
    assert [d.metadata['book'] for d in docs] == ['Book I', 'Book II']
    assert [d.metadata['section'] for d in docs] == [1, 1]
    assert [d.metadata['chapter_title'] for d in docs] == ['First', 'Second']


def test_cross_file_note_uses_reference_chapter(tmp_path):
    path = make_epub(tmp_path, ['<h2>CHAPTER III.</h2><p>Argument<a id="ref_1"></a><a class="fnref" href="part1.xhtml#footnote_1">1</a>.</p>',
                               '<h2>CHAPTER IV.</h2><p>Different chapter.</p><div class="footnote"><p><a id="footnote_1" href="part0.xhtml#ref_1">1</a>Earlier chapter note.</p></div>'])
    docs = parse_epub(path)
    note = next(d for d in docs if d.metadata['content_type'] == 'note')
    assert note.metadata['chapter'] == 3
    assert note.metadata['reference_block_id'] == docs[0].metadata['block_id']
    assert note.page_content == 'Earlier chapter note.'


def test_unresolved_selected_note_fails(tmp_path):
    path = make_epub(tmp_path, ['<h2>CHAPTER I.</h2><p>Body.</p><div class="footnote"><p>No reference.</p></div>'])
    with pytest.raises(ValueError, match='Unresolved selected notes'):
        parse_epub(path)


def test_unknown_selected_text_fails(tmp_path):
    path = make_epub(tmp_path, ['<h2>CHAPTER I.</h2><div>Unrecognized direct body text.</div>'])
    with pytest.raises(ValueError, match='Unhandled selected text'):
        parse_epub(path)


def test_no_selected_body_fails(tmp_path):
    path = make_epub(tmp_path, ['<h1>Title page only</h1><p>Editorial introduction.</p>'])
    with pytest.raises(ValueError, match='No selected body'):
        parse_epub(path)


def test_tables_preserve_single_column_verse_and_label_data():
    single = BeautifulSoup('<table><tr><td>First line</td></tr><tr><td>Second line</td></tr></table>', 'html.parser').table
    assert table_text(single) == 'First line\nSecond line'
    table = BeautifulSoup('<table><tr><td></td><td>Livres</td></tr><tr><td>Charity</td><td>3,866,920</td></tr></table>', 'html.parser').table
    assert table_text(table) == 'Item: Charity | Livres: 3,866,920'
    table.td['colspan'] = '2'
    with pytest.raises(ValueError, match='spanning-cell'):
        table_text(table)


def citation(doc, **overrides):
    meta = doc.metadata
    data = {k: meta[k] for k in ['author', 'work', 'locator', 'passage_id', 'chapter', 'section'] if k in meta}
    return Citation(**(dict(data, quote=doc.page_content[:80]) | overrides))


def example(chapter=None):
    meta = {'author': 'Author', 'work': 'Work', 'passage_id': 'one:c0', 'locator': 'Native heading, paragraph 1'}
    if chapter is not None:
        meta['chapter'] = chapter
    return Document(page_content='A continuous quotation supports this argument. A different sentence follows.', metadata=meta)


@pytest.mark.parametrize('chapter', [None, 1])
def test_generic_context_and_citation(chapter):
    doc = example(chapter)
    assert '"passage_id": "one:c0"' in assemble_context([doc])
    assert verify_citations(build_verification_index([doc]), [citation(doc)])[0]['status'] == 'ok'


@pytest.mark.parametrize(('overrides', 'status'), [
    ({'passage_id': 'unknown'}, 'unknown passage'),
    ({'work': 'Wrong work'}, 'source mismatch'),
    ({'author': 'Wrong author'}, 'source mismatch'),
    ({'locator': 'Wrong location'}, 'source mismatch'),
    ({'chapter': 9}, 'source mismatch'),
    ({'quote': ''}, 'quote not found'),
    ({'quote': '   '}, 'quote not found'),
    ({'quote': 'A continuous ... argument.'}, 'quote not found'),
    ({'quote': 'Invented quotation.'}, 'quote not found'),
])
def test_invalid_citations_rejected(overrides, status):
    doc = example()
    assert verify_citations(build_verification_index([doc]), [citation(doc, **overrides)])[0]['status'] == status


def test_exact_chunk_identity_and_duplicate_rejection():
    first, second = example(1), example(1)
    second.metadata.update(passage_id='two:c0', locator='Book II, Chapter 1')
    second.page_content = 'Different words in the second book.'
    index = build_verification_index([first, second])
    assert verify_citations(index, [citation(second, quote=first.page_content)])[0]['status'] == 'quote not found'
    with pytest.raises(ValueError, match='Duplicate retrieved'):
        build_verification_index([first, first])


def test_chunk_identity_metadata_and_repeatability():
    doc = example()
    doc.metadata.update(block_id='source:work:block')
    doc.page_content = 'Long philosophical argument. ' * 200
    original = dict(doc.metadata)
    a, ids = chunk_paragraphs([doc])
    b, more_ids = chunk_paragraphs([doc])
    assert ids == more_ids and len(set(ids)) == len(ids) > 1
    assert [d.page_content for d in a] == [d.page_content for d in b]
    assert all(len(d.page_content) <= CHUNK_SIZE for d in a)
    assert all(d.metadata['passage_id'] == d.id for d in a)
    assert doc.metadata == original
    with pytest.raises(ValueError, match='Duplicate passage'):
        chunk_paragraphs([doc, doc])


def test_full_corpus_coverage_and_clean_metadata(corpus):
    chunks, ids, report = corpus
    assert len(report['sources']) == 7 and report['logical_works'] == 9
    ingest.validate_records(chunks, ids)
    assert all('PROJECT GUTENBERG' not in d.page_content.upper() for d in chunks)
    assert all('THE END.' != d.page_content for d in chunks)
    assert len(set(ids)) == len(ids)
    assert all(d.metadata['source_href'] != 'toc.xhtml' for d in chunks)
    for doc in chunks:
        assert all(v is not None for v in doc.metadata.values())


def test_real_corpus_hierarchy_and_attribution(corpus):
    chunks, _, _ = corpus
    essay = [d for d in chunks if d.metadata['source_id'] == 'pg10615']
    assert {d.metadata['book'] for d in essay if 'book' in d.metadata} == {'Book I', 'Book II'}
    assert all(any(d.metadata.get('book') == book and d.metadata.get('chapter') == 1 for d in essay)
               for book in ['Book I', 'Book II'])
    hobbes = [d for d in chunks if d.metadata['source_id'] == 'pg3207']
    assert {d.metadata['chapter'] for d in hobbes if 'chapter' in d.metadata} == set(range(1, 48))
    assert {d.metadata['part'] for d in hobbes if 'part' in d.metadata} == {'Part I', 'Part II', 'Part III', 'Part IV'}
    mill = [d for d in chunks if d.metadata['source_id'] == 'pg11224']
    assert next(d for d in mill if d.metadata['chapter'] == 1).metadata['chapter_title'] == 'GENERAL REMARKS.'
    liberty = [d for d in chunks if d.metadata['source_id'] == 'pg34901']
    assert {d.metadata['chapter'] for d in liberty} == set(range(1, 6))
    assert not any('W. L. COURTNEY' in d.page_content.upper() for d in liberty)
    burke = [d for d in chunks if d.metadata['source_id'] == 'pg15679']
    assert len({d.metadata['work'] for d in burke}) == 3
    assert all('chapter' not in d.metadata for d in burke)
    assert any('3,866,920' in d.page_content and 'Livres' in d.page_content for d in burke)
    assert any(d.metadata['content_type'] == 'verse' and '\n' in d.page_content for d in burke)
    assert not any("Transcriber's note:" in d.page_content or 'Mr. Burke probably had' in d.page_content for d in burke)
    note = next(d for d in chunks if d.metadata.get('source_anchor') == 'footnote_2_1')
    assert note.metadata['chapter'] == 3


def test_locke_sections_and_known_text(corpus):
    chunks, _, _ = corpus
    locke = [d for d in chunks if d.metadata['source_id'] == 'pg7370']
    assert {d.metadata['chapter'] for d in locke if 'chapter' in d.metadata} == set(range(1, 20))
    assert {d.metadata['section'] for d in locke if 'section' in d.metadata} == set(range(1, 244))
    assert any('The labour of his body' in d.page_content and d.metadata.get('section') == 27 for d in locke)
    assert any(d.metadata.get('heading') == 'PREFACE' for d in locke)


def test_offline_preparation_is_repeatable(corpus):
    chunks, ids, report = corpus
    again, more_ids, more_report = ingest.prepare_records()
    assert more_ids == ids
    assert [d.model_dump() for d in chunks] == [d.model_dump() for d in again]
    assert report == more_report


def test_invalid_metadata_fails(corpus):
    chunks, ids, _ = corpus
    invalid = chunks[0].model_copy(deep=True)
    invalid.metadata['chapter_title'] = None
    with pytest.raises(ValueError, match='Invalid metadata'):
        ingest.validate_records([invalid], ids[:1])


def test_upload_failure_and_resume_without_duplicate_embedding(monkeypatch, tmp_path, corpus):
    chunks, ids, report = corpus
    chunks, ids = chunks[:3], ids[:3]
    calls = []
    class Embeddings:
        def __init__(self, **kwargs):
            pass
        def embed_documents(self, texts):
            calls.append(len(texts))
            return [[0.] * 1024 for _ in texts]
    class Index:
        fail = True
        def upsert(self, vectors, namespace):
            if len(vectors) == 1 and self.fail:
                raise RuntimeError('simulated last batch failure')
            return SimpleNamespace(upserted_count=len(vectors))
    index = Index()
    monkeypatch.setattr(ingest, 'remote_index', lambda: index)
    import langchain_openai
    monkeypatch.setattr(langchain_openai, 'OpenAIEmbeddings', Embeddings)
    progress = tmp_path / 'progress.json'
    with pytest.raises(RuntimeError, match='simulated'):
        ingest.upload_records(chunks, ids, report, report['corpus_version'], 2, progress)
    assert len(json.loads(progress.read_text())['completed_ids']) == 2
    index.fail = False
    ingest.upload_records(chunks, ids, report, report['corpus_version'], 2, progress)
    assert calls == [2, 1, 1]
    ingest.upload_records(chunks, ids, report, report['corpus_version'], 2, progress)
    assert calls == [2, 1, 1]
    with pytest.raises(ValueError, match='staging namespace'):
        ingest.upload_records(chunks, ids, report, '', 2, progress)


def test_offline_cli_without_credentials(corpus):
    # Install the network tripwire before importing the CLI in a fresh interpreter.
    code = """
import os, socket, sys
for key in list(os.environ):
    if key.endswith('API_KEY'):
        os.environ.pop(key)
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
def blocked(*a, **kw):
    raise AssertionError('Offline CLI attempted network access')
socket.socket.connect = blocked
socket.create_connection = blocked
import ingest
sys.argv = ['ingest.py']
ingest.main()
"""
    result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert 'Offline preparation only' in result.stdout


def test_retrieval_namespace_cache_and_existing_interface(monkeypatch):
    import retrieval
    constructed = []
    class Store:
        def __init__(self, **kwargs):
            self.namespace = kwargs['namespace']
            constructed.append(self.namespace)
        def similarity_search(self, question, k, filter):
            return (question, k, filter)
    monkeypatch.setattr(retrieval, 'OpenAIEmbeddings', lambda **kwargs: object())
    monkeypatch.setattr(retrieval, 'PineconeVectorStore', Store)
    factory = retrieval.get_vectorstore
    factory.cache_clear()
    try:
        first = retrieval.get_vectorstore('stage-one')
        assert retrieval.get_vectorstore('stage-one') is first
        assert retrieval.get_vectorstore('stage-two') is not first
        assert constructed == ['stage-one', 'stage-two']
        monkeypatch.setattr(retrieval, 'get_vectorstore', lambda: first)
        assert retrieval.retrieve('question', 3, {'author': 'Author'}) == ('question', 3, {'author': 'Author'})
    finally:
        factory.cache_clear()


def test_wrong_index_dimension_stops_before_opening_index(monkeypatch):
    import pinecone
    class Client:
        def describe_index(self, name):
            return SimpleNamespace(dimension=1536, host='unused')
        def Index(self, **kwargs):
            pytest.fail('Index opened despite incompatible dimensions')
    monkeypatch.setattr(pinecone, 'Pinecone', Client)
    with pytest.raises(ValueError, match='Index dimension'):
        ingest.remote_index()


def test_selected_model_and_schema_construct_without_network(monkeypatch):
    from langchain.chat_models import init_chat_model

    from ask import ResearchedResponse, prompt
    monkeypatch.setenv('GROQ_API_KEY', 'offline-test-key')
    model = init_chat_model('groq:openai/gpt-oss-120b')
    structured = model.with_structured_output(ResearchedResponse, method='json_schema')
    assert prompt | structured


def test_one_correction_attempt_keeps_strict_quote_checks():
    from ask import ResearchedResponse, invoke_with_verification
    doc = example()
    bad = ResearchedResponse(Answer='A claim.', Citations=[citation(doc, quote='A continuous ... argument.')])
    good = ResearchedResponse(Answer='A supported claim.', Citations=[citation(doc)])
    class Chain:
        def __init__(self, responses):
            self.responses = iter(responses)
            self.requests = []
        def invoke(self, request):
            self.requests.append(request)
            return next(self.responses)
    chain = Chain([bad, good])
    response, checks = invoke_with_verification(chain, 'Question?', assemble_context([doc]), build_verification_index([doc]))
    assert response == good and checks[0]['status'] == 'ok'
    assert len(chain.requests) == 2 and 'quote not found' in chain.requests[1]['question']
    assert chain.requests[0]['context'] == chain.requests[1]['context']
    chain = Chain([bad, bad])
    _, checks = invoke_with_verification(chain, 'Question?', assemble_context([doc]), build_verification_index([doc]))
    assert len(chain.requests) == 2 and checks[0]['status'] == 'quote not found'


def test_translation_cli_displays_unchaptered_sources(monkeypatch, capsys):
    import runpy

    import langchain.chat_models
    from langchain_core.runnables import RunnableLambda

    import retrieval
    from philosophy_query import ModernizedWork

    class Model:
        def with_structured_output(self, schema):
            assert schema.__name__ == 'ModernizedWork'
            return RunnableLambda(lambda _: ModernizedWork(TranslatedPassage='A clear translation.'))
    monkeypatch.setattr(langchain.chat_models, 'init_chat_model', lambda *a, **kw: Model())
    monkeypatch.setattr(retrieval, 'retrieve', lambda question: [example()])
    monkeypatch.setattr(sys, 'argv', ['philosophy_query.py', '--question', 'A question'])
    runpy.run_path(str(ROOT / 'philosophy_query.py'), run_name='__main__')
    output = capsys.readouterr().out
    assert 'Native heading, paragraph 1' in output
    assert 'A clear translation.' in output
