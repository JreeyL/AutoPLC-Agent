"""Deterministic Ladder Diagram IR generator for PLC_AST files (E2S4T3).

This MVP generator converts a validated :class:`src.ast_schemas.PLC_AST` JSON
file into a structured Ladder Diagram intermediate representation. It emits
JSON only: no graphical LD rendering, PLCopen XML export, or LLM calls.

Usage::

    python -m src.ld_ir_gen data/ast/signal_light_demo_api_AST_C.json
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from pydantic import ValidationError

try:
    from src.ast_schemas import PLC_AST, InterlockNode, SequenceStepNode
    from src.plc_code_schemas import LDCoil, LDContact, LDNetwork, LDProgram
except ImportError:
    from ast_schemas import PLC_AST, InterlockNode, SequenceStepNode
    from plc_code_schemas import LDCoil, LDContact, LDNetwork, LDProgram


DEFAULT_OUTPUT_DIR = Path("data/plc/ld")

_SET_ACTION_TERMS = (
    "open",
    "opened",
    "opens",
    "opening",
    "start",
    "started",
    "starts",
    "starting",
    "on",
    "energize",
    "energized",
    "energizes",
    "energizing",
    "activate",
    "activated",
    "activates",
    "activating",
    "run",
    "runs",
    "running",
    "green",
    "red",
    "switch to",
)
_RESET_ACTION_TERMS = (
    "close",
    "closed",
    "closes",
    "closing",
    "stop",
    "stopped",
    "stops",
    "stopping",
    "off",
    "de-energize",
    "de-energized",
    "de-energizes",
    "de-energizing",
    "deenergize",
    "deenergized",
    "deenergizes",
    "deenergizing",
    "deactivate",
    "deactivated",
    "deactivates",
    "deactivating",
    "reset",
    "resets",
    "resetting",
)
_NEGATION_TERMS = ("do not", "don't", "not", "never", "no", "cannot", "can't", "must not")
_UNSUPPORTED_OR_PATTERN = re.compile(r"(?<![a-z0-9])or(?![a-z0-9])", re.IGNORECASE)
_UNSUPPORTED_NEGATION_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:not|never|no|cannot|can't|without)(?![a-z0-9])",
    re.IGNORECASE,
)
_UNSUPPORTED_COMPARISON_PATTERN = re.compile(
    r"(?:[<>]=?|==|!=|=|\b(?:greater|less|above|below|at least|at most|"
    r"reaches?|exceeds?|under|over)\b|\d+(?:\.\d+)?\s*%)",
    re.IGNORECASE,
)
_UNSUPPORTED_TIMER_PATTERN = re.compile(
    r"\b(?:timer|delay|duration|elapsed|seconds?|second|minutes?|minute|hours?|hour|"
    r"ms|milliseconds?)\b|\b\d+(?:\.\d+)?\s*(?:ms|s|sec|secs|seconds?|m|min|mins|"
    r"minutes?|h|hr|hrs|hours?)\b",
    re.IGNORECASE,
)


def sanitize_var_name(name: str) -> str:
    """Convert a source equipment name into a readable PLC variable name."""
    sanitized = re.sub(r"[^0-9A-Za-z]+", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if sanitized and sanitized[0].isdigit():
        sanitized = f"V_{sanitized}"
    return sanitized or "unnamed"


def _load_ast(path: Path) -> PLC_AST:
    try:
        return PLC_AST.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError:
        raise
    except OSError as exc:
        raise RuntimeError(f"Failed to read AST file {path}: {exc}") from exc


def _clean_comment_text(text: str | None) -> str:
    if text is None:
        return "None"
    return re.sub(r"\s+", " ", text).strip()


def _text_mentions_device(text: str | None, device_name: str) -> bool:
    if not text:
        return False
    escaped = re.escape(device_name.lower())
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text.lower()))


def _find_mentioned_devices(text: str | None, device_names: list[str]) -> list[str]:
    return [name for name in device_names if _text_mentions_device(text, name)]


def _term_pattern(term: str) -> str:
    parts = [re.escape(part) for part in term.split()]
    return r"(?<![a-z0-9-])" + r"\s+".join(parts) + r"(?![a-z0-9-])"


def _has_action_term(text: str, term: str) -> bool:
    return bool(re.search(_term_pattern(term), text, re.IGNORECASE))


def _has_negated_action(text: str, term: str) -> bool:
    negation = "|".join(re.escape(term) for term in _NEGATION_TERMS)
    return bool(
        re.search(
            rf"(?<![a-z0-9])(?:{negation})(?![a-z0-9])"
            rf"(?:\s+\w+){{0,3}}\s+{_term_pattern(term)}",
            text,
            re.IGNORECASE,
        )
    )


def action_text_to_coil_type(action_text: str | None) -> str:
    """Classify explicit action text into LD coil behavior for the MVP."""
    if not action_text:
        return "normal"

    set_matches = [
        term
        for term in _SET_ACTION_TERMS
        if _has_action_term(action_text, term)
        and not _has_negated_action(action_text, term)
    ]
    reset_matches = [
        term
        for term in _RESET_ACTION_TERMS
        if _has_action_term(action_text, term)
        and not _has_negated_action(action_text, term)
    ]

    if set_matches and not reset_matches:
        return "set"
    if reset_matches and not set_matches:
        return "reset"
    return "normal"


def _sequence_action_text(step: SequenceStepNode) -> str:
    text = step.action
    if re.match(r"\s*(?:when|once|if)\b", text, re.IGNORECASE) and "," in text:
        return text.split(",", 1)[1].strip()
    return text


def _unsupported_condition_reasons(text: str | None) -> list[str]:
    if not text:
        return []

    reasons: list[str] = []
    if _UNSUPPORTED_OR_PATTERN.search(text):
        reasons.append("OR expressions are not supported by the LD IR MVP")
    if _UNSUPPORTED_NEGATION_PATTERN.search(text):
        reasons.append("negated contact conditions are not supported by the LD IR MVP")
    if _UNSUPPORTED_COMPARISON_PATTERN.search(text):
        reasons.append("numeric comparisons or analogue thresholds are not supported by the LD IR MVP")
    if _UNSUPPORTED_TIMER_PATTERN.search(text):
        reasons.append("timer or duration conditions are not supported by the LD IR MVP")
    return reasons


def _build_device_var_map(ast: PLC_AST) -> dict[str, str]:
    """Map source device names to unique sanitized PLC variable names."""
    result: dict[str, str] = {}
    used: set[str] = set()

    for device in ast.devices:
        base = sanitize_var_name(device.name)
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}_{index}"
            index += 1
        used.add(candidate)
        result[device.name] = candidate

    return result


def _build_contacts(
    text: str | None,
    device_names: list[str],
    device_vars: dict[str, str],
) -> tuple[list[LDContact], list[str]]:
    unsupported_reasons = _unsupported_condition_reasons(text)
    if unsupported_reasons:
        notes = [
            f"TODO_UNSUPPORTED_CONDITION: {_clean_comment_text(text)}",
            *unsupported_reasons,
        ]
        return [], notes

    return [
        LDContact(variable=device_vars[name], contact_type="normally_open")
        for name in _find_mentioned_devices(text, device_names)
    ], []


def _placeholder_sequence_coil(node_id: str) -> LDCoil:
    return LDCoil(
        variable=f"TODO_UNMAPPED_TARGET_{sanitize_var_name(node_id)}",
        coil_type="normal",
    )


def _placeholder_interlock_coil(node_id: str, coil_type: str = "normal") -> LDCoil:
    return LDCoil(
        variable=f"TODO_UNMAPPED_INTERLOCK_TARGET_{sanitize_var_name(node_id)}",
        coil_type=coil_type,
    )


def _build_sequence_network(
    step: SequenceStepNode,
    device_names: list[str],
    device_vars: dict[str, str],
) -> LDNetwork:
    contacts, notes = _build_contacts(step.condition, device_names, device_vars)
    if step.target_device and step.target_device in device_vars:
        coil = LDCoil(
            variable=device_vars[step.target_device],
            coil_type=action_text_to_coil_type(_sequence_action_text(step)),
        )
    else:
        coil = _placeholder_sequence_coil(step.node_id)

    return LDNetwork(
        network_id=step.node_id,
        title=f"Sequence Step {step.step_id}",
        contacts=contacts,
        coil=coil,
        priority=1,
        source_ast_node_id=step.node_id,
        source_step_id=step.source_step_id,
        source_scenario=step.source_scenario,
        source_condition=step.condition,
        notes=notes,
    )


def _interlock_targets(
    interlock: InterlockNode,
    device_names: list[str],
    device_vars: dict[str, str],
) -> list[str]:
    condition_devices = _find_mentioned_devices(interlock.condition, device_names)
    affected_devices = [name for name in interlock.affected_devices if name in device_vars]

    targets = [name for name in affected_devices if name not in condition_devices]
    if targets:
        return targets
    return affected_devices


def _build_interlock_networks(
    interlock: InterlockNode,
    device_names: list[str],
    device_vars: dict[str, str],
) -> list[LDNetwork]:
    contacts, notes = _build_contacts(interlock.condition, device_names, device_vars)
    coil_type = action_text_to_coil_type(interlock.forced_action)
    targets = _interlock_targets(interlock, device_names, device_vars)

    if not targets:
        return [
            LDNetwork(
                network_id=interlock.node_id,
                title=f"Safety Interlock {interlock.node_id}",
                contacts=contacts,
                coil=_placeholder_interlock_coil(interlock.node_id, coil_type),
                priority=interlock.priority,
                source_ast_node_id=interlock.node_id,
                source_scenario=interlock.source_scenario,
                source_interlock_condition=interlock.source_interlock_condition,
                source_condition=interlock.condition,
                notes=notes,
            )
        ]

    use_target_suffix = len(targets) > 1
    networks: list[LDNetwork] = []
    for target in targets:
        target_var = device_vars[target]
        network_id = (
            f"{interlock.node_id}_{target_var}" if use_target_suffix else interlock.node_id
        )
        networks.append(
            LDNetwork(
                network_id=network_id,
                title=f"Safety Interlock {interlock.node_id}",
                contacts=contacts,
                coil=LDCoil(variable=target_var, coil_type=coil_type),
                priority=interlock.priority,
                source_ast_node_id=interlock.node_id,
                source_scenario=interlock.source_scenario,
                source_interlock_condition=interlock.source_interlock_condition,
                source_condition=interlock.condition,
                notes=notes,
            )
        )
    return networks


def build_ld_program(
    ast: PLC_AST,
    source_ast_file: Path,
    fallback_stem: str,
) -> LDProgram:
    """Build the LDProgram contract object from a PLC_AST."""
    device_vars = _build_device_var_map(ast)
    device_names = [device.name for device in ast.devices]
    program_name_source = ast.feature_title if ast.feature_title.strip() else fallback_stem

    networks: list[LDNetwork] = []
    networks.extend(
        _build_sequence_network(step, device_names, device_vars) for step in ast.sequence
    )
    for interlock in ast.interlocks:
        networks.extend(_build_interlock_networks(interlock, device_names, device_vars))

    return LDProgram(
        program_name=sanitize_var_name(program_name_source),
        networks=networks,
        source_ast_file=str(source_ast_file.resolve()),
    )


def write_ld_file(
    ast_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, LDProgram]:
    ast = _load_ast(ast_path)
    program = build_ld_program(ast, ast_path, ast_path.stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{ast_path.stem}_ld.json"
    output_path.write_text(program.model_dump_json(indent=2), encoding="utf-8")
    return output_path, program


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic Ladder Diagram IR JSON from PLC_AST JSON."
    )
    parser.add_argument("ast_file", help="Path to a validated PLC_AST JSON file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    ast_path = Path(args.ast_file)

    try:
        output_path, program = write_ld_file(ast_path)
    except ValidationError as exc:
        print(f"ERROR: Invalid PLC_AST JSON: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Generated LD IR: {output_path} ({len(program.networks)} networks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
