"""Parse natural-language PLC requirements into structured JSON (E2S1).

This is the main execution script for the requirement-ingestion pipeline. It
reads a free-form ``.txt`` control narrative, sends it to a local LM Studio
model through LangChain's structured-output binding, and writes the validated
:class:`SystemRequirement` to ``data/parsed/<name>_parsed_<backend>.json``.

Usage::

    python -m src.req_parser data/requirements/sample.txt
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

# Load variables from the project-root .env at startup. override=False means an
# already-exported shell environment variable takes priority over the .env value.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

try:
    # When run as a module (python -m src.req_parser).
    from src.schemas import SystemRequirement
except ImportError:
    # When run directly from inside the src/ directory.
    from schemas import SystemRequirement


SYSTEM_PROMPT = (
    "You are an expert Automation Systems Engineer. Your task is to analyze "
    "natural-language PLC control requirements and extract them into strict "
    "JSON formats."
)

INSTRUCTION = (
    "Extract all equipment, operational sequences, and safety interlocks "
    "accurately. Do NOT hallucinate or fabricate any devices, rules, or steps "
    "not explicitly mentioned in the text."
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

# Gemini exposes an OpenAI-compatible endpoint; the 2.5 series supports
# response_format json_schema natively, so structured output needs no override.
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
GEMINI_MODEL = "gemini-2.5-flash"


def build_llm(backend: str) -> ChatOpenAI:
    """Construct the ChatOpenAI client for the chosen backend.

    ``local`` -> LM Studio on the Windows host (default, fully offline).
    ``api``   -> Gemini cloud API via its OpenAI-compatible endpoint, intended
                 for demo scenarios where local inference is too slow. Requires
                 ``GEMINI_API_KEY``.
    """
    if backend == "api":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print(
                "❌ The api backend requires the GEMINI_API_KEY "
                "environment variable to be set."
            )
            sys.exit(1)
        print(f"Using Gemini API: {GEMINI_MODEL}", flush=True)
        return ChatOpenAI(
            base_url=GEMINI_BASE_URL,
            api_key=api_key,
            model=GEMINI_MODEL,
            temperature=0,  # Deterministic extraction is critical.
            timeout=60,
            max_retries=0,
        )

    # Default: local LM Studio server.
    print(f"Using LM Studio base URL: {BASE_URL}", flush=True)
    return ChatOpenAI(
        base_url=BASE_URL,
        api_key="lm-studio",
        model="local-model",
        temperature=0,  # Deterministic extraction is critical.
        timeout=600,
        max_retries=0,
    )


# Per-backend output filename suffix, so local and API extractions for the same
# input can coexist and be diffed instead of overwriting each other.
BACKEND_SUFFIX = {"local": "local", "api": "api"}


def resolve_output_path(input_path: Path, backend: str) -> Path:
    """Map an input requirement file to its parsed-JSON destination.

    The output is tagged by backend so cross-backend runs don't overwrite each
    other (rerunning the same backend intentionally overwrites its own file)::

        sample.txt --backend local -> data/parsed/sample_parsed_local.json
        sample.txt --backend api   -> data/parsed/sample_parsed_api.json

    The ``data/parsed/`` directory is created if it does not yet exist.
    """
    output_dir = input_path.resolve().parent.parent / "parsed"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = BACKEND_SUFFIX[backend]
    return output_dir / f"{input_path.stem}_parsed_{suffix}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse a natural-language PLC requirement .txt file into "
            "structured JSON."
        )
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Path to the input requirement .txt file "
        "(e.g. data/requirements/sample.txt).",
    )
    parser.add_argument(
        "--backend",
        choices=["local", "api"],
        default="local",
        help="Inference backend. 'local' (default) uses the LM Studio server "
        "on the Windows host; 'api' uses the Gemini cloud API (requires "
        "GEMINI_API_KEY) for demos where local inference is too slow.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path: Path = args.input_file

    # Component 1: File input.
    if not input_path.is_file():
        print(f"❌ Input file not found: {input_path}")
        sys.exit(1)

    requirement_text = input_path.read_text(encoding="utf-8").strip()
    if not requirement_text:
        print(f"❌ Input file is empty: {input_path}")
        sys.exit(1)

    output_path = resolve_output_path(input_path, args.backend)

    # Component 2: LLM initialization for the selected backend.
    llm = build_llm(args.backend)

    # Component 3: System prompting.
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", f"{SYSTEM_PROMPT}\n\n{INSTRUCTION}"),
            ("human", "{requirement}"),
        ]
    )

    # Component 4: Structured binding and execution.
    structured_llm = llm.with_structured_output(SystemRequirement)
    chain = prompt | structured_llm

    print("Parsing requirement... (this may take a moment)", flush=True)
    try:
        result: SystemRequirement = chain.invoke({"requirement": requirement_text})
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure clearly.
        print(f"❌ Parsing failed: {exc}")
        if args.backend == "api":
            print(
                "Check that GEMINI_API_KEY is valid and that "
                "generativelanguage.googleapis.com is reachable."
            )
        else:
            print(
                "Check that LM Studio is running and its local server is "
                "listening on port 1234."
            )
        sys.exit(1)

    # Output handling.
    json_output = result.model_dump_json(indent=2)
    output_path.write_text(json_output, encoding="utf-8")

    print(
        "✅ Parsing complete! Extracted: "
        f"{len(result.equipment_list)} Equipment items, "
        f"{len(result.interlocks)} Interlocks, and "
        f"{len(result.sequences)} Sequence steps. "
        f"Saved to {output_path}."
    )


if __name__ == "__main__":
    main()
