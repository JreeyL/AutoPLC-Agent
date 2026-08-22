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
    SafetyReviewItem,
    Severity,
    StepReviewItem,
    Tier1Result,
    Tier1Validator,
    Tier2Result,
    Tier2SemanticEvaluator,
    UnifiedReport,
    ValidationIssue,
    load_pipeline_artifacts,
    run_unified_validation,
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

# ---------------------------------------------------------------------------
# Tier 2 / unified validation (E3S3T1 Part 2) - mock evaluator, no live API
# ---------------------------------------------------------------------------



def _load_signal():
    return load_pipeline_artifacts("data/ast/signal_light_demo_api_AST_C.json")


def _tier2_result(score=95.0, missing=None, hazards=None) -> Tier2Result:
    parsed, _, _, _ = _load_signal()
    return Tier2Result(
        score=score,
        steps_reviewed=[StepReviewItem(step_id=s.step_id, covered=True)
                        for s in parsed.sequences],
        safety_reviews=[SafetyReviewItem(interlock_condition=il.condition,
                                         addressed=True, hazard_flag=False)
                        for il in parsed.interlocks],
        missing_steps=missing or [],
        critical_hazards=hazards or [],
        summary="mock verdict",
        backend="mock",
    )


class _FakeEvaluator(Tier2SemanticEvaluator):
    """Deterministic stand-in: returns a canned Tier2Result, never calls an LLM."""

    def __init__(self, result: Tier2Result):
        super().__init__(backend="mock")
        self._result = result
        self.calls = 0

    def evaluate(self, parsed, ast, st_text, ld=None) -> Tier2Result:
        self.calls += 1
        return self._result


class Tier2SchemaTests(unittest.TestCase):
    def test_tier2_result_defaults_and_roundtrip(self) -> None:
        r = _tier2_result()
        self.assertEqual(r.score, 95.0)
        self.assertEqual(r.backend, "mock")
        self.assertEqual(r.missing_steps, [])

    def test_unified_report_requires_tier1(self) -> None:
        with self.assertRaises(Exception):
            UnifiedReport(tier2=None, valid=True)  # tier1 is required


class ThresholdGatingTests(unittest.TestCase):
    def test_high_score_passes_gate(self) -> None:
        parsed, ast, st, ld = _load_signal()
        report = run_unified_validation(
            parsed, ast, st, ld, score_threshold=80.0,
            evaluator=_FakeEvaluator(_tier2_result(score=95.0)))
        self.assertTrue(report.valid)
        self.assertIsNotNone(report.tier2)
        self.assertEqual(report.gate_reason, "")

    def test_low_score_fails_gate(self) -> None:
        parsed, ast, st, ld = _load_signal()
        report = run_unified_validation(
            parsed, ast, st, ld, score_threshold=80.0,
            evaluator=_FakeEvaluator(_tier2_result(score=55.0)))
        self.assertFalse(report.valid)
        self.assertIn("coverage score", report.gate_reason)

    def test_custom_threshold_boundary(self) -> None:
        parsed, ast, st, ld = _load_signal()
        report = run_unified_validation(
            parsed, ast, st, ld, score_threshold=90.0,
            evaluator=_FakeEvaluator(_tier2_result(score=85.0)))
        self.assertFalse(report.valid)


class HazardBlockingTests(unittest.TestCase):
    def test_critical_hazard_blocks_even_with_good_score(self) -> None:
        parsed, ast, st, ld = _load_signal()
        result = _tier2_result(score=99.0, hazards=["unaddressed E-Stop wiring"])
        report = run_unified_validation(parsed, ast, st, ld, evaluator=_FakeEvaluator(result))
        self.assertFalse(report.valid)
        self.assertIn("critical hazards", report.gate_reason)

    def test_missing_steps_block(self) -> None:
        parsed, ast, st, ld = _load_signal()
        result = _tier2_result(score=90.0, missing=[1])
        report = run_unified_validation(parsed, ast, st, ld, evaluator=_FakeEvaluator(result))
        self.assertFalse(report.valid)
        self.assertIn("missing steps", report.gate_reason)


class FailFastTests(unittest.TestCase):
    def test_tier1_errors_skip_tier2(self) -> None:
        parsed, ast, st, ld = _load_signal()
        mut = deepcopy(ast)
        mut.interlocks[0].source_interlock_condition = "HACKED"
        fake = _FakeEvaluator(_tier2_result())
        report = run_unified_validation(parsed, mut, st, ld, evaluator=fake)
        self.assertFalse(report.valid)
        self.assertIsNone(report.tier2)
        self.assertIn("tier1 structural errors", report.gate_reason)
        self.assertEqual(fake.calls, 0, "Tier 2 must not run when Tier 1 fails")

    def test_clean_pipeline_runs_evaluator_once(self) -> None:
        parsed, ast, st, ld = _load_signal()
        fake = _FakeEvaluator(_tier2_result())
        report = run_unified_validation(parsed, ast, st, ld, evaluator=fake)
        self.assertTrue(report.valid)
        self.assertEqual(fake.calls, 1)

    def test_real_pipeline_end_to_end_with_mock(self) -> None:
        for ast_file in ["data/ast/signal_light_demo_api_AST_C.json",
                         "data/ast/sample_control_api_AST_C.json"]:
            with self.subTest(file=ast_file):
                parsed, ast, st, ld = load_pipeline_artifacts(ast_file)
                report = run_unified_validation(
                    parsed, ast, st, ld, evaluator=_FakeEvaluator(_tier2_result()))
                self.assertTrue(report.valid)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()