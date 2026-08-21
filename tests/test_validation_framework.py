"""Tier 1 deterministic validation framework tests (E3S3T1 Part 1).

Positive cases: the validator passes the real `signal_light_demo` and
`sample_control` pipelines (parsed / AST / deterministic ST / LD).
Negative cases: mutated artifacts (ungrounded devices, broken step sequences,
tampered interlocks, duplicate LD networks, unbalanced ST) are strictly
rejected with structured issue codes.
"""

from copy import deepcopy
import unittest

from src.ast_schemas import PLC_AST
from src.plc_code_schemas import LDProgram
from src.validation_framework import (
    Severity,
    Tier1Result,
    Tier1Validator,
    ValidationIssue,
    load_pipeline_artifacts,
)


def _model_mutation(model):
    """Deep-copy a Pydantic model for mutation without touching real artifacts."""
    return deepcopy(model)


class ReportingModelsTests(unittest.TestCase):
    def test_issue_and_result_models_shape(self) -> None:
        issue = ValidationIssue(Severity.ERROR, "X", "boom", "ctx")
        self.assertEqual(issue.code, "X")
        self.assertEqual(issue.severity, Severity.ERROR)
        result = Tier1Result(valid=False, issues=[issue])
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)


class PositivePipelineTests(unittest.TestCase):
    def test_signal_light_pipeline_passes(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/signal_light_demo_api_AST_C.json")
        result = Tier1Validator().validate_artifacts(parsed, ast, st, ld)
        self.assertTrue(result.valid, f"{result.errors}")

    def test_sample_control_pipeline_passes(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/sample_control_api_AST_C.json")
        result = Tier1Validator().validate_artifacts(parsed, ast, st, ld)
        self.assertTrue(result.valid, f"{result.errors}")

    def test_valid_result_has_no_error_issues(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/signal_light_demo_api_AST_C.json")
        result = Tier1Validator().validate_artifacts(parsed, ast, st, ld)
        self.assertEqual(result.errors, [])


class NegativeGroundingTests(unittest.TestCase):
    def test_ungrounded_source_equipment_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/signal_light_demo_api_AST_C.json")
        mut = _model_mutation(ast)
        mut.devices[0].source_equipment = "Phantom Device XX-99"
        result = Tier1Validator().validate_artifacts(parsed, mut, st, ld)
        self.assertFalse(result.valid)
        self.assertIn("GROUNDING_SOURCE_EQUIPMENT",
                      [i.code for i in result.issues])

    def test_unknown_device_tag_in_text_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/signal_light_demo_api_AST_C.json")
        mut = _model_mutation(ast)
        mut.sequence[0].action = "XX-777 must trigger the alarm"
        result = Tier1Validator().validate_artifacts(parsed, mut, st, ld)
        self.assertFalse(result.valid)
        self.assertIn("GROUNDING_TAG_UNRESOLVED",
                      [i.code for i in result.issues])


class NegativeSequenceTests(unittest.TestCase):
    def test_broken_step_sequence_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/sample_control_api_AST_C.json")
        mut = _model_mutation(ast)
        mut.sequence[2].step_id = 99  # breaks 1..4 continuity
        result = Tier1Validator().validate_artifacts(parsed, mut, st, ld)
        self.assertFalse(result.valid)
        self.assertIn("SEQUENCE_STEP_GAP", [i.code for i in result.issues])

    def test_duplicate_ld_network_id_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/sample_control_api_AST_C.json")
        ld_mut = _model_mutation(ld)
        ld_mut.networks[1].network_id = ld_mut.networks[0].network_id
        result = Tier1Validator().validate_artifacts(parsed, ast, st, ld_mut)
        self.assertFalse(result.valid)
        self.assertIn("LD_DUPLICATE_NETWORK", [i.code for i in result.issues])

    def test_low_interlock_priority_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/signal_light_demo_api_AST_C.json")
        mut = _model_mutation(ast)
        mut.interlocks[0].priority = 0
        result = Tier1Validator().validate_artifacts(parsed, mut, st, ld)
        self.assertFalse(result.valid)
        self.assertIn("INTERLOCK_PRIORITY", [i.code for i in result.issues])


class NegativeAuthoritativeTests(unittest.TestCase):
    def test_tampered_interlock_condition_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/signal_light_demo_api_AST_C.json")
        mut = _model_mutation(ast)
        mut.interlocks[0].source_interlock_condition = "HACKED CONDITION"
        result = Tier1Validator().validate_artifacts(parsed, mut, st, ld)
        self.assertFalse(result.valid)
        self.assertIn("AUTHORITATIVE_INTERLOCK_TAMPERED",
                      [i.code for i in result.issues])

    def test_forged_step_reference_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/signal_light_demo_api_AST_C.json")
        mut = _model_mutation(ast)
        mut.sequence[0].source_step_id = 12  # not present in parsed
        result = Tier1Validator().validate_artifacts(parsed, mut, st, ld)
        self.assertFalse(result.valid)
        self.assertIn("AUTHORITATIVE_STEP_REF", [i.code for i in result.issues])


class NegativeStructuralTests(unittest.TestCase):
    def test_unbalanced_if_end_if_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/signal_light_demo_api_AST_C.json")
        broken_st = st.replace("END_IF;", "END_IF;", 1)[: st.rfind("END_IF")]
        result = Tier1Validator().validate_artifacts(parsed, ast, broken_st, ld)
        self.assertFalse(result.valid)
        self.assertIn("ST_IF_ENDIF_UNBALANCED", [i.code for i in result.issues])

    def test_safety_before_sequence_rejected(self) -> None:
        parsed, ast, st, ld = load_pipeline_artifacts(
            "data/ast/sample_control_api_AST_C.json")
        ld_mut = _model_mutation(ld)
        seq_idx = [i for i, n in enumerate(ld_mut.networks) if n.network_id.startswith("SEQ")]
        ilk_idx = [i for i, n in enumerate(ld_mut.networks) if not n.network_id.startswith("SEQ")]
        order = ld_mut.networks
        order[seq_idx[0]], order[ilk_idx[0]] = order[ilk_idx[0]], order[seq_idx[0]]
        ld_mut.networks = order
        result = Tier1Validator().validate_artifacts(parsed, ast, st, ld_mut)
        self.assertFalse(result.valid)
        self.assertIn("LD_SEQUENCE_AFTER_SAFETY", [i.code for i in result.issues])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()