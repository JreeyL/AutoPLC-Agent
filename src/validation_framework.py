"""Tier 1 deterministic validation framework (E3S3T1, Part 1).

Consolidates the deterministic, offline checks from the E3S1 artifact suites
into one reusable validator operating across a single requirement pipeline
(parsed ``SystemRequirement`` -> ``PLC_AST`` -> generated ST text -> LD IR):

- Equipment grounding: AST ``source_equipment`` maps verbatim into the parsed
  ``equipment_list``; ST/LD variables resolve to AST devices.
- ID continuity: monotonic continuous sequence ``step_id``, interlock
  ``priority >= 1``, unique LD ``network_id``.
- Authoritative field protection: interlock ``source_interlock_condition`` and
  sequence ``source_step_id`` remain verbatim references into the parsed
  requirement (untampered).
- Structural contract: ``PROGRAM``/``END_PROGRAM`` wrapper, balanced
  ``IF``/``END_IF``, and sequence-before-safety ordering in LD.

No business-logic semantic review is performed in Tier 1; that is the Tier 2
(LLM-based evaluator) responsibility (E3S3T1 Part 2).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import re

from pydantic import BaseModel, Field

from src.ast_schemas import PLC_AST
from src.plc_code_schemas import LDProgram
from src.schemas import SystemRequirement
from src.st_gen import sanitize_var_name


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    severity: Severity
    code: str
    message: str
    context: str = ""

    def __init__(self, severity, code, message, context: str = ""):
        super().__init__(severity=severity, code=code, message=message, context=context)


class Tier1Result(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]


_TAG_RE = re.compile(r"\b[A-Z]{1,4}-\d+\b")


class Tier1Validator:
    """Deterministic multi-artifact validator for one requirement pipeline."""

    # ---- grounding ---------------------------------------------------------

    def check_equipment_grounding(
        self,
        parsed: SystemRequirement,
        ast: PLC_AST,
        st_text: str = "",
        ld: LDProgram | None = None,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        parsed_names = {e.name for e in parsed.equipment_list}

        if not ast.devices:
            issues.append(ValidationIssue(Severity.ERROR, "GROUNDING_EMPTY_DEVICES",
                                          "AST has no devices"))
        seen_source: set[str] = set()
        for dev in ast.devices:
            if dev.name in seen_source:
                issues.append(ValidationIssue(Severity.ERROR, "GROUNDING_DUPLICATE_DEVICE",
                                              f"duplicate device {dev.name!r}", dev.node_id))
            seen_source.add(dev.name)
            if not dev.name.strip() or not dev.device_type.strip():
                issues.append(ValidationIssue(Severity.ERROR, "GROUNDING_EMPTY_DEVICE_FIELD",
                                              f"device {dev.node_id!r} has empty name/type"))
            if dev.source_equipment not in parsed_names:
                issues.append(ValidationIssue(
                    Severity.ERROR, "GROUNDING_SOURCE_EQUIPMENT",
                    f"source_equipment {dev.source_equipment!r} not in parsed equipment_list",
                    dev.node_id))

        # Device tags referenced in AST sequence/interlock text must resolve.
        texts = [s.action for s in ast.sequence]
        texts += [s.condition or "" for s in ast.sequence]
        texts += [il.condition for il in ast.interlocks]
        texts += [il.forced_action for il in ast.interlocks]
        for tag in sorted(set(_TAG_RE.findall(" || ".join(texts)))):
            if not any(tag in d.name or tag in d.device_type for d in ast.devices):
                issues.append(ValidationIssue(
                    Severity.ERROR, "GROUNDING_TAG_UNRESOLVED",
                    f"device tag {tag!r} does not resolve to any AST device"))

        # ST variables resolve to AST devices (sanitized names).
        if st_text:
            known = {sanitize_var_name(d.name) for d in ast.devices}
            var_block = re.search(r"\bVAR\b(.*?)\bEND_VAR\b", st_text, re.S)
            declared_vars = (
                set(re.findall(r"^\s*(\w+)\s*:", var_block.group(1), re.M))
                if var_block else set()
            )
            for var in sorted(declared_vars - known):
                issues.append(ValidationIssue(
                    Severity.WARNING, "GROUNDING_ST_VARIABLE",
                    f"ST variable {var!r} not declared from AST devices"))

        # LD contact/coil variables resolve to AST devices.
        if ld is not None:
            known = {sanitize_var_name(d.name) for d in ast.devices}
            for net in ld.networks:
                for var in [net.coil.variable, *[c.variable for c in net.contacts]]:
                    if var and var not in known:
                        issues.append(ValidationIssue(
                            Severity.ERROR, "GROUNDING_LD_VARIABLE",
                            f"LD variable {var!r} not an AST device variable", net.network_id))
        return issues

    # ---- id continuity ------------------------------------------------------

    def check_id_continuity(
        self, ast: PLC_AST, ld: LDProgram | None = None
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        ids = [s.step_id for s in ast.sequence]
        if ids and ids != list(range(1, len(ids) + 1)):
            issues.append(ValidationIssue(
                Severity.ERROR, "SEQUENCE_STEP_GAP",
                f"sequence step_ids {ids} are not continuous from 1"))
        if ld is not None:
            ids_ld = [n.network_id for n in ld.networks]
            if len(ids_ld) != len(set(ids_ld)):
                dupes = {nid for nid in ids_ld if ids_ld.count(nid) > 1}
                issues.append(ValidationIssue(
                    Severity.ERROR, "LD_DUPLICATE_NETWORK",
                    f"duplicate LD network_id(s): {sorted(dupes)}"))
        for il in ast.interlocks:
            if il.priority < 1:
                issues.append(ValidationIssue(
                    Severity.ERROR, "INTERLOCK_PRIORITY",
                    f"interlock {il.node_id} priority {il.priority} < 1", il.node_id))
        return issues

    # ---- authoritative field protection --------------------------------------

    def check_authoritative_fields(
        self, parsed: SystemRequirement, ast: PLC_AST
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        parsed_conds = {il.condition for il in parsed.interlocks}
        for il in ast.interlocks:
            if not il.source_interlock_condition.strip():
                issues.append(ValidationIssue(Severity.ERROR, "AUTHORITATIVE_INTERLOCK_EMPTY",
                                              f"interlock {il.node_id} lacks source condition"))
            elif il.source_interlock_condition not in parsed_conds:
                issues.append(ValidationIssue(
                    Severity.ERROR, "AUTHORITATIVE_INTERLOCK_TAMPERED",
                    f"interlock condition {il.source_interlock_condition!r} does not "
                    f"match any parsed interlock verbatim", il.node_id))
            if not il.forced_action.strip():
                issues.append(ValidationIssue(Severity.ERROR, "AUTHORITATIVE_INTERLOCK_ACTION",
                                              f"interlock {il.node_id} empty forced_action"))

        parsed_step_ids = {s.step_id for s in parsed.sequences}
        for step in ast.sequence:
            if step.source_step_id not in parsed_step_ids:
                issues.append(ValidationIssue(
                    Severity.ERROR, "AUTHORITATIVE_STEP_REF",
                    f"sequence {step.node_id} source_step_id {step.source_step_id} "
                    f"not found in parsed", step.node_id))
        return issues

    # ---- structural contract --------------------------------------------------

    def check_structural_contract(
        self, st_text: str, ld: LDProgram | None = None
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if st_text.strip():
            if "PROGRAM" not in st_text or "END_PROGRAM" not in st_text:
                issues.append(ValidationIssue(Severity.ERROR, "ST_PROGRAM_WRAPPER",
                                              "ST missing PROGRAM/END_PROGRAM wrapper"))
            if_count = len(re.findall(r"^\s*IF\s", st_text, re.M))
            endif_count = st_text.count("END_IF")
            if if_count != endif_count:
                issues.append(ValidationIssue(
                    Severity.ERROR, "ST_IF_ENDIF_UNBALANCED",
                    f"IF ({if_count}) / END_IF ({endif_count}) unbalanced"))
        if ld is not None:
            seq = [i for i, n in enumerate(ld.networks) if n.network_id.startswith("SEQ")]
            ilk = [i for i, n in enumerate(ld.networks) if not n.network_id.startswith("SEQ")]
            if seq and ilk and max(seq) > min(ilk):
                issues.append(ValidationIssue(
                    Severity.ERROR, "LD_SEQUENCE_AFTER_SAFETY",
                    "interlock network precedes sequence network"))
        return issues

    # ---- composed runner -------------------------------------------------------

    def validate_artifacts(
        self,
        parsed: SystemRequirement,
        ast: PLC_AST,
        st_text: str = "",
        ld: LDProgram | None = None,
    ) -> Tier1Result:
        """Run the full Tier 1 check set over one pipeline's artifacts."""
        issues = []
        issues += self.check_equipment_grounding(parsed, ast, st_text, ld)
        issues += self.check_id_continuity(ast, ld)
        issues += self.check_authoritative_fields(parsed, ast)
        issues += self.check_structural_contract(st_text, ld)
        return Tier1Result(valid=not any(i.severity == Severity.ERROR for i in issues),
                           issues=issues)


def load_pipeline_artifacts(ast_path: Path | str):
    """Load the paired parsed/ST/LD artifacts for a given AST file.

    Returns ``(parsed, ast, st_text, ld)`` using the AST's own provenance fields
    and the deterministic ST/LD artifacts sharing the AST stem.
    """
    ast_path = Path(ast_path)
    ast = PLC_AST.model_validate_json(ast_path.read_text(encoding="utf-8"))
    parsed = SystemRequirement.model_validate_json(
        Path(ast.source_requirement_file).read_text(encoding="utf-8")
    )
    st_text = (ast_path.parent.parent / "plc" / "st"
               / f"{ast_path.stem}.st").read_text(encoding="utf-8")
    ld_path = ast_path.parent.parent / "plc" / "ld" / f"{ast_path.stem}_ld.json"
    ld = LDProgram.model_validate_json(ld_path.read_text(encoding="utf-8"))
    return parsed, ast, st_text, ld