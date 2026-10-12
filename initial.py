import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_community.document_loaders import UnstructuredEPubLoader
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

loader = UnstructuredEPubLoader("pg7370.epub")
documents = loader.load()
# Sample the load
# print(f"Loaded {len(documents)} documents")
# print(documents[0].page_content[:1000])
# print(documents[0].metadata)

splitter = RecursiveCharacterTextSplitter(
    chunk_size=2000,
    chunk_overlap=200
)

chunks = splitter.split_documents(documents)
# Sample the chunks
# print(f"Created {len(chunks)} chunks")
# print(chunks[0].page_content)
# print(chunks[0].metadata)


# embeddings = OpenAIEmbeddings(
#         model="text-embedding-3-small", show_progress_bar=False, chunk_size=50, retry_min_seconds=10
# )

# vectorstore = PineconeVectorStore(index_name="agora", embedding=embeddings)

