"""Deterministic, validated builders used by E2S3 Approach C.

The functions in this module are intentionally small and side-effect free.
Approach C exposes the sequence and interlock builders as LLM tools, but the
authoritative source values and the final Pydantic validation remain in
Python.  The model therefore chooses semantic mappings without owning the
shape or provenance of the complete AST.
"""

from __future__ import annotations

from typing import Optional, Sequence

try:
    from src.ast_schemas import DeviceNode, InterlockNode, PLC_AST, SequenceStepNode
except ImportError:
    from ast_schemas import DeviceNode, InterlockNode, PLC_AST, SequenceStepNode


def build_device_node(name: str, device_type: str) -> DeviceNode:
    """Build one device node from one authoritative requirement equipment."""
    return DeviceNode(
        node_id=f"DEV-{name}",
        name=name,
        device_type=device_type,
        source_equipment=name,
    )


def build_sequence_step_node(
    step_id: int,
    action: str,
    target_device: Optional[str] = None,
    condition: Optional[str] = None,
    source_scenario: Optional[str] = None,
) -> SequenceStepNode:
    """Build and validate a sequence node from structured tool arguments."""
    return SequenceStepNode(
        node_id=f"SEQ-{step_id}",
        step_id=step_id,
        action=action,
        target_device=target_device,
        condition=condition,
        source_step_id=step_id,
        source_scenario=source_scenario,
    )


def build_interlock_node(
    index: int,
    condition: str,
    forced_action: str,
    affected_devices: Sequence[str],
    source_scenario: Optional[str] = None,
    priority: int = 1,
) -> InterlockNode:
    """Build and validate an interlock node from structured tool arguments."""
    return InterlockNode(
        node_id=f"ILK-{index}",
        condition=condition,
        forced_action=forced_action,
        affected_devices=list(affected_devices),
        priority=priority,
        source_interlock_condition=condition,
        source_scenario=source_scenario,
    )


def assemble_plc_ast(
    feature_title: str,
    devices: Sequence[DeviceNode],
    sequence: Sequence[SequenceStepNode],
    interlocks: Sequence[InterlockNode],
    source_requirement_file: str,
    source_gherkin_file: str,
) -> PLC_AST:
    """Assemble and revalidate the complete AST after all tool calls finish."""
    return PLC_AST(
        feature_title=feature_title,
        devices=list(devices),
        sequence=list(sequence),
        interlocks=list(interlocks),
        source_requirement_file=source_requirement_file,
        source_gherkin_file=source_gherkin_file,
    )
