"""Unit tests for src/ld_ir_gen_llm_direct.py (E3S3T2).

Covers the deterministic Python-owned surface of the LLM-direct LD IR wrapper:
loading, path resolution, JSON cleanup/parsing, variable-name rules, expected
interlock target derivation, structural LD validation (ordering, uniqueness,
traceability, coil/contact rules, multi-target completeness), message
conversion, and the validation-retry loop in generate_ld_program() with a
scripted fake LLM.
"""

from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import src.ld_ir_gen_llm_direct as ld_llm
from src.plc_code_schemas import LDProgram


VALID_PAYLOAD: dict = {
    "program_name": "Signal_light_control",
    "source_ast_file": "data/ast/signal_light_demo_api_AST_C.json",
    "networks": [
        {
            "network_id": "SEQ-1",
            "title": "Sequence Step 1",
            "contacts": [{"variable": "PB_101", "contact_type": "normally_open"}],
            "coil": {"variable": "SL_301", "coil_type": "set"},
            "priority": 1,
            "source_ast_node_id": "SEQ-1",
            "source_step_id": 1,
            "source_scenario": "Operator starts the system",
            "notes": [],
        },
        {
            "network_id": "ILK-1",
            "title": "Safety Interlock ILK-1",
            "contacts": [{"variable": "Emergency_Stop_Button", "contact_type": "normally_open"}],
            "coil": {"variable": "SL_301", "coil_type": "reset"},
            "priority": 1,
            "source_ast_node_id": "ILK-1",
            "source_interlock_condition": "Emergency Stop button is pressed",
            "source_condition": "Emergency Stop button is pressed",
            "notes": [],
        },
    ],
}


class LoadAstTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_valid_ast_loads(self) -> None:
        ast = ld_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        self.assertGreater(len(ast.interlocks), 0)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            ld_llm.load_ast(self.dir / "missing.json")

    def test_invalid_ast_raises_value_error(self) -> None:
        path = self.dir / "bad.json"
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            ld_llm.load_ast(path)


class ResolveOutputPathTests(unittest.TestCase):
    def test_backend_specific_ld_suffix(self) -> None:
        out = ld_llm.resolve_output_path(Path("data/ast/x.json"), "api")
        self.assertEqual(out.name, "x_ld_llm_direct_api.json")
        out_local = ld_llm.resolve_output_path(Path("data/ast/x.json"), "local")
        self.assertEqual(out_local.name, "x_ld_llm_direct_local.json")


class CleanAndParseJsonTests(unittest.TestCase):
    def test_full_fence_is_stripped(self) -> None:
        self.assertEqual(
            ld_llm.clean_llm_json('```json\n{"a": 1}\n```'), '{"a": 1}'
        )

    def test_partial_fences_are_stripped(self) -> None:
        self.assertEqual(ld_llm.clean_llm_json('```\n{"a": 1}'), '{"a": 1}')
        self.assertEqual(ld_llm.clean_llm_json('{"a": 1}\n```'), '{"a": 1}')

    def test_parse_ld_json_object(self) -> None:
        self.assertEqual(ld_llm.parse_ld_json('{"a": 1}'), {"a": 1})

    def test_parse_ld_json_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            ld_llm.parse_ld_json("{not json")

    def test_parse_ld_json_non_object_raises(self) -> None:
        with self.assertRaises(ValueError):
            ld_llm.parse_ld_json("[1, 2, 3]")


class MessageContentToTextTests(unittest.TestCase):
    def test_str_and_list_shapes(self) -> None:
        self.assertEqual(ld_llm._message_content_to_text("x"), "x")
        self.assertEqual(
            ld_llm._message_content_to_text(["a", {"text": "b"}]),
            "a\nb",
        )


