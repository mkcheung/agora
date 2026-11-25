"""Create a write-once golden record map at a deliberately chosen output path."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest import prepare_records, save_report


def record_hashes(chunks):
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()[:20]
    return {d.metadata['passage_id']: {
        'text': digest(d.page_content),
        'metadata': digest(json.dumps({k: v for k, v in d.metadata.items()
                                      if k not in ('corpus_version', 'embedded_text_sha256')}, sort_keys=True)),
    } for d in chunks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    chunks, _, report = prepare_records()
    save_report(args.output, record_hashes(chunks))
    print(report['corpus_version'], len(chunks), args.output)
