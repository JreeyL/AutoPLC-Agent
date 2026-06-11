"""Ingest the Siemens manual into Weaviate using LangChain (comparison against LlamaIndex)."""

from pathlib import Path

import weaviate
from langchain_community.document_loaders import TextLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_weaviate import WeaviateVectorStore


DOCUMENT_PATH = Path("data/siemens_manual.txt")
INDEX_NAME = "LangChainSiemens"
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"


def main() -> None:
    if not DOCUMENT_PATH.exists():
        raise FileNotFoundError(f"Document not found: {DOCUMENT_PATH}")

    docs = TextLoader(str(DOCUMENT_PATH)).load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL_NAME)

    client = weaviate.connect_to_local(port=8080, grpc_port=50051)

    try:
        WeaviateVectorStore.from_documents(
            chunks,
            embeddings,
            client=client,
            index_name=INDEX_NAME,
        )
        print(f"Successfully inserted {len(chunks)} chunks into Weaviate index '{INDEX_NAME}'.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
