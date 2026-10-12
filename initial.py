import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_community.document_loaders import UnstructuredEPubLoader
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

load_dotenv()

loader = UnstructuredEPubLoader("pg7370.epub")
documents = loader.load()
print(f"Loaded {len(documents)} documents")
print(documents[0].page_content[:1000])
print(documents[0].metadata)


# embeddings = OpenAIEmbeddings(
#         model="text-embedding-3-small", show_progress_bar=False, chunk_size=50, retry_min_seconds=10
# )

# vectorstore = PineconeVectorStore(index_name="agora", embedding=embeddings)

