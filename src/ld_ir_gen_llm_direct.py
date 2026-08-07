"""LLM-direct Ladder Diagram IR generator for PLC_AST files (E2S4).

This approach asks the selected LLM backend to directly produce Ladder Diagram
intermediate-representation JSON from a validated PLC_AST input. Python owns
orchestration, prompting, JSON cleanup/parsing, schema validation, light
structural checks, and file writing only; it does not build LD networks
deterministically.

Usage::

    python -m src.ld_ir_gen_llm_direct data/ast/signal_light_demo_api_AST_C.json --backend api
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

try:
    from src.ast_schemas import PLC_AST
    from src.plc_code_schemas import LDProgram
    from src.req_parser import build_llm
except ImportError:
    from ast_schemas import PLC_AST
    from plc_code_schemas import LDProgram
    from req_parser import build_llm


APPROACH_NAME = "llm_direct"
DEFAULT_OUTPUT_DIR = Path("data/plc/ld")
ALLOWED_CONTACT_TYPES = {"normally_open", "normally_closed"}
ALLOWED_COIL_TYPES = {"normal", "set", "reset"}
IEC_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LLMBackendError(RuntimeError):
    """The selected LLM backend did not return a usable response."""


class LLMOutputValidationError(ValueError):
    """The LLM responded, but its LD IR output failed validation."""


SYSTEM_PROMPT = """\
You are an expert PLC software engineer generating Ladder Diagram intermediate
representation JSON for engineer review.

Return valid JSON only. Do not wrap the response in Markdown fences. Do not add
explanatory prose outside the JSON object.
"""


USER_PROMPT = """\
Generate one Ladder Diagram IR JSON object from this validated PLC_AST.
Return JSON only, no Markdown. Shape: program_name, source_ast_file, networks.
Each network has network_id, title, contacts, coil, priority,
source_ast_node_id, source_step_id, source_scenario,
source_interlock_condition, source_condition, notes. contacts contain variable
and contact_type. coil contains variable and coil_type.

Allowed values: contact_type = normally_open or normally_closed. coil_type =
normal, set, or reset. Preserve AST traceability.

Important network ordering rule: the networks array must list sequence networks
first, followed by interlock/safety networks. All N-SEQ networks must appear
before any N-ILK or safety/interlock network. Do not place N-ILK networks before
N-SEQ networks.

Priority rule: safety/interlock networks may have higher logical priority, but
must still appear after sequence networks in the JSON array. Represent safety
priority with priority and traceability fields, not by moving interlocks first.

Multi-target interlock rule: if an interlock affects multiple target devices,
create one LD network per target coil. Do not put secondary target actions only
in notes. If emergency stop de-energizes EV-101 and EV-102, generate one reset
coil network for EV_101 and one reset coil network for EV_102. Notes must not
replace required output coils.

Variable naming rule: all contact and coil variable names must match
^[A-Za-z_][A-Za-z0-9_]*$. Never use "%" in contact variable, coil variable,
network_id, or program_name. Convert percentages to words: Tank_Level_Sensor_80%
-> Tank_Level_Sensor_80_Percent; level reaches 80% ->
Tank_Level_At_80_Percent; 5-second delay -> Delay_5_Seconds_Elapsed. Do not use
spaces, hyphens, colons, slashes, parentheses, free-text phrases, or TODO as a
coil variable. Examples: Emergency Stop button -> Emergency_Stop_Button; tank
level sensor -> Tank_Level_Sensor; EV-101 -> EV_101; DEV-EV-101 -> DEV_EV_101.

Action rule: open/start/on/energize/activate/run -> set; close/stop/off/
de-energize/deactivate/reset -> reset; ambiguous -> normal or TODO note. If an
interlock closes, stops, disables, de-energizes, resets, or turns off target
devices, create reset coil networks for those targets. Do not replace required
target reset coils with Safety_Interlock_Active unless the AST has no target.

