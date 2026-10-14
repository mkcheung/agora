from functools import cache

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, INDEX_NAME


@cache
def get_vectorstore() -> PineconeVectorStore:
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS)
    return PineconeVectorStore(index_name=INDEX_NAME, embedding=embeddings)