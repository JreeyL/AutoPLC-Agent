"""Ingest the Siemens manual into a local Weaviate vector store."""

from pathlib import Path

import weaviate
from llama_index.core import Settings, SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.weaviate import WeaviateVectorStore


DOCUMENT_PATH = Path("data/siemens_manual.txt")
INDEX_NAME = "SiemensManual"
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"


def main() -> None:
    if not DOCUMENT_PATH.exists():
        raise FileNotFoundError(f"Document not found: {DOCUMENT_PATH}")

    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    Settings.llm = None

    client = weaviate.connect_to_local(port=8080, grpc_port=50051)

    try:
        documents = SimpleDirectoryReader(input_files=[str(DOCUMENT_PATH)]).load_data()
        nodes = SentenceSplitter().get_nodes_from_documents(documents)

        vector_store = WeaviateVectorStore(
            weaviate_client=client,
            index_name=INDEX_NAME,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        VectorStoreIndex(
            nodes,
            storage_context=storage_context,
        )

        print(f"Successfully inserted {len(nodes)} nodes into Weaviate index '{INDEX_NAME}'.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
