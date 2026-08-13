"""Hybrid Structured Text draft generator for PLC_AST files (E2S4T6).

E2S4T6 combines the deterministic baseline renderer (``src/st_gen.py``) with
per-item LLM function calls that return *structured code intent* instead of
final code. Python renders the final Structured Text deterministically from
that intent, so the LLM never emits ST directly.

Mapping (LLM suggests, Python renders):
- ``TimerIntent``        -> deterministic TON function-block rendering
- ``ColourStateIntent``  -> deterministic colour-state comment + BOOL note
- ``AnalogueIntent``     -> deterministic REAL comparison rendering
- ``state_notes``        -> deterministic review comments

This follows the same principle as E2S3 Approach C: the LLM provides semantic
suggestions; Python owns grounding, validation, variable naming, and rendering.

Usage::

    python -m src.st_gen_hybrid data/ast/signal_light_demo_api_AST_C.json --backend api
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

try:
    from src.req_parser import build_llm
    from src.st_gen import (
        DEFAULT_OUTPUT_DIR,
        _bool_literal,
        _clean_comment_text,
        _find_mentioned_devices,
        _interlock_target_value,
        _load_ast,
        _render_condition_expression,
        _sequence_target_value,
        render_st_program,
        sanitize_var_name,
    )
    from src.st_hybrid_schemas import (
        AnalogueIntent,
        InterlockCodeIntent,
        SequenceCodeIntent,
    )
    from src.plc_code_schemas import STBlock, STProgram
except ImportError:  # pragma: no cover - direct script execution fallback
    from req_parser import build_llm
    from st_gen import (
        DEFAULT_OUTPUT_DIR,
        _bool_literal,
        _clean_comment_text,
        _find_mentioned_devices,
        _interlock_target_value,
        _load_ast,
        _render_condition_expression,
        _sequence_target_value,
        render_st_program,
        sanitize_var_name,
    )
    from st_hybrid_schemas import (
        AnalogueIntent,
        InterlockCodeIntent,
        SequenceCodeIntent,
    )
    from plc_code_schemas import STBlock, STProgram


APPROACH_NAME = "hybrid"

# Sentinel used to distinguish "no intent supplied by the model" from a
# grounding failure; both are handled deterministically by Python.
_EMPTY_SEQUENCE_INTENT = SequenceCodeIntent()
_EMPTY_INTERLOCK_INTENT = InterlockCodeIntent()


# ---------------------------------------------------------------------------
# Intent tool contracts (bound to the LLM as function-calling tools)
# ---------------------------------------------------------------------------

def suggest_sequence_intent(
    timers: list[Any] | None = None,
    colour_states: list[Any] | None = None,
    analogue_conditions: list[Any] | None = None,
    state_notes: list[str] | None = None,
) -> SequenceCodeIntent:
    """Return structured code intent for one control-sequence step.

    Provide entries ONLY for complex logic that a plain BOOL assignment cannot
    represent: timers/delays, analogue threshold conditions, colour/state
    changes, or sequence-state notes. Return empty lists when the step is fully
    covered by a plain BOOL draft. Device names inside ``colour_states`` and
    ``analogue_conditions`` must come from the supplied equipment list.
    """
    return SequenceCodeIntent(
        timers=timers or [],
        colour_states=colour_states or [],
        analogue_conditions=analogue_conditions or [],
        state_notes=state_notes or [],
    )


def suggest_interlock_intent(
    colour_states: list[Any] | None = None,
    state_notes: list[str] | None = None,
) -> InterlockCodeIntent:
    """Return structured code intent for one safety interlock.

    Provide entries ONLY for complex forced logic that a plain BOOL draft
    cannot represent (colour/state changes, logic notes). Return empty lists
    when fully covered. Device names must come from the supplied equipment
    list.
    """
    return InterlockCodeIntent(
        colour_states=colour_states or [],
        state_notes=state_notes or [],
    )


# ---------------------------------------------------------------------------
# Tool-calling plumbing (same pattern as E2S3 Approach C)
# ---------------------------------------------------------------------------

def _extract_tool_args(message: Any, expected_name: str, label: str) -> dict[str, Any]:
    """Extract exactly one expected tool call from an AIMessage."""
    calls = getattr(message, "tool_calls", None) or []
    if not calls and getattr(message, "additional_kwargs", None):
        calls = message.additional_kwargs.get("tool_calls", [])
    matching = [
        call
        for call in calls
        if (call.get("name") or call.get("function", {}).get("name")) == expected_name
    ]
    if len(matching) != 1:
        raise ValueError(
            f"Unsupported function-call result for {label}: expected exactly one "
            f"{expected_name} call, received {len(matching)}. Raw tool calls: {calls!r}"
        )
    call = matching[0]
    args = call.get("args")
    if args is None:
        args = call.get("function", {}).get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON arguments for {expected_name}: {args!r}") from exc
    if not isinstance(args, dict):
        raise ValueError(f"Invalid arguments for {expected_name}: {args!r}")
    return args


def _invoke_intent(
    llm: Any,
    tool: Any,
    prompt: str,
    expected_name: str,
    label: str,
    backend: str,
) -> dict[str, Any]:
    """Ask for one structured intent tool call and return its arguments."""
    try:
        # LM Studio only accepts string tool_choice values such as "required".
        # Since exactly one tool is bound per call, this still forces the
        # intended intent tool. _extract_tool_args() validates the returned name.
        tool_choice = "required" if backend == "local" else expected_name
        bound = llm.bind_tools([tool], tool_choice=tool_choice)
        message = bound.invoke(prompt)
        return _extract_tool_args(message, expected_name, label)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Function call failed for {label}: {exc}") from exc


# ---------------------------------------------------------------------------
# Grounding checks (Python-owned; never weakened to make LLM output pass)
# ---------------------------------------------------------------------------

_COLOURS = ("green", "red", "yellow", "on", "off")
_OPERATORS = (">=", "<=", ">", "<", "==")
_ANALOGUE_RE = re.compile(r"([<>]=?|==)\s*(-?\d+(?:\.\d+)?)")
_WORD_OPERATORS = [
    (r"reaches|rises to|at least|above", ">="),
    (r"drops below|falls below|at most|under", "<="),
    (r"exceeds|greater than", ">"),
    (r"less than", "<"),
    (r"equals|equal to", "=="),
]
_TIMER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-?\s*seconds?|sec|s)\b", re.IGNORECASE)


def _longest_matching_device(text: str, device_names: set[str]) -> str | None:
    """Return the longest equipment name that prefixes *text* (case-insensitive)."""
    lowered = text.lower()
    best: str | None = None
    for name in device_names:
        if lowered.startswith(name.lower()):
            if best is None or len(name) > len(best):
                best = name
    return best


def _parse_colour_entry(item: Any, device_names: set[str]) -> dict[str, Any]:
    """Normalize a colour-state entry (dict or 'device: colour' string) to a dict.

    A compact E2B-style mapping ``{device: colour}`` (a single-entry dict
    without the schema's own ``device`` key) is rewritten to the shared
    ``device: colour`` text form so the parser below extracts the colour
    and any trailing description deterministically.
    """
    if isinstance(item, dict) and "device" not in item and len(item) == 1:
        (device, value), = item.items()
        if value is not None:
            item = f"{device}: {value}"
    if isinstance(item, dict):
        return item
    text = str(item).strip()
    device = _longest_matching_device(text, device_names)
    if device is None:
        raise ValueError(f"Cannot parse colour-state entry {item!r}: no matching device prefix")
    rest = text[len(device):].lstrip(":-→> ")
    lowered = rest.lower()
    colour = next((c for c in _COLOURS if c in lowered), None)
    if colour is None:
        raise ValueError(f"Cannot parse colour/state from {item!r}")
    index = lowered.find(colour)
    description = (rest[:index] + rest[index + len(colour):]).strip(" :-\t")
    return {"device": device, "colour": colour, "description": description}


def _parse_analogue_entry(item: Any, device_names: set[str]) -> dict[str, Any]:
    """Normalize an analogue entry (dict or 'device >= 80' string) to a dict.

    A compact E2B-style mapping ``{device: ">= 80"}`` (a single-entry dict
    without the schema's own ``device`` key) is rewritten to the shared
    ``device ...`` text form so operator/threshold extraction stays in one
    place.
    """
    if isinstance(item, dict) and "device" not in item and len(item) == 1:
        (device, value), = item.items()
        if value is not None:
            item = f"{device}: {value}"
    if isinstance(item, dict):
        return item
    text = str(item).strip()
    device = _longest_matching_device(text, device_names)
    if device is None:
        raise ValueError(f"Cannot parse analogue entry {item!r}: no matching device prefix")
    rest = text[len(device):].lstrip(":- ")
    match = _ANALOGUE_RE.search(rest)
    if match:
        operator = match.group(1)
        threshold = float(match.group(2))
    else:
        operator = None
        threshold = None
        for pattern, word_op in _WORD_OPERATORS:
            word_match = re.search(pattern, rest, re.IGNORECASE)
            if word_match:
                number_match = re.search(r"-?\d+(?:\.\d+)?", rest[word_match.end():])
                if number_match:
                    operator = word_op
                    threshold = float(number_match.group(0))
                    match = word_match
                break
        if operator is None:
            raise ValueError(f"Cannot parse operator/threshold from {item!r}")
    description = (rest[:match.start()] + " " + rest[match.end():]).strip()
    return {
        "device": device,
        "operator": operator,
        "threshold": threshold,
        "description": description,
    }


def _parse_timer_entry(item: Any) -> dict[str, Any]:
    """Normalize a timer entry (dict, '5s ...', or bare '5') to a dict.

    A compact single-entry mapping ``{description: duration}`` (without the
    schema's own ``duration_seconds`` key) is rewritten to the shared
    ``description: duration`` text form.
    """
    if isinstance(item, dict) and "duration_seconds" not in item and len(item) == 1:
        (key, value), = item.items()
        if value is not None:
            item = f"{key}: {value}"
    if isinstance(item, dict):
        return item
    text = str(item).strip()
    match = _TIMER_RE.search(text)
    if match:
        duration = float(match.group(1))
        description = (text[:match.start()] + " " + text[match.end():]).strip(" :-\t")
    else:
        bare = re.fullmatch(r"(\d+(?:\.\d+)?)", text)
        if bare is None:
            raise ValueError(f"Cannot parse timer duration from {item!r}")
        duration = float(bare.group(1))
        description = ""
    return {
        "duration_seconds": duration,
        "description": " ".join(description.split()) or "timer delay",
    }


def _normalize_intent_args(
    args: dict[str, Any], device_names: set[str], label: str
) -> dict[str, Any]:
    """Normalize backend-flattened tool args into schema-shaped structures.

    Some backends flatten nested models in tool calls instead of returning
    lists of objects; the loose shapes accepted per list field are:
    - a single string, e.g. ``colour_states='SL-301: green'``
    - a single dict, e.g. ``colour_states={'device': 'SL-301', 'colour': 'green'}``
    - a compact keyed mapping, e.g. ``colour_states={'SL-301': 'green'}``
      (keys are equipment/device names; seen from E2B-style backends)
    Python owns the final structure: loose entries are parsed deterministically
    and still pass through Pydantic validation and grounding checks.

    Intents are graded by semantic load: analogue and timer entries are
    code-bearing (they render to REAL comparisons and TON blocks), so any
    parsing failure aborts the draft. Colour-state entries are
    comment-bearing (they only feed review comments), so an unparseable
    entry degrades to a state note instead of aborting; grounding failures
    (no matching device) still abort.
    """
    normalized = dict(args)
    for key, parser in (
        ("analogue_conditions", lambda item: _parse_analogue_entry(item, device_names)),
        ("timers", _parse_timer_entry),
    ):
        items = normalized.get(key)
        if items is None:
            continue
        if isinstance(items, str):
            items = [items]
        elif isinstance(items, dict):
            # Single loose entry returned as a mapping; the per-key parser
            # normalizes it whether it is schema-shaped or a compact keyed
            # mapping.
            items = [items]
        if not isinstance(items, list):
            raise ValueError(f"Invalid {key} for {label}: {items!r}")
        normalized[key] = [parser(item) for item in items]

    colour_items = normalized.get("colour_states")
    if colour_items is not None:
        if isinstance(colour_items, str):
            colour_items = [colour_items]
        elif isinstance(colour_items, dict):
            colour_items = [colour_items]
        if not isinstance(colour_items, list):
            raise ValueError(f"Invalid colour_states for {label}: {colour_items!r}")
        parsed_colours: list[dict[str, Any]] = []
        degraded_notes: list[str] = []
        for item in colour_items:
            try:
                parsed_colours.append(_parse_colour_entry(item, device_names))
            except ValueError as exc:
                if "no matching device prefix" in str(exc):
                    raise  # grounding failure is never downgraded
                degraded_notes.append(
                    f"Unparseable colour-state entry {item!r} kept as a note: {exc}"
                )
        normalized["colour_states"] = parsed_colours
        if degraded_notes:
            notes = normalized.get("state_notes") or []
            if isinstance(notes, str):
                notes = [notes]
            normalized["state_notes"] = [*notes, *degraded_notes]

    notes = normalized.get("state_notes")
    if isinstance(notes, str):
        normalized["state_notes"] = [notes]
    return normalized


def _ground_intent_device(device: str, device_names: set[str], field: str, label: str) -> None:
    if device not in device_names:
        raise ValueError(
            f"Grounding check failed for {label}: {field}={device!r} is not in the AST device list"
        )


def _validate_sequence_intent(
    args: dict[str, Any],
    device_names: set[str],
    step_id: int,
) -> SequenceCodeIntent:
    label = f"sequence step {step_id}"
    try:
        intent = SequenceCodeIntent.model_validate(
            _normalize_intent_args(args, device_names, label)
        )
    except ValidationError as exc:
        raise ValueError(f"Invalid structured intent for {label}: {exc}") from exc
    for cond in intent.analogue_conditions:
        _ground_intent_device(cond.device, device_names, "analogue_conditions.device", label)
    for state in intent.colour_states:
        _ground_intent_device(state.device, device_names, "colour_states.device", label)
    return intent


def _validate_interlock_intent(
    args: dict[str, Any],
    device_names: set[str],
    index: int,
) -> InterlockCodeIntent:
    label = f"interlock {index}"
    try:
        intent = InterlockCodeIntent.model_validate(
            _normalize_intent_args(args, device_names, label)
        )
    except ValidationError as exc:
        raise ValueError(f"Invalid structured intent for {label}: {exc}") from exc
    for state in intent.colour_states:
        _ground_intent_device(state.device, device_names, "colour_states.device", label)
    return intent


# ---------------------------------------------------------------------------
# Intent collection
# ---------------------------------------------------------------------------

_SEQUENCE_INTENT_PROMPT = """\
Call suggest_sequence_intent exactly once for this control-sequence step.
Return structured code intent ONLY for complex logic that a plain BOOL
assignment cannot represent: timers/delays, analogue threshold conditions,
colour/state changes, or sequence-state notes. Return empty lists when the
step is fully covered by a plain BOOL draft. Never invent devices:
colour_states and analogue_conditions may only name equipment from the
supplied list. Every analogue_conditions entry MUST include a comparison
operator (>=, <=, >, <, ==) and a bare numeric threshold without unit
symbols (e.g. "tank level sensor >= 80").

Step id: {step_id}
Action: {action}
Condition: {condition}
Target device: {target}
Equipment list: {equipment}
"""

_INTERLOCK_INTENT_PROMPT = """\
Call suggest_interlock_intent exactly once for this safety interlock.
Return structured code intent ONLY for complex forced logic that a plain BOOL
draft cannot represent (colour/state changes, logic notes). Return empty lists
when fully covered. Never invent devices: colour_states may only name
equipment from the supplied list.

Interlock: {node_id}
Condition: {condition}
Forced action: {forced_action}
Affected devices: {affected}
Equipment list: {equipment}
"""


def _collect_intents(ast: Any, backend: str) -> tuple[dict[int, SequenceCodeIntent], dict[int, InterlockCodeIntent]]:
    device_names = {device.name for device in ast.devices}
    equipment_context = json.dumps([device.name for device in ast.devices])
    llm = build_llm(backend)

    sequence_intents: dict[int, SequenceCodeIntent] = {}
    for step in ast.sequence:
        prompt = _SEQUENCE_INTENT_PROMPT.format(
            step_id=step.step_id,
            action=step.action,
            condition=step.condition or "None",
            target=step.target_device or "None",
            equipment=equipment_context,
        )
        args = _invoke_intent(
            llm,
            suggest_sequence_intent,
            prompt,
            "suggest_sequence_intent",
            f"sequence step {step.step_id}",
            backend,
        )
        sequence_intents[step.step_id] = _validate_sequence_intent(
            args, device_names, step.step_id
        )

    interlock_intents: dict[int, InterlockCodeIntent] = {}
    for index, interlock in enumerate(ast.interlocks, start=1):
        prompt = _INTERLOCK_INTENT_PROMPT.format(
            node_id=interlock.node_id,
            condition=interlock.condition,
            forced_action=interlock.forced_action,
            affected=json.dumps(interlock.affected_devices),
            equipment=equipment_context,
        )
        args = _invoke_intent(
            llm,
            suggest_interlock_intent,
            prompt,
            "suggest_interlock_intent",
            f"interlock {index}",
            backend,
        )
        interlock_intents[index] = _validate_interlock_intent(
            args, device_names, index
        )

    return sequence_intents, interlock_intents


# ---------------------------------------------------------------------------
# Deterministic rendering (Python-owned final code)
# ---------------------------------------------------------------------------

def _build_hybrid_sequence_block(
    step: Any,
    intent: SequenceCodeIntent,
    device_names: list[str],
    device_vars: dict[str, str],
    ton_declarations: list[str],
) -> STBlock:
    lines = [
        f"// {step.node_id}",
        f"// Source step: {step.source_step_id}",
        f"// Source scenario: {_clean_comment_text(step.source_scenario)}",
        f"// Action: {_clean_comment_text(step.action)}",
        "// Draft logic: hybrid renderer (LLM suggested structured intent; Python rendered final code).",
    ]

    trigger_devices = _find_mentioned_devices(step.condition, device_names)
    target_device = step.target_device if step.target_device in device_vars else None
    target_value = _bool_literal(_sequence_target_value(step.action))

    if not trigger_devices and not intent.analogue_conditions:
        # Analogue conditions implement the condition mapping themselves, so the
        # baseline TODO is suppressed there; the timer path keeps it because a
        # TON with IN := TRUE still needs the real start condition wired by review.
        lines.append(
            f"// TODO: Map source condition to ST logic: {_clean_comment_text(step.condition)}"
        )
    if target_device is None:
        lines.append(
            f"// TODO: Map target device for action: {_clean_comment_text(step.action)}"
        )

    if target_device is not None:
        if intent.timers:
            # Timer-gated assignment: LLM supplies the duration, Python renders
            # the TON function-block call and the gated assignment.
            for index, timer in enumerate(intent.timers, start=1):
                ton_name = f"TON_{step.step_id}_{index}"
                ton_declarations.append(
                    f"{ton_name} : TON; // hybrid timer: {_clean_comment_text(timer.description)}"
                )
                condition_expr = (
                    _render_condition_expression(trigger_devices, device_vars)
                    if trigger_devices
                    else "TRUE"
                )
                lines.append("")
                lines.append(
                    f"// Hybrid timer intent (LLM-suggested, Python-rendered): "
                    f"{_clean_comment_text(timer.description)}"
                )
                lines.append(
                    f"{ton_name}(IN := {condition_expr}, PT := T#{timer.duration_seconds:g}s);"
                )
                lines.append(f"IF {ton_name}.Q THEN")
                lines.append(f"    {device_vars[target_device]} := {target_value};")
                lines.append("END_IF;")
        elif intent.analogue_conditions:
            # Analogue-gated assignment: LLM supplies the threshold, Python
            # renders the REAL comparison (the device is declared REAL).
            for cond in intent.analogue_conditions:
                analogue_var = device_vars.get(cond.device)
                if not analogue_var:
                    continue
                lines.append("")
                lines.append(
                    f"// Hybrid analogue condition (LLM-suggested, Python-rendered): "
                    f"{analogue_var} {cond.operator} {cond.threshold:g}"
                    + (f" -- {_clean_comment_text(cond.description)}" if cond.description else "")
                )
                lines.append(
                    f"IF {analogue_var} {cond.operator} {cond.threshold:g} THEN"
                )
                lines.append(f"    {device_vars[target_device]} := {target_value};")
                lines.append("END_IF;")
        elif trigger_devices:
            # Plain BOOL assignment (deterministic baseline path).
            condition_expr = _render_condition_expression(trigger_devices, device_vars)
            lines.append(f"IF {condition_expr} THEN")
            lines.append(f"    {device_vars[target_device]} := {target_value};")
            lines.append("END_IF;")

    for state in intent.colour_states:
        if state.device in device_vars:
            lines.append("")
            detail = f" ({_clean_comment_text(state.description)})" if state.description else ""
            lines.append(
                f"// Hybrid colour-state intent (LLM-suggested): {state.device} -> {state.colour}{detail}"
            )
            lines.append(
                "// TODO: full colour modelling needs an enumerated colour variable; "
                "the BOOL draft above keeps the assignment."
            )

    for note in intent.state_notes:
        lines.append(f"// State logic: {_clean_comment_text(note)}")

    return STBlock(
        block_id=step.node_id,
        title=f"Sequence Step {step.step_id}",
        code="\n".join(lines),
        source_ast_node_id=step.node_id,
        source_step_id=step.source_step_id,
        source_scenario=step.source_scenario,
    )


def _build_hybrid_interlock_block(
    interlock: Any,
    intent: InterlockCodeIntent,
    device_names: list[str],
    device_vars: dict[str, str],
) -> STBlock:
    lines = [
        f"// {interlock.node_id}",
        f"// Source interlock condition: {_clean_comment_text(interlock.source_interlock_condition)}",
        f"// Source scenario: {_clean_comment_text(interlock.source_scenario)}",
        f"// Forced action: {_clean_comment_text(interlock.forced_action)}",
        f"// Priority: {interlock.priority}",
        "// Draft logic: hybrid renderer (LLM suggested structured intent; Python rendered final code).",
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

    for state in intent.colour_states:
        if state.device in device_vars:
            lines.append("")
            detail = f" ({_clean_comment_text(state.description)})" if state.description else ""
            lines.append(
                f"// Hybrid colour-state intent (LLM-suggested): {state.device} -> {state.colour}{detail}"
            )
            lines.append(
                "// TODO: full colour modelling needs an enumerated colour variable; "
                "the BOOL draft above keeps the assignment."
            )

    for note in intent.state_notes:
        lines.append(f"// State logic: {_clean_comment_text(note)}")

    return STBlock(
        block_id=interlock.node_id,
        title=f"Safety Interlock {interlock.node_id}",
        code="\n".join(lines),
        source_ast_node_id=interlock.node_id,
        source_scenario=interlock.source_scenario,
        source_interlock_condition=interlock.source_interlock_condition,
    )


def _build_device_var_map(ast: Any) -> dict[str, str]:
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


def build_hybrid_st_program(
    ast: Any,
    source_ast_file: Path,
    backend: str,
) -> STProgram:
    """Collect LLM code intent and assemble the hybrid STProgram contract."""
    sequence_intents, interlock_intents = _collect_intents(ast, backend)

    device_vars = _build_device_var_map(ast)
    device_names = [device.name for device in ast.devices]
    analogue_devices = {
        cond.device
        for intent in sequence_intents.values()
        for cond in intent.analogue_conditions
    }

    program_name = sanitize_var_name(ast.feature_title) or sanitize_var_name(source_ast_file.stem)

    declarations: list[str] = []
    for device in ast.devices:
        var_name = device_vars[device.name]
        source_name = _clean_comment_text(device.source_equipment or device.name)
        if device.name in analogue_devices:
            declarations.append(
                f"{var_name} : REAL; // source equipment: {source_name} (hybrid: analogue)"
            )
        else:
            declarations.append(f"{var_name} : BOOL; // source equipment: {source_name}")

    ton_declarations: list[str] = []
    blocks: list[STBlock] = []
    for step in ast.sequence:
        intent = sequence_intents.get(step.step_id, _EMPTY_SEQUENCE_INTENT)
        blocks.append(
            _build_hybrid_sequence_block(
                step, intent, device_names, device_vars, ton_declarations
            )
        )
    for index, interlock in enumerate(ast.interlocks, start=1):
        intent = interlock_intents.get(index, _EMPTY_INTERLOCK_INTENT)
        blocks.append(
            _build_hybrid_interlock_block(
                interlock, intent, device_names, device_vars
            )
        )

    declarations.extend(ton_declarations)

    return STProgram(
        program_name=program_name,
        variables=declarations,
        blocks=blocks,
        source_ast_file=str(source_ast_file.resolve()),
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def resolve_output_path(ast_path: Path, backend: str) -> Path:
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_OUTPUT_DIR / f"{ast_path.stem}_st_{APPROACH_NAME}_{backend}.st"


def load_ast(path: Path) -> Any:
    """Load and validate a PLC_AST JSON file (wraps st_gen errors cleanly)."""
    try:
        return _load_ast(path)
    except ValidationError as exc:
        raise ValueError(f"Invalid PLC_AST JSON: {path}\n{exc}") from exc
    except OSError as exc:
        raise FileNotFoundError(f"AST file not found: {path}") from exc


def write_st_file(ast_path: Path, backend: str) -> tuple[Path, STProgram]:
    if backend == "api" and not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "The api backend requires GEMINI_API_KEY to be set. No output was generated."
        )
    ast = load_ast(ast_path)
    program = build_hybrid_st_program(ast, ast_path, backend)
    output_path = resolve_output_path(ast_path, backend)
    output_path.write_text(render_st_program(program), encoding="utf-8")
    return output_path, program


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a hybrid Structured Text draft from PLC_AST JSON (E2S4T6)."
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
        output_path, program = write_st_file(args.ast_file, args.backend)
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

    print(
        f"Generated hybrid ST draft ({args.backend}): {output_path} "
        f"({len(program.variables)} variables, {len(program.blocks)} ST blocks)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
