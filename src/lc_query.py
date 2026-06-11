"""Query the LangChain Siemens RAG index through LM Studio and Weaviate."""

import os
import subprocess
import sys

import weaviate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_weaviate import WeaviateVectorStore


INDEX_NAME = "LangChainSiemens"
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"


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


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python lc_query.py "<your question>"')
        sys.exit(0)

    query = sys.argv[1]

    print(f"Using LM Studio base URL: {BASE_URL}", flush=True)

    llm = ChatOpenAI(
        base_url=BASE_URL,
        api_key="lm-studio",
        model="local-model",
        max_tokens=512,
        timeout=180,
        max_retries=0,
    )

    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL_NAME)

    client = weaviate.connect_to_local(port=8080, grpc_port=50051)

    try:
        vector_store = WeaviateVectorStore(
            client=client,
            index_name=INDEX_NAME,
            embedding=embeddings,
            text_key="text",
        )
        retriever = vector_store.as_retriever(search_kwargs={"k": 2})

        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "You are a PLC expert. "
                "Answer the question based only on the provided context:\n\n{context}"
            )),
            ("human", "{question}"),
        ])

        def format_docs(docs: list) -> str:
            return "\n\n".join(doc.page_content for doc in docs)

        rag_chain = (
            {"context": retriever | format_docs, "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser()
        )

        print(f"\nQuery:\n{query}", flush=True)
        answer = rag_chain.invoke(query)

        print("\nAnswer:", flush=True)
        print(answer, flush=True)

        # source_docs = retriever.invoke(query)
        # print("\nSource documents:", flush=True)
        # for idx, doc in enumerate(source_docs, start=1):
        #     print(f"\n--- Source {idx} ---", flush=True)
        #     print(doc.page_content, flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