Unsupported timer/analogue/sequence-state rule: keep LD IR structurally valid.
Use sanitized placeholder contacts when needed and record the limitation in
notes. Do not pretend timer or analogue behavior is fully implemented. Example:
contact variable TODO_Timer_Delay_Elapsed; notes ["TODO: 5-second settling delay
requires timer implementation."]. MVP draft only.

PLC_AST JSON: {ast_json}
"""


RETRY_PROMPT = """\
Your previous LD IR JSON failed validation:
{validation_error}

Fix this exact issue and return the full corrected JSON only.
Do not include Markdown fences.
Return JSON only.
Keep sequence networks before interlock networks.
Split multi-target interlocks into one network per target coil.
Use only IEC-compatible variable names matching ^[A-Za-z_][A-Za-z0-9_]*$.
Do not use "%" anywhere in variable names, network_id, or program_name.
Replace "%" with "_Percent" or another IEC-compatible word.
Do not use TODO as a coil variable.
Preserve required fields including contact_type and coil_type.
network_id must be a string such as "SEQ-1" or "ILK-2_EV_101", never a number.
priority must be an integer, for example 1 or 2, never null.
notes must be an array, for example [] or ["TODO: text"], never a plain string.
"""


LOCAL_USER_PROMPT = """\
Generate compact, complete, valid LDProgram JSON only from this PLC_AST. No
Markdown. Close all braces/brackets. Use short titles and short notes. Omit
fields whose value would be null; Pydantic will restore schema defaults.
Required top keys: program_name, networks, source_ast_file. Each network needs
network_id,title,contacts,coil,priority,source_ast_node_id,notes plus
source_step_id for sequences or source_interlock_condition for interlocks. Each
contact needs variable and contact_type. coil needs variable and coil_type.
network_id is a string like "SEQ-1" or "ILK-2_EV_101", never a number. priority
is an integer, never null. notes is always an array: [] or ["TODO: text"], never
a plain string.

Allowed: contact_type normally_open/normally_closed; coil_type normal/set/reset.
Order rule: all sequence networks first, then interlock/safety networks. Safety
priority goes in priority fields, not array order.
Multi-target rule: if interlock affects EV-101 and EV-102, create two reset coil
networks, one for EV_101 and one for EV_102. Do not replace target resets with
Safety_Interlock_Active when target devices exist.
Name rule: contact/coil variables match ^[A-Za-z_][A-Za-z0-9_]*$. No spaces,
hyphens, %, :, /, parentheses, or free-text. Never use TODO as coil variable.
Convert % to Percent: Tank_Level_Sensor_80_Percent. Delay example:
Delay_5_Seconds_Elapsed.
Action rule: open/start/on/energize/activate/run -> set; close/stop/off/
de-energize/deactivate/reset -> reset.
Unsupported timer/analogue/state: use sanitized placeholder contact with
contact_type normally_open and TODO notes. Do not claim full implementation.

source_ast_file: {source_ast_file}
PLC_AST: {ast_json}
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
    """Resolve backend-specific LLM-direct LD IR output path."""
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_OUTPUT_DIR / f"{ast_path.stem}_ld_{APPROACH_NAME}_{backend}.json"


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


def clean_llm_json(text: str) -> str:
    """Strip accidental Markdown fences while preserving JSON text."""
    cleaned = text.strip()
    fence_match = re.fullmatch(r"```[A-Za-z0-9_-]*\s*(.*?)\s*```", cleaned, re.S)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    cleaned = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", cleaned).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned


def parse_ld_json(text: str) -> dict[str, Any]:
    """Parse model output as JSON object."""
    cleaned = clean_llm_json(text)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("LLM output must be a JSON object matching LDProgram.")
    return value


def _is_invalid_variable_name(variable: str) -> bool:
    if not variable:
        return True
    if variable.strip().upper() == "TODO":
        return True
    return not bool(IEC_NAME_PATTERN.fullmatch(variable))


def _is_invalid_coil_variable(variable: str) -> bool:
    if _is_invalid_variable_name(variable):
        return True
    return variable == "Safety_Interlock_Active"


def _sanitize_var_name(name: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z]+", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if sanitized and sanitized[0].isdigit():
        sanitized = f"V_{sanitized}"
    return sanitized or "unnamed"


def _text_mentions_device(text: str | None, device_name: str) -> bool:
    if not text:
        return False
    escaped = re.escape(device_name.lower())
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text.lower()))