class VariableNameRulesTests(unittest.TestCase):
    def test_invalid_name_forms(self) -> None:
        for name in ("", "  ", "TODO", "with space", "80%", "EV-101", "has%dash"):
            with self.subTest(name=name):
                self.assertTrue(ld_llm._is_invalid_variable_name(name))

    def test_valid_names(self) -> None:
        for name in ("EV_101", "Tank_Level_At_80_Percent", "_lead", "V_301"):
            with self.subTest(name=name):
                self.assertFalse(ld_llm._is_invalid_variable_name(name))

    def test_generic_marker_coil_is_invalid(self) -> None:
        self.assertTrue(ld_llm._is_invalid_coil_variable("Safety_Interlock_Active"))
        self.assertTrue(ld_llm._is_invalid_coil_variable("TODO"))

    def test_sanitize_var_name(self) -> None:
        self.assertEqual(ld_llm._sanitize_var_name("EV-101"), "EV_101")
        self.assertEqual(ld_llm._sanitize_var_name("301-SL"), "V_301_SL")

    def test_coil_matches_device(self) -> None:
        self.assertTrue(ld_llm._coil_matches_device("EV_101", "EV-101"))
        self.assertTrue(ld_llm._coil_matches_device("ILK_1_EV_101", "EV-101"))
        self.assertFalse(ld_llm._coil_matches_device("EV_102", "EV-101"))

    def test_text_mentions_device_boundary(self) -> None:
        self.assertTrue(ld_llm._text_mentions_device("SL-301 turns red", "SL-301"))
        self.assertFalse(ld_llm._text_mentions_device("SL-3012 turns red", "SL-301"))


class ExpectedInterlockTargetsTests(unittest.TestCase):
    def test_derives_targets_from_forced_action_mentions(self) -> None:
        ast = ld_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        targets = ld_llm._expected_interlock_targets(ast)
        # ILK-1 forces SL-301 red; 'SL-301' appears in the forced action.
        self.assertEqual(targets, {"ILK-1": ["SL-301"]})


class ValidateLdStructureTests(unittest.TestCase):
    def _program(self, **network_overrides) -> LDProgram:
        payload = {**VALID_PAYLOAD}
        if "networks" in network_overrides:
            payload["networks"] = network_overrides.pop("networks")
        for key, value in network_overrides.items():
            payload[key] = value
        return LDProgram.model_validate(payload)

    def test_valid_structure_passes(self) -> None:
        ld_llm.validate_ld_structure(self._program())  # no raise

    def test_empty_network_list_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            ld_llm.validate_ld_structure(self._program(networks=[]))
        self.assertIn("at least one network", str(ctx.exception))

    def test_missing_source_ast_file_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            ld_llm.validate_ld_structure(self._program(source_ast_file=""))
        self.assertIn("source_ast_file", str(ctx.exception))

    def test_percent_in_program_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            ld_llm.validate_ld_structure(self._program(program_name="Tank_80%"))

    def test_duplicate_network_ids_raise(self) -> None:
        networks = [dict(VALID_PAYLOAD["networks"][0]), dict(VALID_PAYLOAD["networks"][0])]
        networks[1]["network_id"] = "SEQ-1"
        with self.assertRaises(ValueError) as ctx:
            ld_llm.validate_ld_structure(self._program(networks=networks))
        self.assertIn("Duplicate LD network_id", str(ctx.exception))

    def test_missing_traceability_raises(self) -> None:
        network = dict(VALID_PAYLOAD["networks"][0])
        network["source_ast_node_id"] = ""
        networks = [network, dict(VALID_PAYLOAD["networks"][1])]
        with self.assertRaises(ValueError):
            ld_llm.validate_ld_structure(self._program(networks=networks))

    def test_sequence_after_interlock_network_raises(self) -> None:
        seq = dict(VALID_PAYLOAD["networks"][0])
        ilk = dict(VALID_PAYLOAD["networks"][1])
        with self.assertRaises(ValueError) as ctx:
            ld_llm.validate_ld_structure(self._program(networks=[ilk, seq]))
        self.assertIn("Sequence network appears after", str(ctx.exception))

    def test_invalid_contact_variable_raises(self) -> None:
        network = dict(VALID_PAYLOAD["networks"][0])
        network["contacts"] = [{"variable": "PB-101", "contact_type": "normally_open"}]
        with self.assertRaises(ValueError) as ctx:
            ld_llm.validate_ld_structure(self._program(networks=[network]))
        self.assertIn("invalid contact variable", str(ctx.exception))

    def test_generic_marker_coil_raises(self) -> None:
        network = dict(VALID_PAYLOAD["networks"][0])
        network["coil"] = {"variable": "Safety_Interlock_Active", "coil_type": "normal"}
        with self.assertRaises(ValueError) as ctx:
            ld_llm.validate_ld_structure(self._program(networks=[network]))
        self.assertIn("invalid coil variable", str(ctx.exception))

    def test_missing_interlock_target_coil_raises(self) -> None:
        # Expected target SL-301 for ILK-1, but ILK-1's network coils something else.
        ilk = dict(VALID_PAYLOAD["networks"][1])
        ilk["coil"] = {"variable": "Something_Else", "coil_type": "reset"}
        program = self._program(
            networks=[dict(VALID_PAYLOAD["networks"][0]), ilk]
        )
        with self.assertRaises(ValueError) as ctx:
            ld_llm.validate_ld_structure(
                program, expected_interlock_targets={"ILK-1": ["SL-301"]}
            )
        self.assertIn("missing a target coil network", str(ctx.exception))

    def test_multi_target_completeness(self) -> None:
        ilk1 = dict(VALID_PAYLOAD["networks"][1])
        ilk2 = dict(VALID_PAYLOAD["networks"][1])
        ilk2["network_id"] = "ILK-1_SL_302"
        ilk2["coil"] = {"variable": "SL_302", "coil_type": "reset"}
        program = self._program(
            networks=[dict(VALID_PAYLOAD["networks"][0]), ilk1, ilk2]
        )
        ld_llm.validate_ld_structure(
            program,
            expected_interlock_targets={"ILK-1": ["SL-301", "SL-302"]},
        )  # no raise


