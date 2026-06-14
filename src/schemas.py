"""Structured-output schemas for natural-language requirement ingestion (E2S1).

These Pydantic models define the target structure for LangChain's
``.with_structured_output()``. The ``Field`` descriptions double as prompt
instructions: they tell the LLM exactly what to extract from chaotic,
free-form PLC control narratives and how to normalize it into JSON.
"""

from typing import List

from pydantic import BaseModel, Field


class Equipment(BaseModel):
    """A single physical or logical device referenced in the requirement."""

    name: str = Field(
        description=(
            "The identifier or human name of the equipment exactly as it "
            "appears in the text. Prefer the engineering tag if one is given "
            "(e.g. 'EV-101', 'PMP-200'); otherwise use the descriptive name "
            "(e.g. 'start button', 'tank level sensor')."
        )
    )
    type: str = Field(
        description=(
            "The category or kind of the equipment, normalized to a short "
            "noun phrase. Examples: 'solenoid valve', 'sensor', 'push "
            "button', 'pump', 'motor', 'level transmitter'. Infer the type "
            "from context when it is not stated explicitly."
        )
    )


class Interlock(BaseModel):
    """A safety interlock: a condition that forces a protective action."""

    condition: str = Field(
        description=(
            "The specific trigger or hazardous condition that activates the "
            "interlock. Capture the full logical test where possible, "
            "e.g. 'Emergency Stop pressed', 'Tank level < 10%', "
            "'Pressure exceeds 5 bar'."
        )
    )
    action: str = Field(
        description=(
            "The forced safety action that must be executed when the "
            "condition is true. State it as an imperative referencing the "
            "affected equipment, e.g. 'Close EV-101 immediately', "
            "'Stop pump PMP-200', 'De-energize all outputs'."
        )
    )


class ControlSequence(BaseModel):
    """One ordered step in the normal operating control sequence."""

    step_id: int = Field(
        description=(
            "The chronological order of this action within the overall "
            "sequence, starting from 1 and incrementing by 1 for each "
            "subsequent step. Use the narrative order if no explicit numbers "
            "are given."
        )
    )
    description: str = Field(
        description=(
            "A detailed description of what happens in this step, including "
            "the equipment involved and any timing or condition that gates "
            "the action, e.g. 'Open EV-101 to begin filling the tank until "
            "the high-level sensor is triggered'."
        )
    )


class SystemRequirement(BaseModel):
    """The complete structured representation of a control requirement."""

    equipment_list: List[Equipment] = Field(
        description=(
            "The complete list of all distinct equipment items mentioned "
            "anywhere in the requirement. Include each device only once."
        )
    )
    interlocks: List[Interlock] = Field(
        description=(
            "All safety interlocks described in the requirement. Use an empty "
            "list if no interlocks or safety conditions are mentioned."
        )
    )
    sequences: List[ControlSequence] = Field(
        description=(
            "The ordered control sequence describing normal operation, as a "
            "list of steps sorted by step_id. Use an empty list if no "
            "operating sequence is described."
        )
    )
