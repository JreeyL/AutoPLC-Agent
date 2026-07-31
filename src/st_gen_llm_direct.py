"""LLM-direct Structured Text draft generator for PLC_AST files (E2S4).

This approach asks the selected LLM backend to directly produce IEC 61131-3
Structured Text from a validated PLC_AST JSON input. Python owns orchestration,
prompting, light structural validation, and file writing only; it does not
assemble ST blocks deterministically.

Usage::

    python -m src.st_gen_llm_direct data/ast/signal_light_demo_api_AST_C.json --backend api
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

try:
    from src.ast_schemas import PLC_AST
    from src.req_parser import build_llm
except ImportError:
    from ast_schemas import PLC_AST
    from req_parser import build_llm


APPROACH_NAME = "llm_direct"
DEFAULT_OUTPUT_DIR = Path("data/plc/st")
REQUIRED_ST_TOKENS = ("PROGRAM", "VAR", "END_VAR", "END_PROGRAM")


SYSTEM_PROMPT = """\
You are an expert PLC software engineer generating IEC 61131-3 Structured Text
draft code for engineer review.

Return plain Structured Text only. Do not wrap the response in Markdown fences.
Do not add explanatory prose outside the ST program.
"""


USER_PROMPT = """\
Generate one IEC 61131-3 Structured Text draft from this validated PLC_AST.
Return plain ST only, no Markdown.

Must include: MVP/review header comment; Source AST comment; PROGRAM, VAR,
END_VAR, END_PROGRAM; BOOL device declarations; source-equipment comments for
variables; sequence trace comments (node_id, source step, source scenario,
action); interlock trace comments (node_id, condition, scenario, forced action,
priority); sequence logic before safety overrides; a safety/interlock section.

Variable names: non-alnum -> _, collapse _, strip _, prefix digit names with V_.
Unsupported sequence state, timers/delays, analogue thresholds, runtime/vendor
logic, and full green/red colour modelling must stay TODO/review comments. Do
not pretend unsupported logic is fully implemented.

Source AST: {source_ast_file}
PLC_AST JSON: {ast_json}
"""


def load_ast(path: Path) -> PLC_AST:
    """Load and validate a PLC_AST JSON file."""
    if not path.is_file():
        raise FileNotFoundError(f"AST file not found: {path}")
    try:
        return PLC_AST.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValueError(f"Invalid PLC_AST JSON: {path}\n{exc}") from exc


def resolve_output_path(ast_path: Path, backend: str) -> Path:
    """Resolve backend-specific LLM-direct ST output path."""
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_OUTPUT_DIR / f"{ast_path.stem}_st_{APPROACH_NAME}_{backend}.st"


def _message_content_to_text(content: Any) -> str:
    """Convert common LangChain message content shapes to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def clean_llm_output(text: str) -> str:
    """Strip accidental Markdown fences while preserving plain ST text."""
    cleaned = text.strip()
    fence_match = re.fullmatch(r"```[A-Za-z0-9_-]*\s*(.*?)\s*```", cleaned, re.S)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    cleaned = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", cleaned).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned + "\n"


def validate_st_structure(st_text: str) -> None:
    """Perform light structural validation before saving model output."""
    upper = st_text.upper()
    missing = [token for token in REQUIRED_ST_TOKENS if token not in upper]
    if missing:
        raise ValueError(
            "LLM output is missing required ST structure token(s): "
            f"{', '.join(missing)}"
        )
    if upper.find("PROGRAM") > upper.find("END_PROGRAM"):
        raise ValueError("LLM output has END_PROGRAM before PROGRAM.")
    if upper.find("VAR") > upper.find("END_VAR"):
        raise ValueError("LLM output has END_VAR before VAR.")
    executable_text = re.sub(r"\(\*.*?\*\)", "", st_text, flags=re.S)
    executable_text = re.sub(r"/\*.*?\*/", "", executable_text, flags=re.S)
    executable_text = re.sub(r"//.*", "", executable_text)
    executable_upper = executable_text.upper()
    unterminated_ifs = len(re.findall(r"^\s*IF\b", executable_upper, re.M)) - len(
        re.findall(r"^\s*END_IF\b\s*;?", executable_upper, re.M)
    )
    if unterminated_ifs > 0:
        raise ValueError(
            "LLM output appears to contain IF block(s) without matching END_IF."
        )
    if "```" in st_text:
        raise ValueError("LLM output still contains Markdown code fences after cleanup.")


def generate_st(ast: PLC_AST, source_ast_file: Path, backend: str) -> str:
    """Ask the selected LLM backend to directly generate ST text."""
    if backend == "api" and not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "The api backend requires GEMINI_API_KEY to be set. "
            "No output was generated."
        )

    llm = build_llm(backend).bind(max_tokens=1800)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", USER_PROMPT),
        ]
    )
    chain = prompt | llm
    try:
        message = chain.invoke(
            {
                "source_ast_file": str(source_ast_file.resolve()),
                "ast_json": ast.model_dump_json(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"LLM direct ST generation failed for {backend}: {exc}") from exc

    st_text = clean_llm_output(_message_content_to_text(getattr(message, "content", message)))
    validate_st_structure(st_text)
    return st_text


def write_st_file(ast_path: Path, backend: str) -> Path:
    ast = load_ast(ast_path)
    st_text = generate_st(ast, ast_path, backend)
    output_path = resolve_output_path(ast_path, backend)
    output_path.write_text(st_text, encoding="utf-8")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate LLM-direct Structured Text draft from PLC_AST JSON."
    )
    parser.add_argument("ast_file", type=Path, help="Path to a validated PLC_AST JSON file.")
    parser.add_argument(
        "--backend",
        choices=["local", "api"],
        default="local",
        help="Inference backend: local LM Studio or api Gemini-compatible backend.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output_path = write_st_file(args.ast_file, args.backend)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.backend == "api":
            print(
                "Check GEMINI_API_KEY and connectivity to the Gemini "
                "OpenAI-compatible endpoint.",
                file=sys.stderr,
            )
        else:
            print(
                "Check that LM Studio is running and listening on the configured "
                "local server URL.",
                file=sys.stderr,
            )
        return 1

    print(f"Generated LLM-direct ST draft ({args.backend}): {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
