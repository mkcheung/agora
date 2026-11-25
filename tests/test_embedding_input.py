"""G3 context reaches embedding input, never stored citation text."""
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

import ingest
from embedding_input import embedding_hash, embedding_text


def test_prefix_is_only_for_long_chunks():
    d=Document(page_content='x'*200,metadata={'author':'A','work':'W','division':'D','book':'Book I','part':'Part II','chapter_title':'C','heading':'H','section_title':'S'})
    assert embedding_text(d)=='A | W | D/Book I/Part II | C | H | S\n\n'+'x'*200
    assert d.page_content=='x'*200
    d.page_content='x'*199
    assert embedding_text(d)==d.page_content


def test_upload_embeds_prefix_but_stores_original(monkeypatch,tmp_path,require_epubs):
    import langchain_openai
    chunks,_ids,report=ingest.prepare_records(['pg11224-images-3.epub'])
    d=next(d for d in chunks if len(d.page_content)>=200)
    captured={}
    class Embeddings:
        def __init__(self,**kwargs): pass
        def embed_documents(self,texts):
            captured['embedded']=texts
            return [[0.]*1024 for _ in texts]
    class Index:
        def upsert(self,vectors,namespace):
            captured['vectors']=vectors
            return SimpleNamespace(upserted_count=len(vectors))
    monkeypatch.setattr(ingest,'remote_index',lambda:Index())
    monkeypatch.setattr(langchain_openai,'OpenAIEmbeddings',Embeddings)
    ingest.upload_records([d],[d.metadata['passage_id']],report,report['corpus_version'],progress_path=tmp_path/'progress.json')
    assert captured['embedded']==[embedding_text(d)]
    assert captured['vectors'][0]['metadata']['text']==d.page_content
    assert captured['vectors'][0]['metadata']['embedded_text_sha256']==embedding_hash(d)
    assert captured['embedded'][0]!=captured['vectors'][0]['metadata']['text']


def test_changed_embedding_hash_is_rejected(require_epubs):
    chunks,ids,_=ingest.prepare_records(['pg11224-images-3.epub'])
    d=chunks[0].model_copy(deep=True)
    d.metadata['embedded_text_sha256']='wrong'
    with pytest.raises(ValueError,match='Embedded text hash mismatch'):
        ingest.validate_records([d],ids[:1])
