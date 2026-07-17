"""Generate a PLC AST with RPC/function-calling semantics (E2S3, Approach C).

The LLM never receives ``PLC_AST`` as its output schema.  It is bound to the
deterministic builder functions in :mod:`src.ast_builders` and returns one
structured tool call per sequence step and interlock.  Python supplies the
authoritative text, validates grounding, invokes the builder, and assembles
the final :class:`~src.ast_schemas.PLC_AST`.

Usage::

    python -m src.ast_gen_C \
        data/parsed/signal_light_demo_parsed_api.json \
        data/gherkin/signal_light_demo_api.feature --backend api
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

try:
    from src.ast_builders import (
        assemble_plc_ast,
        build_device_node,
        build_interlock_node,
        build_sequence_step_node,
    )
    from src.req_parser import build_llm
    from src.schemas import SystemRequirement
except ImportError:
    from ast_builders import (
        assemble_plc_ast,
        build_device_node,
        build_interlock_node,
        build_sequence_step_node,
    )
    from req_parser import build_llm
    from schemas import SystemRequirement


def load_requirement(path: Path) -> SystemRequirement:
    if not path.is_file():
        raise FileNotFoundError(f"Requirement file not found: {path}")
    try:
        return SystemRequirement.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValueError(f"Invalid SystemRequirement JSON: {path}\n{exc}") from exc


def load_gherkin(path: Path) -> tuple[str, list[dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Gherkin file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Gherkin file is empty: {path}")
    try:
        parsed = Parser().parse(TokenScanner(text))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to parse Gherkin file: {path}\n{exc}") from exc
    feature = parsed.get("feature", {})
    scenarios = [
        child["scenario"]
        for child in feature.get("children", [])
        if "scenario" in child
    ]
    return feature.get("name", ""), scenarios


def _scenario_context(scenarios: list[dict[str, Any]]) -> str:
    return json.dumps(
        [
            {"name": s["name"], "steps": [step["text"] for step in s.get("steps", [])]}
            for s in scenarios
        ],
        indent=2,
    )


def _tool_call(message: Any, expected_name: str, label: str) -> dict[str, Any]:
    """Extract exactly one expected tool call from an AIMessage."""
    calls = getattr(message, "tool_calls", None) or []
    if not calls and getattr(message, "additional_kwargs", None):
        calls = message.additional_kwargs.get("tool_calls", [])
    matching = [call for call in calls if (call.get("name") or call.get("function", {}).get("name")) == expected_name]
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


def _invoke_tool(
    llm: Any,
    tool: Any,
    prompt: str,
    expected_name: str,
    label: str,
    backend: str,
) -> dict[str, Any]:
    """Ask for one tool call and return its structured arguments."""
    try:
        # LM Studio only accepts string tool_choice values such as
        # "required". Since exactly one tool is bound per call, this still
        # forces the intended builder. _tool_call() validates the returned name.
        tool_choice = "required" if backend == "local" else expected_name
        bound = llm.bind_tools([tool], tool_choice=tool_choice)
        message = bound.invoke(prompt)
        return _tool_call(message, expected_name, label)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Function call failed for {label}: {exc}") from exc


def _validate_choice(value: str | None, allowed: set[str], field: str, label: str) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"Grounding check failed for {label}: {field}={value!r} is not in equipment_list")


def _text_contains_name(text: str, name: str) -> bool:
    """Return whether *name* occurs in *text* without an alphanumeric overmatch.

    The lookarounds prevent names such as ``EV-101`` from matching inside
    ``EV-1012`` or ``NEV-101``, while allowing punctuation and whitespace around
    equipment names.
    """
    escaped = re.escape(name.lower())
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text.lower()))


def _find_mentioned_devices(text: str, equipment_names: list[str]) -> list[str]:
    """Return all equipment names mentioned in *text*, in equipment-list order.

    Approach C defines an interlock's ``affected_devices`` as every equipment
    name explicitly mentioned in its condition or forced action.  This
    deterministic completion is independent of the LLM's interpretation.
    """
    return [name for name in equipment_names if _text_contains_name(text, name)]


def build_ast(req_path: Path, feature_path: Path, backend: str):
    requirement = load_requirement(req_path)
    feature_title, scenarios = load_gherkin(feature_path)
    scenario_names = {scenario["name"] for scenario in scenarios}
    equipment_names = [equipment.name for equipment in requirement.equipment_list]
    equipment_set = set(equipment_names)
    devices = [
        build_device_node(equipment.name, equipment.type)
        for equipment in requirement.equipment_list
    ]
    llm = build_llm(backend)
    context = _scenario_context(scenarios)
    equipment_context = json.dumps(equipment_names)
    sequence = []
    for source in requirement.sequences:
        prompt = (
            "Call build_sequence_step_node exactly once. You are selecting only semantic mappings "
            "for one authoritative control-sequence item. Preserve the supplied action and step_id "
            "exactly. target_device must be null or one equipment name. condition should be a concise "
            "trigger extracted from the source, or null. source_scenario must be null or exactly one "
            "scenario name from the supplied list. Do not invent values.\n"
            f"step_id: {source.step_id}\naction: {source.description!r}\n"
            f"equipment_list: {equipment_context}\nscenarios: {context}"
        )
        args = _invoke_tool(
            llm,
            build_sequence_step_node,
            prompt,
            "build_sequence_step_node",
            f"sequence step {source.step_id}",
            backend,
        )
        # Local models may paraphrase tool arguments, so Approach C treats the
        # model output as semantic suggestions only. Python overwrites
        # authoritative source fields before deterministic AST builders run.
        args["step_id"] = source.step_id
        args["action"] = source.description
        if "source_step_id" in args:
            args["source_step_id"] = source.step_id
        _validate_choice(args.get("target_device"), equipment_set, "target_device", f"sequence step {source.step_id}")
        scenario = args.get("source_scenario")
        if scenario is not None and scenario not in scenario_names:
            raise ValueError(f"Grounding check failed for sequence step {source.step_id}: source_scenario={scenario!r} is not a real Gherkin scenario")
        args.pop("source_step_id", None)
        sequence.append(build_sequence_step_node(**args))

    interlocks = []
    for index, source in enumerate(requirement.interlocks, start=1):
        prompt = (
            "Call build_interlock_node exactly once. Preserve condition and forced_action exactly as "
            "supplied. affected_devices may contain only names from equipment_list and should include "
            "all equipment explicitly referenced by the condition/action. source_scenario must be null "
            "or exactly one scenario name from the supplied list. Keep priority 1.\n"
            f"index: {index}\ncondition: {source.condition!r}\nforced_action: {source.action!r}\n"
            f"equipment_list: {equipment_context}\nscenarios: {context}"
        )
        args = _invoke_tool(
            llm,
            build_interlock_node,
            prompt,
            "build_interlock_node",
            f"interlock {index}",
            backend,
        )
        affected = args.get("affected_devices")
        if affected is not None and (
            not isinstance(affected, list) or any(device not in equipment_set for device in affected)
        ):
            raise ValueError(f"Grounding check failed for interlock {index}: affected_devices={affected!r} is not a subset of equipment_list")
        args["index"] = index
        args["condition"] = source.condition
        args["forced_action"] = source.action
        args["priority"] = 1
        # Complete affected_devices deterministically from all equipment named
        # in the authoritative condition or forced-action text.  The LLM still
        # performs semantic mapping through the tool call, but cannot omit a
        # referenced device or alter the equipment-list order here.
        mentioned_devices = _find_mentioned_devices(
            f"{source.condition} {source.action}", equipment_names
        )
        args["affected_devices"] = mentioned_devices
        scenario = args.get("source_scenario")
        if scenario is not None and scenario not in scenario_names:
            raise ValueError(f"Grounding check failed for interlock {index}: source_scenario={scenario!r} is not a real Gherkin scenario")
        interlocks.append(build_interlock_node(**args))

    return assemble_plc_ast(
        feature_title,
        devices,
        sequence,
        interlocks,
        str(req_path.resolve()),
        str(feature_path.resolve()),
    )


def resolve_output_path(requirement_path: Path, backend: str) -> Path:
    name = requirement_path.stem
    if "_parsed_" not in name:
        raise ValueError(f"Requirement filename must follow '<stem>_parsed_<backend>.json': {requirement_path.name}")
    stem = name.rsplit("_parsed_", 1)[0]
    output_dir = requirement_path.resolve().parent.parent / "ast"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{stem}_{backend}_AST_C.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a PLC AST using RPC/function-calling builder tools (E2S3 Approach C).")
    parser.add_argument("requirement_file", type=Path)
    parser.add_argument("gherkin_file", type=Path)
    parser.add_argument("--backend", choices=["local", "api"], default="local")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = build_ast(args.requirement_file, args.gherkin_file, args.backend)
        output_path = resolve_output_path(args.requirement_file, args.backend)
        output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"❌ Approach C failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(
        f"✅ AST C generated: {len(result.devices)} devices, {len(result.sequence)} sequence steps, "
        f"{len(result.interlocks)} interlocks. Saved to {output_path}."
    )


if __name__ == "__main__":
    main()
