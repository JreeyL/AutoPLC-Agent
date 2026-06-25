"""Structured-output schema for BDD/Gherkin generation (E2S2T1).

These Pydantic models define the target structure for LangChain's
``.with_structured_output()`` during the Gherkin-generation stage. As with
``src/schemas.py``, the ``Field`` descriptions double as prompt instructions:
they tell the LLM exactly how to turn a single requirement item into a single
BDD scenario.

**This schema is consumed one item at a time, not all at once.** Each LLM call
binds :class:`GherkinScenario` via ``.with_structured_output()`` and converts
*exactly one* source item -- either one :class:`~src.schemas.ControlSequence`
step or one :class:`~src.schemas.Interlock` -- into *one*
:class:`GherkinScenario`. The model never receives a whole
:class:`~src.schemas.SystemRequirement` and never emits a list of scenarios in
a single response.

The rationale (documented in the project notes) is failure isolation: the
local model backing this pipeline (``local-model`` via LM Studio) is unreliable
at producing large, multi-item structured outputs in one shot, where a single
malformed item can corrupt or truncate the entire response. By driving the
conversion per source item, a parsing or quality failure is contained to that
one item -- the remaining steps and interlocks still generate cleanly, and the
bad item can be retried in isolation. :class:`GherkinFeature` is therefore
*assembled in Python* by the calling code after each per-item call returns; it
is never generated directly by the LLM.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class GherkinScenario(BaseModel):
    """One BDD scenario generated from a single requirement item.

    Produced by one ``.with_structured_output()`` call over exactly one
    :class:`~src.schemas.ControlSequence` step *or* one
    :class:`~src.schemas.Interlock`. The ``given``/``when``/``then`` steps are
    plain string lists (no nested ``GherkinStep`` type): a single scenario can
    carry multiple Given/When/Then lines.
    """

    name: str = Field(
        description=(
            "A short, descriptive name for this scenario, phrased as a "
            "behaviour from the operator's or system's point of view. Keep it "
            "to a single concise clause, e.g. 'Operator starts the conveyor', "
            "'Tank fills until high-level sensor trips', 'Emergency stop "
            "de-energizes all outputs'."
        )
    )
    given: List[str] = Field(
        description=(
            "The pre-condition steps that must already hold before the "
            "scenario runs, one per list entry. Do NOT include the 'Given' "
            "keyword in the string itself -- the renderer prepends 'Given'/"
            "'And' later. Examples: 'the conveyor is stopped', 'tank TK-101 "
            "level is below 10%', 'the system is in AUTO mode'."
        )
    )
    when: List[str] = Field(
        description=(
            "The triggering action steps that drive the behaviour, one per "
            "list entry. Do NOT include the 'When' keyword in the string "
            "itself -- the renderer prepends 'When'/'And' later. Examples: "
            "'the operator presses the start button', 'the high-level sensor "
            "is triggered', 'the Emergency Stop is pressed'."
        )
    )
    then: List[str] = Field(
        description=(
            "The expected outcome steps that must be true after the action, "
            "one per list entry. Do NOT include the 'Then' keyword in the "
            "string itself -- the renderer prepends 'Then'/'And' later. "
            "Examples: 'the conveyor motor runs forward', 'EV-101 closes "
            "immediately', 'pump PMP-200 stops'."
        )
    )
    source_step_id: Optional[int] = Field(
        default=None,
        description=(
            "Set ONLY when this scenario was generated from a "
            "ControlSequence step; holds that step's 'step_id' (e.g. 3) so "
            "the scenario can be traced back to its source. Leave as None for "
            "interlock-derived scenarios. Exactly one of 'source_step_id' or "
            "'source_interlock_condition' must be set on any scenario -- never "
            "both, never neither."
        ),
    )
    source_interlock_condition: Optional[str] = Field(
        default=None,
        description=(
            "Set ONLY when this scenario was generated from an Interlock; "
            "holds that interlock's original 'condition' text verbatim "
            "(e.g. 'Tank level < 10%') so the scenario can be traced back to "
            "its source even though Interlock has no numeric id field. Leave "
            "as None for control-sequence-derived scenarios. Exactly one of "
            "'source_step_id' or 'source_interlock_condition' must be set on "
            "any scenario -- never both, never neither."
        ),
    )


class GherkinFeature(BaseModel):
    """A complete BDD feature assembled from many per-item scenarios.

    This model is built in Python by the calling code, not emitted by the LLM.
    After each per-item ``.with_structured_output()`` call returns one
    :class:`GherkinScenario`, the caller appends it to ``scenarios`` and fills
    in ``title``/``description`` for the overall requirement.
    """

    title: str = Field(
        description=(
            "The feature title, naming the overall capability under test in a "
            "short noun phrase, e.g. 'Conveyor start/stop control', 'Tank "
            "filling sequence', 'Reactor safety interlocks'."
        )
    )
    description: str = Field(
        description=(
            "A 1-3 sentence summary of the feature describing the behaviour "
            "it covers and why it matters, e.g. 'Controls the filling of tank "
            "TK-101 from empty to its high-level setpoint. Ensures the inlet "
            "valve closes once the tank is full to prevent overflow.'"
        )
    )
    scenarios: List[GherkinScenario] = Field(
        default_factory=list,
        description=(
            "The list of scenarios belonging to this feature. Populated by the "
            "calling code after each per-item LLM call returns a single "
            "GherkinScenario; it is NOT produced by one LLM call over the whole "
            "requirement."
        ),
    )
