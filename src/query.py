"""Query the Siemens manual RAG index through LM Studio and Weaviate."""

import os
import subprocess
import sys

import weaviate
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.base.llms.types import LLMMetadata, MessageRole
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.vector_stores.weaviate import WeaviateVectorStore
from openai import OpenAI as OpenAIClient


INDEX_NAME = "SiemensManual"
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
CONTEXT_WINDOW = 4096


class LocalOpenAI(LlamaOpenAI):
    """OpenAI-compatible local LLM with explicit metadata for non-OpenAI models."""

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=CONTEXT_WINDOW,
            num_output=self.max_tokens or -1,
            is_chat_model=True,
            is_function_calling_model=False,
            model_name=self.model,
            system_role=MessageRole.SYSTEM,
        )


def get_wsl_host_ip() -> str:
    """Return the WSL default gateway IP, or localhost as a fallback."""
    try:
        result = subprocess.run(
            ["sh", "-c", "ip route show default | awk '{print $3}'"],
            check=True,
            capture_output=True,
            text=True,
        )
        host_ip = result.stdout.strip()
        if host_ip:
            return host_ip
    except (OSError, subprocess.SubprocessError):
        return "localhost"

    return "localhost"


BASE_URL = os.getenv("LM_STUDIO_BASE_URL", f"http://{get_wsl_host_ip()}:1234/v1")


def get_lm_studio_model(base_url: str) -> str:
    """Return the first loaded LM Studio model, or a configured fallback."""
    fallback_model = os.getenv("LM_STUDIO_MODEL", "local-model")

    try:
        client = OpenAIClient(base_url=base_url, api_key="lm-studio")
        models = client.models.list()
        if models.data:
            return models.data[0].id
    except Exception as exc:  # noqa: BLE001 - keep local connectivity fallback user-friendly.
        print(f"Could not discover LM Studio model automatically: {exc}")

    return fallback_model


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python query.py "<your question>"')
        return

    query = sys.argv[1]

    print(f"Using LM Studio base URL: {BASE_URL}", flush=True)

    model_name = get_lm_studio_model(BASE_URL)
    print(f"Using LM Studio model: {model_name}", flush=True)

    Settings.llm = LocalOpenAI(
        model=model_name,
        api_base=BASE_URL,
        api_key="lm-studio",
        context_window=CONTEXT_WINDOW,
        max_tokens=512,
        max_retries=0,
        timeout=180.0,
    )
    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)

    client = weaviate.connect_to_local(port=8080, grpc_port=50051)

    try:
        vector_store = WeaviateVectorStore(
            weaviate_client=client,
            index_name=INDEX_NAME,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            storage_context=storage_context,
        )
        query_engine = index.as_query_engine(similarity_top_k=2)

        print(f"\nQuery:\n{query}", flush=True)
        response = query_engine.query(query)

        print("\nResponse:", flush=True)
        print(response, flush=True)

        # print("\nSource nodes:", flush=True)
        # for idx, source_node in enumerate(response.source_nodes, start=1):
        #     print(f"\n--- Source Node {idx} ---", flush=True)
        #     print(f"Score: {source_node.score}", flush=True)
        #     print(source_node.node.get_content(), flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
