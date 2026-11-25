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


def test_note_context_is_its_owner_and_resume_keeps_gaps_separate(tmp_path):
    import json
    a=doc('pg1:main:a','Original owner paragraph.')
    b=doc('pg1:main:b','Another paragraph.')
    n=doc('pg1:main:n','A short note.',kind='note')
    n.metadata['reference_block_id']=a.metadata['block_id']
    calls=[]
    class Client:
        def spent(self):return 0
        def call(self,model,system,user,schema,max_tokens):
            payload=json.loads(user);calls.append(payload)
            return E.Renderings(blocks=[E.Rendering(block_id=p['block_id'],modern_text=p['text'],notes='') for p in payload]),{}
    E.build([a,b,n],tmp_path,E.definition(),Client())
    note_input=next(p for pack in calls for p in pack if p['block_id']==n.metadata['block_id'])
    assert note_input['context']==a.page_content
    assert 'text' not in E.records(tmp_path)[a.metadata['block_id']]
    # A finished middle record must separate two unfinished paragraphs on resume.
    folder=tmp_path/'resumed'
    E.append(E.work_path(folder,'pg1:main'),E.records(tmp_path)[b.metadata['block_id']])
    c=doc('pg1:main:c','Third paragraph.')
    calls.clear()
    E.build([a,b,c],folder,E.definition(),Client())
    assert sorted([p['block_id'] for p in pack] for pack in calls)==[['pg1:main:a'],['pg1:main:c']]


def test_judge_evidence_is_checked_before_acceptance(tmp_path):
    d=doc()
    spec=E.definition()
    E.append(E.work_path(tmp_path,'pg1:main'),{'block_id':d.metadata['block_id'],'source_sha256':E.sha(d.page_content),'modern_text':d.page_content,'notes':'','checks':[],'judge':None,'status':'checked'})
    class Client:
        def call(self,*args):
            return E.Judgement(faithful=False,findings=[E.Finding(issue='negation',original_span='Invented source',modern_span='Invented modern',explanation='No matching evidence')]),{}
    E.judge([d],tmp_path,spec,Client())
    row=E.records(tmp_path)[d.metadata['block_id']]
    assert row['judge']['evidence_verified'] is False
    assert row['status']=='needs_review'


def test_auth_stop_is_rechecked_after_waiting_for_ledger(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    checked=threading.Event()
    class Stop:
        def __init__(self):self.event=threading.Event()
        def is_set(self):checked.set();return self.event.is_set()
        def set(self):self.event.set()
    invoked=[]
    c=E.PaidClient(tmp_path,1,invoke=lambda *a:invoked.append(a))
    c.stopped=Stop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with E.locked(c.ledger.with_suffix('.lock')):
            future=pool.submit(c.call,E.DEFAULT_MODEL,'s','u',E.Judgement,100)
            assert checked.wait(1)
            c.stopped.set()
        with pytest.raises(E.EditionError,match='stopped'):
            future.result(timeout=2)
    assert not invoked


def test_sentence_initial_names_are_checked_without_flagging_sentence_starters():
    assert 'names' in E.code_checks('Socrates argues about the nature of wisdom.','Someone argues about the nature of wisdom.')
    assert 'names' not in E.code_checks('People argue about the nature of wisdom.','Someone argues about the nature of wisdom.')
    d=doc(text='First verse line.\nSecond verse line.',kind='verse')
    assert 'verse_lines' in E.document_checks(d,'First verse line. Second verse line.')


def test_ascii_latin_real_record_is_mandatory_judge_candidate(require_epubs):
    from parsers import parse_epub
    docs=parse_epub(E.ROOT/'pg7370.epub')
    saved={d.metadata['block_id']:{'source_sha256':E.sha(d.page_content),'modern_text':d.page_content,'checks':[]} for d in docs}
    target='pg7370:main:a434bae8f81d7a8958d7'
    assert target in {d.metadata['block_id'] for d in E.judge_sample(docs,saved)}


def test_append_only_acceptance_and_targeted_retry_are_hash_bound(tmp_path):
    import json
    d=doc()
    class Client:
        calls=0
        def spent(self):return 0
        def call(self,model,system,user,schema,max_tokens):
            self.calls+=1
            payload=json.loads(user)
            return E.Renderings(blocks=[E.Rendering(block_id=p['block_id'],modern_text=p['text'],notes='') for p in payload]),{}
    c=Client();spec=E.definition()
    E.build([d],tmp_path,spec,c)
    E.accept_review([d],tmp_path,[d.metadata['block_id']],'Checked exact text.','Test reviewer')
    row=E.records(tmp_path)[d.metadata['block_id']]
    assert E.review_valid(row,d.page_content)
    assert not E.review_valid(dict(row,modern_text='Changed modern text'),d.page_content)
    assert not E.review_valid(row,'Changed source text')
    E.build([d],tmp_path,spec,c,retry_ids=[d.metadata['block_id']])
    new=E.records(tmp_path)[d.metadata['block_id']]
    assert c.calls==2 and new['review'] is None and new['judge'] is None
    assert len(E.lines(E.work_path(tmp_path,'pg1:main')))==3
    E.build([d],tmp_path,spec,c)
    assert c.calls==2


def test_failed_judge_can_be_explicitly_retried(tmp_path):
    d=doc();spec=E.definition()
    row={'block_id':d.metadata['block_id'],'source_sha256':E.sha(d.page_content),'modern_text':d.page_content,'notes':'','checks':[],'status':'needs_review'}
    row['judge']={'source_sha256':row['source_sha256'],'rendering_sha256':E.rendering_hash(row),'verdict':{'faithful':False,'findings':[]},'evidence_verified':False}
    E.append(E.work_path(tmp_path,'pg1:main'),row)
    class Client:
        calls=0
        def call(self,*args):self.calls+=1;return E.Judgement(faithful=True,findings=[]),{}
    c=Client()
    E.judge([d],tmp_path,spec,c)
    assert c.calls==0
    E.judge([d],tmp_path,spec,c,retry_ids=[d.metadata['block_id']])
    assert c.calls==1 and E.records(tmp_path)[d.metadata['block_id']]['status']=='judged'


def test_released_selection_cannot_mutate_or_reset_budget(tmp_path,monkeypatch):
    import json
    import sys
    spec=E.definition();ident=E.edition_id(spec)
    released=tmp_path/'editions/modern'/ident;released.mkdir(parents=True)
    metadata=released/'edition.json';metadata.write_text(json.dumps(spec))
    original=metadata.read_bytes()
    draft=tmp_path/'editions/drafts';E.append(draft/'spend.jsonl',{'usd':10.0})
    monkeypatch.setattr(E,'ROOT',tmp_path)
    monkeypatch.setattr(E,'definition',lambda:spec)
    monkeypatch.setattr(E,'drift',lambda _:False)
    monkeypatch.setattr(E,'corpus',lambda:([doc()],{}))
    monkeypatch.setattr(sys,'argv',['edition.py','build','--edition',ident])
    with pytest.raises(E.EditionError,match='immutable'):
        E.main()
    assert metadata.read_bytes()==original
    assert not (released.parent/'spend.jsonl').exists()


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,'bad',True])
def test_malformed_ledger_fails_closed(tmp_path,value):
    E.append(tmp_path/'spend.jsonl',{'usd':value})
    c=E.PaidClient(tmp_path,10,invoke=lambda *a:pytest.fail('network invoked'))
    with pytest.raises(E.EditionError):
        c.call(E.DEFAULT_MODEL,'s','u',E.Judgement,100)


