"""Explicit staging smoke checks. Cached evidence is scoped to namespace, model and code."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CASES = [
    ('cross_author', 'Give one reason, from each author, why Locke and Mill limit political power. Use one passage per author.', None, 8),
    ('mill', 'What is the greatest happiness principle?', {'source_id':'pg11224'}, 4),
    ('burke', 'Why does Burke oppose treating political rights as abstract principles?', {'work_id':'pg15679:reflections'}, 4),
    ('locke', 'According to Locke, how does labour make property?', {'source_id':'pg7370'}, 4),
]


def smoke_identity(namespace, model, code_sha256):
    identity = {'namespace':namespace, 'model':model, 'ask_sha256':code_sha256, 'cases':CASES}
    return identity, hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]


def run(namespace, model, report_dir):
    from langchain.chat_models import init_chat_model

    from ask import (
        ResearchedResponse,
        assemble_context,
        build_verification_index,
        invoke_with_verification,
        normalize,
        prompt,
    )
    from ingest import save_json
    from retrieval import get_vectorstore

    identity, ident = smoke_identity(namespace, model, hashlib.sha256((ROOT/'ask.py').read_bytes()).hexdigest())
    path = report_dir / f'smoke-{ident}.json'
    # JSON round trip makes tuple/list forms comparable after reading cached evidence.
    identity = json.loads(json.dumps(identity))
    report = json.loads(path.read_text()) if path.exists() else {'identity':identity, 'qa':[]}
    if report.get('identity') != identity:
        raise ValueError(f'Refusing to reuse mismatched evidence: {path}')
    store = get_vectorstore(namespace)
    chain = prompt | init_chat_model(model).with_structured_output(ResearchedResponse,method='json_schema')
    for name, question, filters, k in CASES:
        previous = next((r for r in report['qa'] if r['case']==name),None)
        if previous and previous['passed']:
            print('Previously verified:',name)
            continue
        docs=store.similarity_search(question,k=k,filter=filters)
        response,checks=invoke_with_verification(chain,question,assemble_context(docs),build_verification_index(docs))
        passed=bool(response.Answer.strip() and response.Citations and all(r['status']=='ok' for r in checks))
        if name=='cross_author':
            passed=passed and {'John Locke','John Stuart Mill'} <= {c.author for c in response.Citations}
        row={'case':name,'passed':passed,'question':question,'response':response.model_dump(),'checks':checks,
             'inline_locators':[normalize(c.locator) in normalize(response.Answer) for c in response.Citations],
             'retrieved_ids':[d.metadata['passage_id'] for d in docs]}
        report['qa']=[r for r in report['qa'] if r['case']!=name]+[row]
        report['passed']=False
        save_json(path,report)
        if not passed:
            raise ValueError(f'Smoke check failed: {name}; see {path}')
    report['passed']=True
    save_json(path,report)
    print(f'Four Q&A cases passed for {namespace} / {model}; evidence: {path}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True)
    parser.add_argument('--model',help='defaults to ask.ANSWER_MODEL')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports')
    args=parser.parse_args()
    from ask import ANSWER_MODEL
    run(args.namespace,args.model or ANSWER_MODEL,args.report_dir)


if __name__=='__main__':
    main()