def _coil_matches_device(coil_variable: str, device_name: str) -> bool:
    sanitized = _sanitize_var_name(device_name)
    return coil_variable == sanitized or coil_variable.endswith(f"_{sanitized}")


def _expected_interlock_targets(ast: PLC_AST) -> dict[str, list[str]]:
    targets: dict[str, list[str]] = {}
    device_names = [device.name for device in ast.devices]
    for interlock in ast.interlocks:
        action_targets = [
            name
            for name in interlock.affected_devices
            if name in device_names and _text_mentions_device(interlock.forced_action, name)
        ]
        if action_targets:
            targets[interlock.node_id] = action_targets
    return targets


def validate_ld_structure(
    program: LDProgram,
    expected_interlock_targets: dict[str, list[str]] | None = None,
) -> None:
    """Perform light structural validation beyond Pydantic schema checks."""
    if not program.networks:
        raise ValueError("LD IR must contain at least one network.")
    if not program.source_ast_file:
        raise ValueError("LDProgram.source_ast_file must be populated.")
    if "%" in program.program_name:
        raise ValueError(
            f"LDProgram.program_name contains '%': {program.program_name!r}. "
            "Replace '%' with '_Percent' or another IEC-compatible word."
        )

    seen_ids: set[str] = set()
    first_interlock_index: int | None = None
    for index, network in enumerate(program.networks):
        if not network.network_id:
            raise ValueError("Every LD network must have a non-empty network_id.")
        if "%" in network.network_id:
            raise ValueError(
                f"Network ID contains '%': {network.network_id!r}. "
                "Replace '%' with '_Percent' or another IEC-compatible word."
            )
        if network.network_id in seen_ids:
            raise ValueError(f"Duplicate LD network_id: {network.network_id}")
        seen_ids.add(network.network_id)

        if not network.source_ast_node_id:
            raise ValueError(
                f"Network {network.network_id} is missing source_ast_node_id traceability."
            )
        if network.source_interlock_condition and first_interlock_index is None:
            first_interlock_index = index
        if first_interlock_index is not None and not network.source_interlock_condition:
            raise ValueError(
                "Sequence network appears after a safety/interlock network; "
                f"offending network_id={network.network_id}"
            )

        for contact in network.contacts:
            if contact.contact_type not in ALLOWED_CONTACT_TYPES:
                raise ValueError(
                    f"Network {network.network_id} has invalid contact_type "
                    f"{contact.contact_type!r}."
                )
            if not contact.variable:
                raise ValueError(f"Network {network.network_id} has an empty contact variable.")
            if _is_invalid_variable_name(contact.variable):
                raise ValueError(
                    f"Network {network.network_id} has invalid contact variable "
                    f"{contact.variable!r}; use a sanitized IEC-compatible name."
                )

        if network.coil.coil_type not in ALLOWED_COIL_TYPES:
            raise ValueError(
                f"Network {network.network_id} has invalid coil_type "
                f"{network.coil.coil_type!r}."
            )
        if not network.coil.variable:
            raise ValueError(f"Network {network.network_id} has an empty coil variable.")
        if _is_invalid_coil_variable(network.coil.variable):
            raise ValueError(
                f"Network {network.network_id} has invalid coil variable "
                f"{network.coil.variable!r}; use a target device coil where one "
                "is identified, not a generic marker coil."
            )

    expected_interlock_targets = expected_interlock_targets or {}
    for interlock_id, target_devices in expected_interlock_targets.items():
        related_networks = [
            network
            for network in program.networks
            if network.source_ast_node_id == interlock_id
            or network.network_id.startswith(interlock_id)
        ]
        for target_device in target_devices:
            if not any(
                _coil_matches_device(network.coil.variable, target_device)
                for network in related_networks
            ):
                raise ValueError(
                    f"Interlock {interlock_id} is missing a target coil network "
                    f"for {target_device!r}. Split multi-target interlocks into "
                    "one network per target coil."
                )


