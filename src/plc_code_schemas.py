"""Output contracts for future IEC 61131-3 code generation (E2S4).

These Pydantic models define lightweight MVP structures for generated
Structured Text (ST) blocks and Ladder Diagram (LD) networks. They are
contracts only; ST/LD generation logic is intentionally deferred to later
E2S4 tasks.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class STBlock(BaseModel):
    """One generated Structured Text block linked to an AST source node."""

    block_id: str = Field(
        description="Stable identifier for this generated ST block."
    )
    title: str = Field(
        description="Human-readable title for the ST block."
    )
    code: str = Field(
        description="Generated IEC 61131-3 Structured Text code for this block."
    )
    source_ast_node_id: Optional[str] = Field(
        default=None,
        description="Traceability link to the source AST node identifier.",
    )
    source_step_id: Optional[int] = Field(
        default=None,
        description="Traceability link to the source control-sequence step.",
    )
    source_scenario: Optional[str] = Field(
        default=None,
        description="Traceability link to the source Gherkin scenario name.",
    )
    source_interlock_condition: Optional[str] = Field(
        default=None,
        description="Traceability link to the source interlock condition text.",
    )


class STProgram(BaseModel):
    """Full generated Structured Text program contract."""

    program_name: str = Field(
        description="Name of the generated ST program."
    )
    variables: list[str] = Field(
        description="PLC variable declarations or variable names used by the ST program."
    )
    blocks: list[STBlock] = Field(
        description="Generated ST blocks that make up the program."
    )
    source_ast_file: str = Field(
        description="Path to the AST JSON file used as the generation source."
    )


class LDContact(BaseModel):
    """One Ladder Diagram contact."""

    variable: str = Field(
        description="PLC variable referenced by this contact."
    )
    contact_type: Literal["normally_open", "normally_closed"] = Field(
        description="Contact behavior: normally_open or normally_closed."
    )


class LDCoil(BaseModel):
    """One Ladder Diagram coil."""

    variable: str = Field(
        description="PLC variable driven by this coil."
    )
    coil_type: Literal["normal", "set", "reset"] = Field(
        description="Coil behavior: normal, set, or reset."
    )


class LDNetwork(BaseModel):
    """One Ladder Diagram network/rung linked to an AST source node."""

    network_id: str = Field(
        description="Stable identifier for this LD network."
    )
    title: str = Field(
        description="Human-readable title for the LD network."
    )
    contacts: list[LDContact] = Field(
        description="Input contacts for the network/rung."
    )
    coil: LDCoil = Field(
        description="Output coil driven by the network/rung."
    )
    priority: int = Field(
        default=1,
        description="Execution or safety priority for this network; defaults to 1.",
    )
    source_ast_node_id: Optional[str] = Field(
        default=None,
        description="Traceability link to the source AST node identifier.",
    )
    source_step_id: Optional[int] = Field(
        default=None,
        description="Traceability link to the source control-sequence step.",
    )
    source_scenario: Optional[str] = Field(
        default=None,
        description="Traceability link to the source Gherkin scenario name.",
    )
    source_interlock_condition: Optional[str] = Field(
        default=None,
        description="Traceability link to the source interlock condition text.",
    )


class LDProgram(BaseModel):
    """Full Ladder Diagram intermediate representation contract."""

    program_name: str = Field(
        description="Name of the generated LD program."
    )
    networks: list[LDNetwork] = Field(
        description="Generated LD networks/rungs that make up the program."
    )
    source_ast_file: str = Field(
        description="Path to the AST JSON file used as the generation source."
    )
