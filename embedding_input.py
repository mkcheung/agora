"""Versioned embedding input; citation text always stays verbatim."""

import hashlib


def embedding_text(document):
    text = document.page_content
    if len(text) < 200:
        return text
    meta = document.metadata
    hierarchy = "/".join(str(meta[k]) for k in ("division", "book", "part") if meta.get(k))
    labels = [meta.get("author"), meta.get("work"), hierarchy,
              meta.get("chapter_title"), meta.get("heading"), meta.get("section_title")]
    return " | ".join(str(value) for value in labels if value) + "\n\n" + text


def embedding_hash(document):
    return hashlib.sha256(embedding_text(document).encode()).hexdigest()
