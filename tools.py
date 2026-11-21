from langchain_core.tools import tool
from ask import assemble_context, normalize
from retrieval import get_vectorstore, retrieve

@tool(parse_docstrings=True)
def search_passages(query: str, author: str | None = None, k: int = 5) -> str:
    """Search philosophical texts for passages related to a query.

    Args:
        query: What to look for, 
        author: restrict results to one author. Omit to search all authors
        k: number of passages to return (max 10)
    """

    filters = {"author":author} if author else None
    docs = retrival(query, num_chunks_to_retrieve=min(k,10), filters=filters)
    return assemble_context(docs) or "No passages found."

@tool(parse_docstring=True)
def verify_quote(passage_id:str, quote:str)->str:
    """Check that a quotation appears word-for-word in a specific passage.

    Use this before citing a quote. Quotes must be contiguous, with no ellipses.

    Args:
        passage_id: The passage_id from the passage's Source header.
        quote: The exact text you intend to cite.
    """
    found = get_vectorstore().get_by_ids([passage_id])
    if not found:
        return f"Unknown passage_id: {passage_id}"
    if normalize(quote) and normalize(quote) in normalize(found[0].page_content):
        return "ok"
    return "quote not found in that passage. Copy a shorter contiguous excerpt exactly."