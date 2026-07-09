"""Generate a PLC AST from parsed requirement JSON + Gherkin .feature (E2S3, Approach A).

This is the baseline **Approach A** for the AST-generation stage: a single
LLM-direct call that folds both upstream Epic-2 artifacts into one
:class:`~src.ast_schemas.PLC_AST`. It consumes the *outputs* of E2S1 and E2S2:

* ``requirement_file`` -- a ``data/parsed/<stem>_parsed_<backend>.json`` file
  produced by :mod:`src.req_parser` (validated into a
  :class:`~src.schemas.SystemRequirement`).
* ``gherkin_file`` -- a ``data/gherkin/<stem>_<backend>.feature`` file produced
  by :mod:`src.gherkin_gen` (read as raw text, passed to the prompt as-is).

Unlike E2S2's per-item fan-out, Approach A issues **one single structured call**
for the whole input -- that batch-in-one-shot behaviour is Approach A's
defining characteristic and the baseline other E2S3 approaches are compared
against. The result is written to ``data/ast/<stem>_<backend>.json``.

The two ``PLC_AST.source_*_file`` provenance fields are stamped by this script
*after* the call (never trusted from the model), mirroring how
:mod:`src.gherkin_gen` stamps ``source_step_id`` in E2S2.

Usage::

    python -m src.ast_gen_A \\
        data/parsed/signal_light_demo_parsed_api.json \\
        data/gherkin/signal_light_demo_api.feature \\
        --backend api
"""

import argparse
import sys
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

try:
    # When run as a module (python -m src.ast_gen_A).
    from src.ast_schemas import PLC_AST
    from src.req_parser import build_llm
    from src.schemas import SystemRequirement
except ImportError:
    # When run directly from inside the src/ directory.
    from ast_schemas import PLC_AST
    from req_parser import build_llm
    from schemas import SystemRequirement


SYSTEM_PROMPT = (
    "You are an expert PLC automation engineer and AST designer. Your task is "
    "to fold a structured PLC control requirement and its BDD Gherkin feature "
    "into a single, code-ready Abstract Syntax Tree (AST) intermediate "
    "representation."
)

INSTRUCTION = (
    "Read the SystemRequirement JSON and the Gherkin .feature text provided "
    "below and produce a single PLC_AST object. Follow these rules exactly:\n"
    "- Devices: for each Equipment in equipment_list, create one DeviceNode. "
    "Copy 'name' and 'type' verbatim into name/device_type and set "
    "source_equipment to the same name. node_id MUST follow the pattern "
    "'DEV-<name>' (e.g. 'DEV-EV-101').\n"
    "- Sequence: for each ControlSequence step, create one SequenceStepNode. "
    "Copy the step's description VERBATIM into 'action' -- do NOT paraphrase, "
    "summarise, or extract verb phrases. node_id MUST follow 'SEQ-<step_id>' "
    "(e.g. 'SEQ-1'). Set step_id and source_step_id to the source step_id. "
    "For target_device: identify any equipment name from the equipment_list "
    "that appears in the step description; set None if none is identifiable. "
    "For condition: give the triggering condition if the step states one, else "
    "None. For source_scenario: find the GherkinScenario in the .feature text "
    "whose source step corresponds to this step's step_id and copy its name; "
    "set None if not found.\n"
    "- Interlocks: for each Interlock, create one InterlockNode. Copy "
    "'condition' and 'action' VERBATIM into condition/forced_action and set "
    "source_interlock_condition to the same condition text. node_id MUST "
    "follow 'ILK-<N>' with N a 1-based counter (e.g. 'ILK-1'). Leave priority "
    "as 1. For affected_devices: list ONLY equipment names from the "
    "equipment_list that appear in the condition or action text -- NEVER invent "
    "names; use an empty list if none appear. For source_scenario: find the "
    "GherkinScenario whose interlock corresponds to this interlock's condition "
    "and copy its name; set None if not found.\n"
    "- feature_title: copy it from the Gherkin feature's 'Feature:' line.\n"
    "- Do NOT invent any device, step, or interlock not present in the source "
    "inputs, and do NOT paraphrase any verbatim field. This is the same "
    "no-hallucination principle used in the E2S1 and E2S2 stages.\n"
    "- Leave source_requirement_file and source_gherkin_file as empty strings; "
    "they are stamped by the pipeline after generation."
)


