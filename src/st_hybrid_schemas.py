"""Structured code-intent schemas for the hybrid ST generator (E2S4T6).

The hybrid approach keeps the deterministic baseline renderer from
``src/st_gen.py`` and adds per-item LLM tool calls that return *structured code
intent*: semantic suggestions for the complex logic a plain BOOL draft cannot
represent (timers, analogue thresholds, colour states, sequence-state notes).
Python owns grounding checks, variable naming, TON/REAL declaration decisions,
and all final Structured Text rendering. The LLM never emits ST.

Field descriptions double as prompt instructions, the same convention used by
``src/schemas.py`` and ``src/ast_schemas.py``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TimerIntent(BaseModel):
    """One timer/delay that gates an action in the final ST logic."""

    duration_seconds: float = Field(
        gt=0,
        le=3600,
        description=(
            "Timer duration in seconds; must be greater than 0 and at most 3600."
        ),
    )
    description: str = Field(
        description=(
            "What the timer gates, e.g. 'settling delay before opening the "
            "draining valve'."
        )
    )


class ColourStateIntent(BaseModel):
    """One colour/state change for a device, used for review comments."""

    device: str = Field(
        description=(
            "Name of the device whose colour/state changes; must be one "
            "equipment name from the supplied equipment list."
        )
    )
    colour: Literal["green", "red", "yellow", "on", "off"] = Field(
        description="Target colour/state for the device."
    )
    description: str = Field(
        default="",
        description="Optional plain-English note about this colour state.",
    )


class AnalogueIntent(BaseModel):
    """One analogue threshold condition that gates an action."""

    device: str = Field(
        description=(
            "Name of the analogue device being measured; must be one equipment "
            "name from the supplied equipment list."
        )
    )
    operator: Literal[">=", "<=", ">", "<", "=="] = Field(
        description="Comparison operator for the analogue threshold."
    )
    threshold: float = Field(
        description="Threshold value for the analogue condition."
    )
    description: str = Field(
        default="",
        description="Optional plain-English note about this analogue condition.",
    )


class SequenceCodeIntent(BaseModel):
    """Structured code intent for one control-sequence step."""

    timers: list[TimerIntent] = Field(
        default_factory=list,
        description="Timers/delays that gate this step's action.",
    )
    colour_states: list[ColourStateIntent] = Field(
        default_factory=list,
        description="Colour/state changes this step causes.",
    )
    analogue_conditions: list[AnalogueIntent] = Field(
        default_factory=list,
        description="Analogue threshold conditions this step depends on.",
    )
    state_notes: list[str] = Field(
        default_factory=list,
        description="Short review notes about sequence-state logic this step needs.",
    )


class InterlockCodeIntent(BaseModel):
    """Structured code intent for one safety interlock."""

    colour_states: list[ColourStateIntent] = Field(
        default_factory=list,
        description="Colour/state changes this interlock forces.",
    )
    state_notes: list[str] = Field(
        default_factory=list,
        description="Short review notes about logic this interlock needs.",
    )
