"""Local validation evidence; this script never activates or deletes a namespace."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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

namespace = 'epub-v1-04b8672ea20df6c7'
report_path = ROOT / 'reports' / f'{namespace}-live-smoke.json'
version = hashlib.sha256((ROOT / 'ask.py').read_bytes()).hexdigest()
report = json.loads(report_path.read_text()) if report_path.exists() else {}
if report.get('ask_sha256') != version:
    report = {'namespace': namespace, 'ask_sha256': version, 'qa_model': 'groq:openai/gpt-oss-120b',
              'temperature': 0, 'verification_retry_limit': 1, 'translation_model': 'gpt-4.1-mini', 'qa': []}
store = get_vectorstore(namespace)
qa = prompt | init_chat_model('groq:openai/gpt-oss-120b', temperature=0, max_retries=5).with_structured_output(ResearchedResponse, method='json_schema')
cases = [
    ('cross_author', 'Give one reason, from each author, why Locke and Mill limit political power. Use one passage per author.', None, 8),
    ('mill', 'What does the greatest happiness principle say about right actions?', {'source_id': 'pg11224'}, 4),
    ('burke', 'In Reflections on the Revolution in France, why does Burke oppose treating political rights as abstract principles?', {'work_id': 'pg15679:reflections'}, 4),
    ('locke', "According to Locke, how does labour make something a person's property?", {'source_id': 'pg7370'}, 4),
]
for name, question, filters, k in cases:
    docs = store.similarity_search(question, k=k, filter=filters)
    previous = next((r for r in report['qa'] if r['case'] == name), None)
    if previous and previous['statuses'] and all(s == 'ok' for s in previous['statuses']):
        print('Already passed:', name, flush=True)
        continue
    response, checks = invoke_with_verification(qa, question, assemble_context(docs), build_verification_index(docs))
    record = {'case': name, 'question': question, 'response': response.model_dump(),
              'statuses': [r['status'] for r in checks],
              'exact_inline_locators': [normalize(c.locator) in normalize(response.Answer) for c in response.Citations],
              'retrieved_passage_ids': [d.metadata['passage_id'] for d in docs]}
    report['qa'] = [r for r in report['qa'] if r['case'] != name] + [record]
    save_json(report_path, report)
    print('\nCASE', name, 'STATUSES', record['statuses'], 'INLINE LOCATORS', record['exact_inline_locators'], flush=True)
    print(response.Answer, flush=True)
    for c in response.Citations:
        print('QUOTE', c.quote, flush=True)
    assert response.Answer.strip() and response.Citations
    assert all(r['status'] == 'ok' for r in checks), record['statuses']
    if name == 'cross_author':
        assert {'John Locke', 'John Stuart Mill'} <= {c.author for c in response.Citations}
report['passed'] = True
save_json(report_path, report)
print('\nAll four Q&A cases passed; edition checks run separately.', flush=True)
