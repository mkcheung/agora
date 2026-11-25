"""Advisory only: compare indexed authors with the query graph's Author Literal."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def declared_authors(path=ROOT / 'philosophy_query.py'):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'Author' for t in node.targets):
            return {n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return set()


def main():
    from ingest import prepare_records
    chunks, _, report = prepare_records()
    authors = {d.metadata['author'] for d in chunks}
    missing = sorted(authors - declared_authors())
    print(report['corpus_version'])
    print('Authors absent from Author:', ', '.join(missing) or 'none')
    print('Advisory: missing authors use the unfiltered/other-thinkers route.')


if __name__ == '__main__':
    main()
