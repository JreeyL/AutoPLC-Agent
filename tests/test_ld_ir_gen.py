from pathlib import Path
import unittest

from src.ast_schemas import PLC_AST
from src.ld_ir_gen import (
    _build_contacts,
    _build_device_var_map,
    _sequence_action_text,
    _unsupported_condition_reasons,
    action_text_to_coil_type,
    build_ld_program,
)


class LDActionClassificationTests(unittest.TestCase):
    def test_positive_actions_map_to_set(self) -> None:
        for text in (
            "Open EV-101",
            "START the motor",
            "turn on pump",
            "energize relay",
            "activate output",
            "run conveyor",
        ):
            with self.subTest(text=text):
                self.assertEqual(action_text_to_coil_type(text), "set")

    def test_negative_actions_map_to_reset(self) -> None:
        for text in (
            "Close EV-101",
            "stop motor",
            "turn off pump",
            "de-energize relay",
            "deactivate output",
            "reset latch",
        ):
            with self.subTest(text=text):
                self.assertEqual(action_text_to_coil_type(text), "reset")

    def test_word_boundary_safety(self) -> None:
        self.assertEqual(action_text_to_coil_type("motion detected"), "normal")
        self.assertEqual(action_text_to_coil_type("office mode enabled"), "normal")
        self.assertEqual(action_text_to_coil_type("stoppedness is invalid"), "normal")

    def test_negated_actions_are_not_classified_positive(self) -> None:
        self.assertEqual(action_text_to_coil_type("do not open EV-101"), "normal")
        self.assertEqual(action_text_to_coil_type("must not start pump"), "normal")

    def test_sequence_classifier_uses_command_clause(self) -> None:
        ast = PLC_AST.model_validate_json(
            Path("data/ast/sample_control_api_AST_C.json").read_text(encoding="utf-8")
        )
        step = ast.sequence[0]
        self.assertEqual(action_text_to_coil_type(_sequence_action_text(step)), "reset")


class LDConditionSupportTests(unittest.TestCase):
    def test_simple_positive_and_builds_serial_contacts(self) -> None:
        ast = PLC_AST.model_validate_json(
            Path("data/ast/sample_control_api_AST_C.json").read_text(encoding="utf-8")
        )
        device_vars = _build_device_var_map(ast)
        contacts, notes = _build_contacts(
            "EV-101 is open AND EV-102 is open",
            [device.name for device in ast.devices],
            device_vars,
        )

        self.assertEqual([contact.variable for contact in contacts], ["EV_101", "EV_102"])
        self.assertEqual(notes, [])

    def test_unsupported_conditions_are_detected(self) -> None:
        cases = (
            "EV-101 is open OR EV-102 is open",
            "NOT EV-101 is open",
            "tank level reaches 80%",
            "5-second settling delay has elapsed",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(_unsupported_condition_reasons(text))


class LDSampleBehaviorTests(unittest.TestCase):
    def test_sample_sequence_and_ilk2_coil_semantics(self) -> None:
        ast_path = Path("data/ast/sample_control_api_AST_C.json")
        ast = PLC_AST.model_validate_json(ast_path.read_text(encoding="utf-8"))
        program = build_ld_program(ast, ast_path, ast_path.stem)
        networks = {network.network_id: network for network in program.networks}

        self.assertEqual([network.network_id for network in program.networks[:4]], [
            "SEQ-1",
            "SEQ-2",
            "SEQ-3",
            "SEQ-4",
        ])
        self.assertEqual(networks["SEQ-2"].coil.coil_type, "set")
        self.assertEqual(networks["SEQ-3"].coil.coil_type, "reset")
        self.assertEqual(networks["ILK-2_EV_101"].coil.coil_type, "reset")
        self.assertEqual(networks["ILK-2_EV_102"].coil.coil_type, "reset")


if __name__ == "__main__":
    unittest.main()
