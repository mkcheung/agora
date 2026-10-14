from functools import cache
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, INDEX_NAME

@cache
def get_vectorstore() -> PineconeVectorStore:
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS)
    return PineconeVectorStore(index_name=INDEX_NAME, embedding=embeddings)

def retrieve(question:str, num_chunks_to_retrieve: int = 8, filters: dict | None = None) -> list[Document]:
    vectorstore = get_vectorstore()
    results = vectorstore.similarity_search(question, k=num_chunks_to_retrieve, filter=filters or None)
    return results