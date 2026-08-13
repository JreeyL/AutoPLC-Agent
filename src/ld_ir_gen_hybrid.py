"""Hybrid Ladder Diagram IR generator for PLC_AST files (E2S4T7).

E2S4T7 combines the deterministic LD IR baseline renderer (``src/ld_ir_gen.py``)
with per-item LLM function calls that return *structured code intent* instead of
final JSON. Python renders the final LD IR deterministically from that intent,
so the LLM never emits LD networks directly.

Mapping (LLM suggests, Python renders):
- ``AnalogueIntent``    -> contact with ``operator`` / ``threshold`` fields
- ``TimerIntent``       -> network-level ``timer_duration_seconds`` /
                           ``timer_description`` metadata plus a review note
- ``ColourStateIntent`` -> review note (enumerated colour variable required)
- ``state_notes``       -> review notes

This follows the same principle as E2S3 Approach C and E2S4T6 (hybrid ST): the
LLM provides semantic suggestions; Python owns grounding, validation, network
assembly, ordering, and traceability.

Usage::

    python -m src.ld_ir_gen_hybrid data/ast/signal_light_demo_api_AST_C.json --backend api
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pydantic import ValidationError

try:
    from src.ld_ir_gen import (
        DEFAULT_OUTPUT_DIR,
        _build_contacts,
        _build_device_var_map,
        _clean_comment_text,
        _find_mentioned_devices,
        _interlock_targets,
        _load_ast,
        _placeholder_interlock_coil,
        _placeholder_sequence_coil,
        _sequence_action_text,
        action_text_to_coil_type,
        sanitize_var_name,
    )
    from src.ld_ir_gen_llm_direct import validate_ld_structure
    from src.plc_code_schemas import LDCoil, LDContact, LDNetwork, LDProgram
    from src.st_gen_hybrid import (
        _EMPTY_INTERLOCK_INTENT,
        _EMPTY_SEQUENCE_INTENT,
        _collect_intents,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from ld_ir_gen import (
        DEFAULT_OUTPUT_DIR,
        _build_contacts,
        _build_device_var_map,
        _clean_comment_text,
        _find_mentioned_devices,
        _interlock_targets,
        _load_ast,
        _placeholder_interlock_coil,
        _placeholder_sequence_coil,
        _sequence_action_text,
        action_text_to_coil_type,
        sanitize_var_name,
    )
    from ld_ir_gen_llm_direct import validate_ld_structure
    from plc_code_schemas import LDCoil, LDContact, LDNetwork, LDProgram
    from st_gen_hybrid import (
        _EMPTY_INTERLOCK_INTENT,
        _EMPTY_SEQUENCE_INTENT,
        _collect_intents,
    )


APPROACH_NAME = "hybrid"


# ---------------------------------------------------------------------------
# Deterministic LD IR rendering (Python-owned final code)
# ---------------------------------------------------------------------------

def _build_hybrid_sequence_network(
    step: object,
    intent: object,
    device_names: list[str],
    device_vars: dict[str, str],
) -> LDNetwork:
    """Build one hybrid sequence network from baseline logic plus code intent."""
    contacts: list[LDContact] = []
    notes: list[str] = []

    if intent.analogue_conditions:
        # Analogue conditions become real comparison contacts instead of the
        # baseline "unsupported condition" TODO note.
        for cond in intent.analogue_conditions:
            analogue_var = device_vars.get(cond.device)
            if not analogue_var:
                continue
            contacts.append(
                LDContact(
                    variable=analogue_var,
                    contact_type="normally_open",
                    operator=cond.operator,
                    threshold=cond.threshold,
                )
            )
            note = f"Hybrid analogue condition: {analogue_var} {cond.operator} {cond.threshold:g}"
            if cond.description:
                note += f" ({_clean_comment_text(cond.description)})"
            notes.append(note)
    elif intent.timers:
        # Timer-gated network: plain condition contacts (may be empty) plus
        # network-level timer metadata replacing the baseline TODO note.
        contacts = [
            LDContact(variable=device_vars[name], contact_type="normally_open")
            for name in _find_mentioned_devices(step.condition, device_names)
            if name in device_vars
        ]
        timer = intent.timers[0]
        notes.append(
            f"Hybrid timer: {timer.duration_seconds:g}s ({_clean_comment_text(timer.description)})"
        )
    else:
        contacts, notes = _build_contacts(step.condition, device_names, device_vars)

    if step.target_device and step.target_device in device_vars:
        coil = LDCoil(
            variable=device_vars[step.target_device],
            coil_type=action_text_to_coil_type(_sequence_action_text(step)),
        )
    else:
        coil = _placeholder_sequence_coil(step.node_id)

    for state in intent.colour_states:
        if state.device in device_vars:
            notes.append(
                f"TODO_COLOUR_STATE: {state.device} -> {state.colour} "
                "(enumerated colour variable required)"
            )
    notes.extend(f"State logic: {_clean_comment_text(note)}" for note in intent.state_notes)

    timer = intent.timers[0] if intent.timers else None
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
        timer_duration_seconds=timer.duration_seconds if timer else None,
        timer_description=_clean_comment_text(timer.description) if timer else None,
    )


def _build_hybrid_interlock_networks(
    interlock: object,
    intent: object,
    device_names: list[str],
    device_vars: dict[str, str],
) -> list[LDNetwork]:
    """Build hybrid interlock networks (one per target coil) from intent."""
    contacts, notes = _build_contacts(interlock.condition, device_names, device_vars)
    coil_type = action_text_to_coil_type(interlock.forced_action)
    targets = _interlock_targets(interlock, device_names, device_vars)

    for state in intent.colour_states:
        if state.device in device_vars:
            notes.append(
                f"TODO_COLOUR_STATE: {state.device} -> {state.colour} "
                "(enumerated colour variable required)"
            )
    notes.extend(f"State logic: {_clean_comment_text(note)}" for note in intent.state_notes)

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


def build_hybrid_ld_program(
    ast: object,
    source_ast_file: Path,
    backend: str,
) -> LDProgram:
    """Collect LLM code intent and assemble the hybrid LDProgram contract."""
    sequence_intents, interlock_intents = _collect_intents(ast, backend)

    device_vars = _build_device_var_map(ast)
    device_names = [device.name for device in ast.devices]
    program_name_source = ast.feature_title if ast.feature_title.strip() else source_ast_file.stem

    networks: list[LDNetwork] = []
    for step in ast.sequence:
        intent = sequence_intents.get(step.step_id, _EMPTY_SEQUENCE_INTENT)
        networks.append(
            _build_hybrid_sequence_network(step, intent, device_names, device_vars)
        )
    for index, interlock in enumerate(ast.interlocks, start=1):
        intent = interlock_intents.get(index, _EMPTY_INTERLOCK_INTENT)
        networks.extend(
            _build_hybrid_interlock_networks(interlock, intent, device_names, device_vars)
        )

    return LDProgram(
        program_name=sanitize_var_name(program_name_source),
        networks=networks,
        source_ast_file=str(source_ast_file.resolve()),
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def resolve_output_path(ast_path: Path, backend: str) -> Path:
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_OUTPUT_DIR / f"{ast_path.stem}_ld_{APPROACH_NAME}_{backend}.json"


def load_ast(path: Path) -> object:
    """Load and validate a PLC_AST JSON file (wraps st_gen errors cleanly)."""
    try:
        return _load_ast(path)
    except ValidationError as exc:
        raise ValueError(f"Invalid PLC_AST JSON: {path}\n{exc}") from exc
    except OSError as exc:
        raise FileNotFoundError(f"AST file not found: {path}") from exc


def write_ld_file(ast_path: Path, backend: str) -> Path:
    if backend == "api" and not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "The api backend requires GEMINI_API_KEY to be set. No output was generated."
        )
    ast = load_ast(ast_path)
    program = build_hybrid_ld_program(ast, ast_path, backend)
    # Hybrid output is deterministic, but prove it satisfies the same structural
    # rules enforced on LLM-direct output before writing.
    validate_ld_structure(program)
    output_path = resolve_output_path(ast_path, backend)
    output_path.write_text(program.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a hybrid Ladder Diagram IR JSON from PLC_AST JSON (E2S4T7)."
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

    print(f"Generated hybrid LD IR ({args.backend}): {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