def _program_from_message(
    message: Any,
    expected_interlock_targets: dict[str, list[str]],
) -> LDProgram:
    payload = parse_ld_json(_message_content_to_text(getattr(message, "content", message)))
    try:
        program = LDProgram.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"LLM output failed LDProgram schema validation:\n{exc}") from exc
    validate_ld_structure(program, expected_interlock_targets)
    return program


def generate_ld_program(ast: PLC_AST, source_ast_file: Path, backend: str) -> LDProgram:
    """Ask the selected LLM backend to directly generate LD IR JSON."""
    if backend == "api" and not os.getenv("GEMINI_API_KEY"):
        raise LLMBackendError(
            "The api backend requires GEMINI_API_KEY to be set. "
            "No output was generated."
        )

    llm_kwargs: dict[str, Any] = {"max_tokens": 1500 if backend == "local" else 2600}
    if backend == "api":
        llm_kwargs["response_format"] = {"type": "json_object"}
    else:
        llm_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "LDProgram",
                "schema": LDProgram.model_json_schema(),
            },
        }
    llm = build_llm(backend).bind(**llm_kwargs)
    user_prompt = LOCAL_USER_PROMPT if backend == "local" else USER_PROMPT
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", user_prompt),
        ]
    )
    prompt_vars = {
        "source_ast_file": str(source_ast_file.resolve()),
        "ast_json": ast.model_dump_json(exclude_none=True),
    }
    expected_targets = _expected_interlock_targets(ast)

    validation_error: str | None = None
    max_validation_retries = 2 if backend == "local" else 1
    for attempt in range(max_validation_retries + 1):
        active_prompt = prompt
        active_vars = prompt_vars
        if attempt >= 1:
            active_prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", SYSTEM_PROMPT),
                    ("human", user_prompt),
                    ("human", RETRY_PROMPT),
                ]
            )
            active_vars = {**prompt_vars, "validation_error": validation_error or "Unknown validation error"}

        try:
            message = (active_prompt | llm).invoke(active_vars)
        except Exception as exc:  # noqa: BLE001
            raise LLMBackendError(
                f"LLM direct LD IR generation failed for {backend}: {exc}"
            ) from exc

        try:
            return _program_from_message(message, expected_targets)
        except ValueError as exc:
            validation_error = str(exc)
            if attempt == max_validation_retries:
                raise LLMOutputValidationError(
                    "LLM returned JSON, but it failed LD IR validation:\n"
                    f"{validation_error}"
                ) from exc

    raise LLMOutputValidationError(
        "LLM returned JSON, but it failed LD IR validation after retries."
    )


def write_ld_file(ast_path: Path, backend: str) -> Path:
    ast = load_ast(ast_path)
    program = generate_ld_program(ast, ast_path, backend)
    output_path = resolve_output_path(ast_path, backend)
    output_path.write_text(program.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate LLM-direct Ladder Diagram IR JSON from PLC_AST JSON."
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
        output_path = write_ld_file(args.ast_file, args.backend)
    except LLMOutputValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "The local backend is reachable. This is an output validation issue, "
            "not a connection issue.",
            file=sys.stderr,
        )
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except LLMBackendError as exc:
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

    print(f"Generated LLM-direct LD IR ({args.backend}): {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
