from collections import defaultdict
from functools import cache
from ingest import ROOT, WORKS 
from parsers import parse_epub

@cache
def prep_cache_for_translation():
    corpus = defaultdict(list)
    for source in WORKS:
        paragraphs = parse_epub(ROOT / source["file"], source["profile"])

        for paragraph in paragraphs:
            corpus[paragraph.metadata['work']].append(paragraph)
    
    return dict(corpus)

def load_work(title:str):
    corpus = prep_cache_for_translation()
    try:
        return list(corpus[title])
    except LookupError:
        raise LookupError(f"{title!r} is not a part of this corpus. Choose one of {sorted(corpus)}") from None