def load_requirement(input_path: Path) -> SystemRequirement:
    """Read and validate a parsed SystemRequirement JSON file.

    A missing file, empty file, or JSON that fails SystemRequirement
    validation is a fatal error (``sys.exit(1)``), matching req_parser.py's
    error-handling style.
    """
    if not input_path.is_file():
        print(f"❌ Requirement file not found: {input_path}")
        sys.exit(1)

    raw = input_path.read_text(encoding="utf-8").strip()
    if not raw:
        print(f"❌ Requirement file is empty: {input_path}")
        sys.exit(1)

    try:
        return SystemRequirement.model_validate_json(raw)
    except ValidationError as exc:
        print(
            f"❌ Requirement file is not a valid SystemRequirement JSON: "
            f"{input_path}\n{exc}"
        )
        sys.exit(1)


def load_gherkin(gherkin_path: Path) -> str:
    """Read a Gherkin .feature file as raw text.

    A missing or empty file is a fatal error (``sys.exit(1)``). The text is
    passed to the prompt as-is -- no Gherkin parsing is performed.
    """
    if not gherkin_path.is_file():
        print(f"❌ Gherkin file not found: {gherkin_path}")
        sys.exit(1)

    text = gherkin_path.read_text(encoding="utf-8").strip()
    if not text:
        print(f"❌ Gherkin file is empty: {gherkin_path}")
        sys.exit(1)

    return text


def resolve_output_path(requirement_path: Path, backend: str) -> Path:
    """Map the parsed-requirement input to its AST-JSON destination.

    The ``<stem>`` is recovered from the requirement filename by stripping its
    ``_parsed_<backend>`` suffix (same logic as gherkin_gen.py); the output
    suffix reflects the ``--backend`` used for this run so local/api runs
    coexist and can be diffed::

        signal_light_demo_parsed_api.json --backend api
            -> data/ast/signal_light_demo_api.json

    The ``data/ast/`` directory (a sibling of ``data/parsed/``) is created if
    it does not yet exist. A filename that does not follow the
    ``_parsed_<backend>`` convention is a fatal error.
    """
    name = requirement_path.stem  # filename without the .json extension
    if "_parsed_" not in name:
        print(
            "❌ Requirement filename does not match the expected "
            f"'<stem>_parsed_<backend>.json' convention: {requirement_path.name}"
        )
        sys.exit(1)

    stem, _input_backend = name.rsplit("_parsed_", 1)
    output_dir = requirement_path.resolve().parent.parent / "ast"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{stem}_{backend}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a PLC AST (E2S3 Approach A) from a parsed "
            "SystemRequirement JSON and a Gherkin .feature file via a single "
            "LLM-direct call."
        )
    )
    parser.add_argument(
        "requirement_file",
        type=Path,
        help="Path to the parsed requirement JSON file "
        "(e.g. data/parsed/signal_light_demo_parsed_api.json).",
    )
    parser.add_argument(
        "gherkin_file",
        type=Path,
        help="Path to the Gherkin .feature file "
        "(e.g. data/gherkin/signal_light_demo_api.feature).",
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
    requirement_path: Path = args.requirement_file
    gherkin_path: Path = args.gherkin_file

    # Component 1: File reading and validation.
    requirement = load_requirement(requirement_path)
    gherkin_text = load_gherkin(gherkin_path)
    output_path = resolve_output_path(requirement_path, args.backend)

    # Component 2 & 3: reuse req_parser.py's backend construction, then bind
    # PLC_AST for one single structured call over the whole input -- Approach
    # A's defining characteristic.
    llm = build_llm(args.backend)
    structured_llm = llm.with_structured_output(PLC_AST)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", f"{SYSTEM_PROMPT}\n\n{INSTRUCTION}"),
            (
                "human",
                "SystemRequirement JSON:\n{requirement}\n\n"
                "Gherkin .feature text:\n{gherkin}",
            ),
        ]
    )
    chain = prompt | structured_llm

    print("Generating AST... (this may take a moment)", flush=True)
    try:
        result: PLC_AST = chain.invoke(
            {
                "requirement": requirement.model_dump_json(),
                "gherkin": gherkin_text,
            }
        )
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure clearly.
        print(f"❌ AST generation failed: {exc}")
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

    # Component 4: stamp provenance deterministically rather than trusting the
    # model, then write the output.
    result.source_requirement_file = str(requirement_path.resolve())
    result.source_gherkin_file = str(gherkin_path.resolve())

    output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    print(
        f"✅ AST generated: {len(result.devices)} devices, "
        f"{len(result.sequence)} sequence steps, "
        f"{len(result.interlocks)} interlocks. "
        f"Saved to {output_path}."
    )


if __name__ == "__main__":
    main()
