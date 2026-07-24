"""Deterministic Structured Text draft generator for PLC_AST files (E2S4T2).

This MVP generator converts a validated :class:`src.ast_schemas.PLC_AST` JSON
file into a readable IEC 61131-3-style Structured Text draft. It performs no
LLM calls and intentionally uses simple rule-based mapping only.

Usage::

    python -m src.st_gen data/ast/signal_light_demo_api_AST_C.json
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from pydantic import ValidationError

try:
    from src.ast_schemas import PLC_AST, InterlockNode, SequenceStepNode
    from src.plc_code_schemas import STBlock, STProgram
except ImportError:
    from ast_schemas import PLC_AST, InterlockNode, SequenceStepNode
    from plc_code_schemas import STBlock, STProgram


DEFAULT_OUTPUT_DIR = Path("data/plc/st")

_FALSE_ACTION_WORDS = ("close", "de-energize", "turn off")
_INTERLOCK_FALSE_WORDS = ("close", "de-energize", "stop", "off")
_INTERLOCK_TRUE_WORDS = ("open", "start", "on", "green", "red", "switch to")


def sanitize_var_name(name: str) -> str:
    """Convert a source equipment name into a readable ST variable name."""
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


def _find_mentioned_devices(
    text: str | None,
    device_names: list[str],
) -> list[str]:
    return [name for name in device_names if _text_mentions_device(text, name)]


def _build_device_var_map(ast: PLC_AST) -> dict[str, str]:
    """Map source device names to unique sanitized ST variable names."""
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


def _build_variable_declarations(ast: PLC_AST, device_vars: dict[str, str]) -> list[str]:
    declarations: list[str] = []
    for device in ast.devices:
        var_name = device_vars[device.name]
        source_name = _clean_comment_text(device.source_equipment or device.name)
        declarations.append(f"{var_name} : BOOL; // source equipment: {source_name}")
    return declarations


def _sequence_target_value(action: str) -> bool:
    lowered = action.lower()
    return not any(word in lowered for word in _FALSE_ACTION_WORDS)


def _interlock_target_value(forced_action: str) -> bool | None:
    lowered = forced_action.lower()
    if any(word in lowered for word in _INTERLOCK_FALSE_WORDS):
        return False
    if any(word in lowered for word in _INTERLOCK_TRUE_WORDS):
        return True
    return None


def _bool_literal(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _render_condition_expression(trigger_devices: list[str], device_vars: dict[str, str]) -> str:
    return " AND ".join(device_vars[name] for name in trigger_devices)


def _build_sequence_block(
    step: SequenceStepNode,
    device_names: list[str],
    device_vars: dict[str, str],
) -> STBlock:
    lines = [
        f"// {step.node_id}",
        f"// Source step: {step.source_step_id}",
        f"// Source scenario: {_clean_comment_text(step.source_scenario)}",
        f"// Action: {_clean_comment_text(step.action)}",
        "// Draft logic: deterministic MVP mapping; requires engineer review.",
    ]

    trigger_devices = _find_mentioned_devices(step.condition, device_names)
    target_device = step.target_device if step.target_device in device_vars else None

    if not trigger_devices:
        lines.append(
            f"// TODO: Map source condition to ST logic: {_clean_comment_text(step.condition)}"
        )
    if target_device is None:
        lines.append(
            f"// TODO: Map target device for action: {_clean_comment_text(step.action)}"
        )

    if trigger_devices and target_device:
        target_value = _bool_literal(_sequence_target_value(step.action))
        condition_expr = _render_condition_expression(trigger_devices, device_vars)
        lines.extend(
            [
                f"IF {condition_expr} THEN",
                f"    {device_vars[target_device]} := {target_value};",
                "END_IF;",
            ]
        )

    return STBlock(
        block_id=step.node_id,
        title=f"Sequence Step {step.step_id}",
        code="\n".join(lines),
        source_ast_node_id=step.node_id,
        source_step_id=step.source_step_id,
        source_scenario=step.source_scenario,
    )


def _build_interlock_block(
    interlock: InterlockNode,
    device_names: list[str],
    device_vars: dict[str, str],
) -> STBlock:
    lines = [
        f"// {interlock.node_id}",
        f"// Source interlock condition: {_clean_comment_text(interlock.source_interlock_condition)}",
        f"// Source scenario: {_clean_comment_text(interlock.source_scenario)}",
        f"// Forced action: {_clean_comment_text(interlock.forced_action)}",
        f"// Priority: {interlock.priority}",
        "// Draft logic: safety override emitted after sequence logic; requires engineer review.",
    ]

    trigger_devices = _find_mentioned_devices(interlock.condition, device_names)
    action_devices = _find_mentioned_devices(interlock.forced_action, device_names)
    affected_devices = [name for name in interlock.affected_devices if name in device_vars]

    targets = [name for name in affected_devices if name not in trigger_devices]
    if not targets:
        targets = [name for name in action_devices if name not in trigger_devices]
    if not targets:
        targets = affected_devices

    target_value = _interlock_target_value(interlock.forced_action)

    if not trigger_devices:
        lines.append(
            f"// TODO: Map interlock condition to ST logic: {_clean_comment_text(interlock.condition)}"
        )
    if not targets:
        lines.append(
            f"// TODO: Map affected devices for forced action: {_clean_comment_text(interlock.forced_action)}"
        )
    if target_value is None:
        lines.append(
            f"// TODO: Determine forced BOOL value for action: {_clean_comment_text(interlock.forced_action)}"
        )

    if trigger_devices and targets and target_value is not None:
        condition_expr = _render_condition_expression(trigger_devices, device_vars)
        assignment_value = _bool_literal(target_value)
        lines.append(f"IF {condition_expr} THEN")
        for target in targets:
            lines.append(f"    {device_vars[target]} := {assignment_value};")
        lines.append("END_IF;")

    return STBlock(
        block_id=interlock.node_id,
        title=f"Safety Interlock {interlock.node_id}",
        code="\n".join(lines),
        source_ast_node_id=interlock.node_id,
        source_scenario=interlock.source_scenario,
        source_interlock_condition=interlock.source_interlock_condition,
    )


def build_st_program(ast: PLC_AST, source_ast_file: Path, fallback_stem: str) -> STProgram:
    """Build the STProgram contract object before text rendering."""
    device_vars = _build_device_var_map(ast)
    device_names = [device.name for device in ast.devices]

    program_name = sanitize_var_name(ast.feature_title) or sanitize_var_name(fallback_stem)
    variables = _build_variable_declarations(ast, device_vars)
    blocks: list[STBlock] = []

    blocks.extend(
        _build_sequence_block(step, device_names, device_vars) for step in ast.sequence
    )
    blocks.extend(
        _build_interlock_block(interlock, device_names, device_vars)
        for interlock in ast.interlocks
    )

    return STProgram(
        program_name=program_name,
        variables=variables,
        blocks=blocks,
        source_ast_file=str(source_ast_file.resolve()),
    )


def render_st_program(program: STProgram) -> str:
    """Render an STProgram into IEC 61131-3-style Structured Text."""
    sequence_blocks = [
        block for block in program.blocks if block.source_interlock_condition is None
    ]
    interlock_blocks = [
        block for block in program.blocks if block.source_interlock_condition is not None
    ]

    lines = [
        "(*",
        "Generated Structured Text draft from PLC_AST.",
        f"Source AST: {program.source_ast_file}",
        "This output is an MVP draft and requires engineer review.",
        "*)",
        "",
        f"PROGRAM {program.program_name}",
        "VAR",
    ]

    lines.extend(f"    {declaration}" for declaration in program.variables)
    lines.extend(
        [
            "END_VAR",
            "",
            "// ==================================================",
            "// Sequence Logic",
            "// ==================================================",
            "",
        ]
    )

    for block in sequence_blocks:
        lines.append(block.code)
        lines.append("")

    lines.extend(
        [
            "// ==================================================",
            "// Safety Interlocks / Overrides",
            "// ==================================================",
            "",
        ]
    )

    for block in interlock_blocks:
        lines.append(block.code)
        lines.append("")

    lines.append("END_PROGRAM")
    lines.append("")
    return "\n".join(lines)


def write_st_file(ast_path: Path, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, STProgram]:
    ast = _load_ast(ast_path)
    program = build_st_program(ast, ast_path, ast_path.stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{ast_path.stem}.st"
    output_path.write_text(render_st_program(program), encoding="utf-8")
    return output_path, program


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic Structured Text draft from PLC_AST JSON."
    )
    parser.add_argument("ast_file", help="Path to a validated PLC_AST JSON file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    ast_path = Path(args.ast_file)

    try:
        output_path, program = write_st_file(ast_path)
    except ValidationError as exc:
        print(f"ERROR: Invalid PLC_AST JSON: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "Generated ST draft: "
        f"{output_path} "
        f"({len(program.variables)} variables, {len(program.blocks)} ST blocks)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
