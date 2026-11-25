"""Edition isolation, resumability, exact block alignment and paid-call safety."""
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

import edition as E


def doc(ident='pg1:main:a', text='An original philosophical paragraph.', kind='prose', chapter=1):
    return Document(page_content=text, metadata={'block_id':ident,'work_id':'pg1:main', 'author':'Author', 'content_type':kind, 'chapter':chapter, 'locator':'Chapter 1, paragraph 1'})


def output(schema, **values):
    return {'parsed':schema(**values),'raw':SimpleNamespace(usage_metadata={'input_tokens':10,'output_tokens':10})}


def test_budget_cumulative_reservation_retry_and_auth(tmp_path):
    calls = []
    def invoke(*args):
        calls.append(args)
        return output(E.Judgement, faithful=True, findings=[])
    c = E.PaidClient(tmp_path, 0.02, invoke=invoke)
    c.call(E.DEFAULT_JUDGE, 's','u', E.Judgement, 100)
    spent = c.spent()
    assert 0 < spent < 0.02
    resumed = E.PaidClient(tmp_path, spent + 0.00001, invoke=invoke)
    with pytest.raises(E.BudgetExceeded):
        resumed.call(E.DEFAULT_JUDGE,'s','u',E.Judgement,100)
    assert len(calls) == 1
    class HTTPError(Exception):
        status_code = 401
    def fail(*args):
        calls.append(args)
        raise HTTPError()
    auth = E.PaidClient(tmp_path, 1, invoke=fail)
    with pytest.raises(E.EditionError,match='without retry'):
        auth.call(E.DEFAULT_MODEL,'s','u',E.Judgement,100)
    assert len(calls) == 2
    assert auth.spent() > spent  # unknown charge remains reserved


def test_retry_is_bounded_and_each_attempt_reserves(tmp_path):
    class HTTPError(Exception):
        status_code = 429
    attempts = []
    def fail(*args):
        attempts.append(args)
        raise HTTPError()
    c = E.PaidClient(tmp_path, 1, invoke=fail, sleep=lambda _: None)
    with pytest.raises(HTTPError):
        c.call(E.DEFAULT_MODEL,'s','u',E.Judgement,100)
    assert len(attempts) == 3
    assert len(E.lines(c.ledger)) == 3


def test_duplicate_model_ids_rejected_and_resume_skips_complete(tmp_path):
    spec = E.definition()
    d = doc()
    class Client:
        duplicates = True
        calls = 0
        def spent(self): return 0
        def call(self, *args):
            self.calls += 1
            render = E.Rendering(block_id=d.metadata['block_id'], modern_text=d.page_content,notes='')
            return E.Renderings(blocks=[render,render] if self.duplicates else [render]), {}
    c = Client()
    with pytest.raises(E.EditionError,match='exactly once'):
        E.build([d],tmp_path,spec,c)
    assert E.records(tmp_path) == {}
    c.duplicates = False
    assert E.build([d],tmp_path,spec,c) == 1
    assert E.build([d],tmp_path,spec,c) == 0
    assert c.calls == 2


def test_tables_never_call_model_and_are_verbatim(tmp_path):
    class Client:
        def call(self,*args): pytest.fail('table sent to model')
        def spent(self): return 0
    d=doc(text=' col1   col2\n 1       2',kind='table')
    E.build([d],tmp_path,E.definition(),Client())
    assert E.records(tmp_path)[d.metadata['block_id']]['modern_text'] == d.page_content


def test_alignment_and_stale_retranslation():
    docs=[doc('pg1:main:valid'), doc('pg1:main:stale','changed'),doc('pg1:main:new','unique')]
    saved={'pg1:main:valid':{'source_sha256':E.sha(docs[0].page_content)},
           'pg1:main:stale':{'source_sha256':E.sha('old')},
           'pg1:main:moved':{'source_sha256':E.sha('unique')},
           'pg1:main:orphan':{'source_sha256':E.sha('missing')}}
    assert {k:v[0] for k,v in E.alignment(docs,saved).items()} == {'pg1:main:valid':'valid','pg1:main:stale':'stale','pg1:main:moved':'moved','pg1:main:orphan':'orphan'}


def test_packing_respects_chapters_and_keeps_long_blocks_whole():
    ds=[doc('pg1:main:a', 'a'*3000),doc('pg1:main:b','b'*3000),doc('pg1:main:c','c'*9000),doc('pg1:main:d',chapter=2),doc('pg1:main:e',kind='note')]
    packs=list(E.packs(ds))
    assert [len(p) for p in packs] == [2,1,1,1]
    assert packs[1][0].page_content == 'c'*9000


def test_checks_detect_lost_numbers_negations_labels_and_meta():
    flags=E.code_checks('Sect. 27. John Locke did not say "42".', 'Here is John Locke saying 41.')
    assert {'numbers','negations','section_labels','quotation_marks','meta_text'} <= set(flags)


def test_edition_id_changes_with_definition_and_drift_is_offline():
    spec=E.definition()
    assert not E.drift(spec)
    assert E.edition_id(dict(spec,prompt='other')) != E.edition_id(spec)
    assert E.edition_id(dict(spec,model='other')) != E.edition_id(spec)


def test_concurrent_budget_reservations_never_exceed_cap(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    def invoke(*args):
        return {'parsed':E.Judgement(faithful=True,findings=[]), 'raw':None}
    c=E.PaidClient(tmp_path,0.03,invoke=invoke)
    def call(_):
        try:
            c.call(E.DEFAULT_JUDGE,'s','u',E.Judgement,100)
            return True
        except E.BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes=list(pool.map(call,range(20)))
    assert 0 < sum(outcomes) < 20
    assert c.spent() <= 0.03
