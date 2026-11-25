"""Versioned embedding input; citation text always stays verbatim."""

def embedding_text(document):
    return document.page_content