@pytest.mark.parametrize('tokens',[float('nan'),-1,'10',True])
def test_malformed_usage_keeps_reservation_and_stops(tmp_path,tokens):
    def invoke(*args):
        return {'parsed':E.Judgement(faithful=True,findings=[]),'raw':SimpleNamespace(usage_metadata={'input_tokens':tokens,'output_tokens':10})}
    c=E.PaidClient(tmp_path,1,invoke=invoke)
    with pytest.raises(E.EditionError,match='Malformed usage'):
        c.call(E.DEFAULT_MODEL,'s','u',E.Judgement,100)
    assert c.spent()>0 and c.stopped.is_set()


def test_acceptance_cannot_replace_mandatory_independent_judge(tmp_path):
    d=doc()
    row={'block_id':d.metadata['block_id'],'source_sha256':E.sha(d.page_content),'modern_text':d.page_content,'notes':'','checks':[],'judge':None,'status':'checked'}
    E.append(E.work_path(tmp_path,'pg1:main'),row)
    E.accept_review([d],tmp_path,[d.metadata['block_id']],'Read against original.','Test reviewer')
    state=E.check_state([d],E.records(tmp_path))
    assert state['missing_judge']==1 and state['release_ready'] is False


def test_symlinked_draft_folder_cannot_mutate_released_edition(tmp_path,monkeypatch):
    released=tmp_path/'editions/modern/example';released.mkdir(parents=True)
    alias=tmp_path/'draft-alias';alias.symlink_to(released,target_is_directory=True)
    spec=E.definition()
    monkeypatch.setattr(E,'ROOT',tmp_path)
    with pytest.raises(E.EditionError,match='immutable'):
        E.build([doc()],alias,spec,object())
    assert not list(released.iterdir())


def test_explicit_rejudge_never_sends_tables_to_models(tmp_path):
    d=doc(kind='table')
    E.append(E.work_path(tmp_path,'pg1:main'),{'block_id':d.metadata['block_id'],'source_sha256':E.sha(d.page_content),'modern_text':d.page_content,'notes':'','checks':[],'judge':None,'status':'checked'})
    class Client:
        def call(self,*args):pytest.fail('table sent to judge')
    with pytest.raises(E.EditionError,match='Tables'):
        E.judge([d],tmp_path,E.definition(),Client(),retry_ids=[d.metadata['block_id']])


def test_new_judge_verdict_clears_previous_acceptance(tmp_path):
    d=doc();spec=E.definition()
    E.append(E.work_path(tmp_path,'pg1:main'),{'block_id':d.metadata['block_id'],'source_sha256':E.sha(d.page_content),'modern_text':d.page_content,'notes':'','checks':[],'judge':None,'status':'checked'})
    E.accept_review([d],tmp_path,[d.metadata['block_id']],'Prior decision.','Test reviewer')
    class Client:
        def call(self,*args):return E.Judgement(faithful=False,findings=[]),{}
    E.judge([d],tmp_path,spec,Client(),retry_ids=[d.metadata['block_id']])
    row=E.records(tmp_path)[d.metadata['block_id']]
    assert row['review'] is None and row['status']=='needs_review'


def test_unknown_sentence_initial_proper_name_is_conservatively_kept():
    original='Cicero maketh honorable mention of one of the Cassii, a severe judge amongst the Romans.'
    modern=original.replace('Cicero','Someone')
    assert 'names' in E.code_checks(original,modern)


def test_empty_explicit_retry_selection_is_a_paid_noop(tmp_path):
    class Client:
        def call(self,*args):pytest.fail('empty selection made a paid call')
        def spent(self):return 0
    d=doc();spec=E.definition()
    assert E.build([d],tmp_path,spec,Client(),retry_ids=[])==0
    assert E.judge([d],tmp_path,spec,Client(),retry_ids=[])==0
