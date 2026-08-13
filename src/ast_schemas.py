"""Structured-output schema for the AST intermediate representation (E2S3).

These Pydantic models define the target structure for LangChain's
``.with_structured_output()`` during the AST-generation stage. As with
``src/schemas.py`` and ``src/gherkin_schemas.py``, the ``Field`` descriptions
double as prompt instructions: they tell the LLM exactly how to fold the two
upstream artifacts into a single, code-ready intermediate representation.

The AST is the connective tissue between the two prior Epic-2 stages:

* E2S1 produces a :class:`~src.schemas.SystemRequirement` (equipment, control
  sequences, safety interlocks) from a free-form narrative.
* E2S2 produces a Gherkin ``.feature`` file
  (:class:`~src.gherkin_schemas.GherkinFeature`) of Given/When/Then scenarios.

:class:`PLC_AST` merges both into one graph of :class:`DeviceNode`,
:class:`SequenceStepNode`, and :class:`InterlockNode` objects. Every node
carries verbatim ``source_*`` traceability fields back to its origin item, and
each sequence/interlock node additionally links to the Gherkin scenario it
corresponds to -- the key cross-E2S1/E2S2 traceability link that downstream
IEC 61131-3 code generation (E2S4) will consume.

Deterministic vs. LLM-owned fields: ``node_id`` values and the two
``PLC_AST.source_*_file`` path fields are stamped by the driving script after
the LLM call, never trusted from the model -- the same discipline as
``source_step_id`` in :mod:`src.gherkin_schemas`. They live in the schema only
so Pydantic validates the fully-assembled object.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class DeviceNode(BaseModel):
    """One physical/logical device, derived from a SystemRequirement Equipment."""

    node_id: str = Field(
        description=(
            "A deterministic identifier for this device node, following the "
            "pattern 'DEV-<name>' where <name> is the equipment's name, "
            "e.g. 'DEV-EV-101', 'DEV-SL-301'."
        )
    )
    name: str = Field(
        description=(
            "The device name copied verbatim from the source Equipment.name, "
            "e.g. 'EV-101', 'SL-301', 'start pushbutton'. Do NOT rename or "
            "normalize."
        )
    )
    device_type: str = Field(
        description=(
            "The device category copied verbatim from the source "
            "Equipment.type, e.g. 'solenoid valve', 'signal light', "
            "'push button'."
        )
    )
    source_equipment: str = Field(
        description=(
            "Traceability: the original Equipment.name this node was created "
            "from, copied verbatim (e.g. 'EV-101'). Normally identical to "
            "'name'; retained as an explicit provenance link."
        )
    )


class SequenceStepNode(BaseModel):
    """One normal-operation step, derived from a ControlSequence step."""

    node_id: str = Field(
        description=(
            "A deterministic identifier for this sequence step node, following "
            "the pattern 'SEQ-<step_id>', e.g. 'SEQ-1', 'SEQ-2'."
        )
    )
    step_id: int = Field(
        description=(
            "The chronological order of this step, copied from the source "
            "ControlSequence.step_id (e.g. 1, 2, 3)."
        )
    )
    action: str = Field(
        description=(
            "The source ControlSequence.description copied VERBATIM. Do NOT "
            "paraphrase, summarize, or extract verb phrases -- reproduce the "
            "original sentence exactly, e.g. 'When the operator presses the "
            "start pushbutton, SL-301 must turn green.'"
        )
    )
    target_device: Optional[str] = Field(
        default=None,
        description=(
            "The name of the equipment (from the equipment_list) that this "
            "step primarily acts on, e.g. 'SL-301'. Set to None if no single "
            "equipment name from the list is clearly identifiable in the step."
        ),
    )
    condition: Optional[str] = Field(
        default=None,
        description=(
            "The triggering condition for this step if one is explicitly "
            "stated, e.g. 'the operator presses the start pushbutton'. Set to "
            "None if the step states no distinct condition."
        ),
    )
    source_step_id: int = Field(
        description=(
            "Traceability: the source ControlSequence.step_id this node was "
            "created from (e.g. 1). Normally identical to 'step_id'; retained "
            "as an explicit provenance link."
        )
    )
    source_scenario: Optional[str] = Field(
        default=None,
        description=(
            "Traceability: the GherkinScenario.name whose 'source_step_id' "
            "matches this step's step_id, copied verbatim (e.g. 'Operator "
            "starts the system'). Set to None if no matching scenario is found "
            "in the provided .feature text. This is the cross-E2S1/E2S2 link."
        ),
    )


class InterlockNode(BaseModel):
    """One safety interlock, derived from a SystemRequirement Interlock."""

    node_id: str = Field(
        description=(
            "A deterministic identifier for this interlock node, following the "
            "pattern 'ILK-<N>' where N is a 1-based counter, e.g. 'ILK-1', "
            "'ILK-2'."
        )
    )
    condition: str = Field(
        description=(
            "The triggering condition copied VERBATIM from the source "
            "Interlock.condition, e.g. 'Emergency Stop button is pressed'. Do "
            "NOT paraphrase."
        )
    )
    forced_action: str = Field(
        description=(
            "The forced safety response copied VERBATIM from the source "
            "Interlock.action, e.g. 'SL-301 must immediately switch to red'. "
            "Do NOT paraphrase."
        )
    )
    affected_devices: List[str] = Field(
        description=(
            "The names of the devices mentioned in this interlock's condition "
            "or forced_action text, e.g. ['SL-301']. Every entry MUST be an "
            "equipment name that exists in the equipment_list -- never invent "
            "a device name. Use an empty list if none from the list appear."
        )
    )
    priority: int = Field(
        default=1,
        description=(
            "The interlock priority for arbitration between competing "
            "interlocks; higher means more urgent. Defaults to 1 and is left "
            "as 1 for Approach A (no priority inference is attempted here)."
        ),
    )
    source_interlock_condition: str = Field(
        description=(
            "Traceability: the source Interlock.condition text copied verbatim "
            "(e.g. 'Emergency Stop button is pressed'). Normally identical to "
            "'condition'; retained as an explicit provenance link."
        )
    )
    source_scenario: Optional[str] = Field(
        default=None,
        description=(
            "Traceability: the GherkinScenario.name whose "
            "'source_interlock_condition' matches this interlock's condition, "
            "copied verbatim (e.g. 'Emergency stop activates signal light'). "
            "Set to None if no matching scenario is found in the provided "
            ".feature text. This is the cross-E2S1/E2S2 link."
        ),
    )


class PLC_AST(BaseModel):
    """The complete AST intermediate representation for one requirement.

    Merges the E2S1 :class:`~src.schemas.SystemRequirement` and the E2S2
    Gherkin feature into a single code-ready graph. The two ``source_*_file``
    fields are stamped deterministically by the driving script after the LLM
    call -- the model is instructed to leave them empty -- so they are always
    trustworthy provenance paths rather than model output.
    """

    feature_title: str = Field(
        description=(
            "The feature title taken from the Gherkin feature's 'Feature:' "
            "line, e.g. 'Signal light control and safety interlocks'."
        )
    )
    devices: List[DeviceNode] = Field(
        description=(
            "One DeviceNode per Equipment in the source equipment_list, in the "
            "same order. Do NOT invent devices not present in the source."
        )
    )
    sequence: List[SequenceStepNode] = Field(
        description=(
            "One SequenceStepNode per ControlSequence step in the source, "
            "ordered by step_id. Do NOT invent steps not present in the source."
        )
    )
    interlocks: List[InterlockNode] = Field(
        description=(
            "One InterlockNode per Interlock in the source. Use an empty list "
            "if the source has no interlocks. Do NOT invent interlocks."
        )
    )
    source_requirement_file: str = Field(
        default="",
        description=(
            "Traceability: the path of the parsed requirement JSON this AST "
            "was built from. Leave as an empty string -- the driving script "
            "overwrites it with the resolved absolute path after the LLM call."
        ),
    )
    source_gherkin_file: str = Field(
        default="",
        description=(
            "Traceability: the path of the Gherkin .feature file this AST was "
            "built from. Leave as an empty string -- the driving script "
            "overwrites it with the resolved absolute path after the LLM call."
        ),
    )