class ProgramFromMessageTests(unittest.TestCase):
    def test_valid_payload_parses(self) -> None:
        message = SimpleNamespace(content=json.dumps(VALID_PAYLOAD))
        program = ld_llm._program_from_message(message, {})
        self.assertIsInstance(program, LDProgram)
        self.assertEqual(program.program_name, "Signal_light_control")

    def test_invalid_payload_raises_value_error(self) -> None:
        bad = dict(VALID_PAYLOAD)
        bad["networks"] = [{"network_id": 5}]  # schema violation
        message = SimpleNamespace(content=json.dumps(bad))
        with self.assertRaises(ValueError):
            ld_llm._program_from_message(message, {})


class GenerateLdProgramTests(unittest.TestCase):
    def test_api_backend_without_key_raises(self) -> None:
        ast = ld_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            with self.assertRaises(ld_llm.LLMBackendError) as ctx:
                ld_llm.generate_ld_program(ast, Path("data/ast/x.json"), "api")
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    class ScriptedLlm:
        def __init__(self, responses: list[str]) -> None:
            self._responses = list(responses)

        def bind(self, **kwargs):
            def invoke(_input):
                payload = self._responses.pop(0)
                return SimpleNamespace(content=payload)

            return invoke

    def _patch_llm(self, responses: list[str]):
        return mock.patch.object(
            ld_llm,
            "build_llm",
            side_effect=lambda backend: self.ScriptedLlm(responses),
        )

    def test_valid_first_response_succeeds(self) -> None:
        ast = ld_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        valid = json.dumps(VALID_PAYLOAD)
        with self._patch_llm([valid]):
            program = ld_llm.generate_ld_program(ast, Path("data/ast/x.json"), "local")
        self.assertIsInstance(program, LDProgram)

    def test_invalid_then_valid_retries_on_local(self) -> None:
        ast = ld_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        invalid_network = dict(VALID_PAYLOAD["networks"][0])
        invalid_network["coil"] = {
            "variable": "Safety_Interlock_Active",
            "coil_type": "normal",
        }
        bad = dict(VALID_PAYLOAD)
        bad["networks"] = [invalid_network, dict(VALID_PAYLOAD["networks"][1])]
        valid = json.dumps(VALID_PAYLOAD)
        with self._patch_llm([json.dumps(bad), valid]):
            program = ld_llm.generate_ld_program(
                ast, Path("data/ast/x.json"), "local"
            )
        self.assertIsInstance(program, LDProgram)

    def test_persistent_invalid_output_raises_validation_error(self) -> None:
        ast = ld_llm.load_ast(Path("data/ast/signal_light_demo_api_AST_C.json"))
        bad = dict(VALID_PAYLOAD)
        bad["program_name"] = "Tank_80%"
        payload = json.dumps(bad)
        with self._patch_llm([payload, payload, payload]):  # local: 3 attempts
            with self.assertRaises(ld_llm.LLMOutputValidationError):
                ld_llm.generate_ld_program(ast, Path("data/ast/x.json"), "local")


if __name__ == "__main__":
    unittest.main()