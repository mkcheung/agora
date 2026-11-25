"""Read-only fixed retrieval probes; older namespace first."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FILTERED = [
    ('Thomas Hobbes', 'Why authorize a sovereign?'),
    ('Thomas Hobbes', 'What is the state of nature?'),
    ('John Locke', 'How does labour make property?'),
    ('John Locke', 'Are ideas innate?'),
    ('Edmund Burke', 'Why reject abstract political rights?'),
    ('Edmund Burke', 'How do the debts of the Nabob affect the Carnatic?'),
    ('John Stuart Mill', 'When may society restrict individual liberty?'),
    ('John Stuart Mill', 'What is the greatest happiness principle?'),
]
UNFILTERED = ['How does knowledge come from experience?', 'What makes knowledge possible a priori?',
              'What determines whether an action is morally right?', 'Is morality grounded in duty or happiness?',
              'Why should women receive equal education?', 'Why oppose the subordination of women?',
              'How does labour create property?', 'What determines the value of labour?']


def main():
    from ingest import save_report
    from retrieval import get_vectorstore
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('older'); parser.add_argument('newer')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    stores = [get_vectorstore(args.older), get_vectorstore(args.newer)]
    result = []
    for author, question in FILTERED + [(None, q) for q in UNFILTERED]:
        ids = [[d.metadata['passage_id'] for d in store.similarity_search(question, k=8, filter={'author': author} if author else None)] for store in stores]
        result.append({'author': author, 'question': question, 'older': ids[0], 'newer': ids[1], 'same_set': set(ids[0]) == set(ids[1])})
    save_report(args.report, {'older':args.older, 'newer':args.newer, 'probes':result})
    print('Filtered unchanged:', sum(r['same_set'] for r in result if r['author']), '/', len(FILTERED))


if __name__ == '__main__':
    main()
