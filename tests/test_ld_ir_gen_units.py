"""Unit tests for src/ld_ir_gen.py (E3S3T2).

Extends the existing tests/test_ld_ir_gen.py (action classification, contact
building, sample behaviour) with unit coverage for the remaining deterministic
surface: term/negation matching, sequence action text extraction, unsupported
condition detection, device-var mapping, placeholder coils, sequence/interlock
network construction, multi-target split networks, and the full program build.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import src.ld_ir_gen as ld_ir_gen
from src.ast_schemas import (
    DeviceNode,
    InterlockNode,
    PLC_AST,
    SequenceStepNode,
)


def make_ast(
    sequence: list[SequenceStepNode],
    interlocks: list[InterlockNode],
    feature_title: str = "Signal light control",
    devices: list[DeviceNode] | None = None,
) -> PLC_AST:
    if devices is None:
        devices = [
            DeviceNode(node_id="DEV-SL-301", name="SL-301", device_type="Signal Light", source_equipment="SL-301"),
            DeviceNode(node_id="DEV-PB-101", name="PB-101", device_type="Pushbutton", source_equipment="PB-101"),
        ]
    return PLC_AST(
        feature_title=feature_title,
        devices=devices,
        sequence=sequence,
        interlocks=interlocks,
    )


class TermMatchingTests(unittest.TestCase):
    def test_has_action_term_matches_with_boundaries(self) -> None:
        self.assertTrue(ld_ir_gen._has_action_term("open EV-101", "open"))
        self.assertFalse(ld_ir_gen._has_action_term("reopen EV-101", "open"))
        self.assertFalse(ld_ir_gen._has_action_term("openers are present", "open"))

    def test_has_action_term_matches_multi_word_terms(self) -> None:
        self.assertTrue(ld_ir_gen._has_action_term("switch to green", "switch to"))
        self.assertFalse(ld_ir_gen._has_action_term("switchback to green", "switch to"))

    def test_negated_action_is_detected(self) -> None:
        self.assertTrue(ld_ir_gen._has_negated_action("do not open EV-101", "open"))
        self.assertTrue(ld_ir_gen._has_negated_action("must not start pump", "start"))
        self.assertFalse(ld_ir_gen._has_negated_action("open EV-101", "open"))


class SequenceActionTextTests(unittest.TestCase):
    def _step(self, action: str) -> SequenceStepNode:
        return SequenceStepNode(
            node_id="SEQ-1",
            step_id=1,
            action=action,
            target_device=None,
            source_step_id=1,
        )

    def test_command_clause_after_trigger_is_extracted(self) -> None:
        step = self._step("When the operator presses start, SL-301 turns green")
        self.assertEqual(
            ld_ir_gen._sequence_action_text(step), "SL-301 turns green"
        )

    def test_if_clause_is_stripped(self) -> None:
        step = self._step("If the tank is full, stop the pump")
        self.assertEqual(ld_ir_gen._sequence_action_text(step), "stop the pump")

    def test_plain_action_is_returned_unchanged(self) -> None:
        step = self._step("SL-301 turns green")
        self.assertEqual(ld_ir_gen._sequence_action_text(step), "SL-301 turns green")

    def test_trigger_without_comma_is_returned_unchanged(self) -> None:
        step = self._step("When the sequence completes")
        self.assertEqual(ld_ir_gen._sequence_action_text(step), "When the sequence completes")


class UnsupportedConditionTests(unittest.TestCase):
    def _has_reason(self, notes: list[str], fragment: str) -> bool:
        return any(fragment in note for note in notes)

    def test_or_expression_is_flagged(self) -> None:
        reasons = ld_ir_gen._unsupported_condition_reasons("EV-101 open OR EV-102 open")
        self.assertTrue(self._has_reason(reasons, "OR expressions are not supported"))

    def test_negated_condition_is_flagged(self) -> None:
        reasons = ld_ir_gen._unsupported_condition_reasons("NOT EV-101 is open")
        self.assertTrue(self._has_reason(reasons, "negated contact conditions are not supported"))

    def test_analogue_comparison_is_flagged(self) -> None:
        reasons = ld_ir_gen._unsupported_condition_reasons("tank level reaches 80%")
        self.assertTrue(self._has_reason(reasons, "numeric comparisons or analogue thresholds are not supported"))

    def test_timer_condition_is_flagged(self) -> None:
        reasons = ld_ir_gen._unsupported_condition_reasons("5-second settling delay has elapsed")
        self.assertTrue(self._has_reason(reasons, "timer or duration conditions are not supported"))

    def test_clean_condition_has_no_reasons(self) -> None:
        reasons = ld_ir_gen._unsupported_condition_reasons("PB-101 is pressed")
        self.assertEqual(reasons, [])

    def test_empty_condition_has_no_reasons(self) -> None:
        self.assertEqual(ld_ir_gen._unsupported_condition_reasons(""), [])
        self.assertEqual(ld_ir_gen._unsupported_condition_reasons(None), [])


class DeviceVarMapTests(unittest.TestCase):
    def test_sanitizes_and_disambiguates(self) -> None:
        ast = make_ast(
            sequence=[],
            interlocks=[],
            devices=[
                DeviceNode(node_id="DEV-A-B", name="A-B", device_type="X", source_equipment="A-B"),
                DeviceNode(node_id="DEV-A!B", name="A!B", device_type="X", source_equipment="A!B"),
            ],
        )
        mapping = ld_ir_gen._build_device_var_map(ast)
        self.assertEqual(mapping, {"A-B": "A_B", "A!B": "A_B_2"})


class PlaceholderCoilTests(unittest.TestCase):
    def test_sequence_placeholder_name(self) -> None:
        coil = ld_ir_gen._placeholder_sequence_coil("SEQ-1")
        self.assertEqual(coil.variable, "TODO_UNMAPPED_TARGET_SEQ_1")
        self.assertEqual(coil.coil_type, "normal")

    def test_interlock_placeholder_preserves_coil_type(self) -> None:
        coil = ld_ir_gen._placeholder_interlock_coil("ILK-2", "reset")
        self.assertEqual(coil.variable, "TODO_UNMAPPED_INTERLOCK_TARGET_ILK_2")
        self.assertEqual(coil.coil_type, "reset")


class BuildSequenceNetworkTests(unittest.TestCase):
    def test_known_target_builds_real_coil(self) -> None:
        step = SequenceStepNode(
            node_id="SEQ-1",
            step_id=1,
            action="When the operator presses start, SL-301 turns on",
            target_device="SL-301",
            condition="PB-101 is pressed",
            source_step_id=1,
            source_scenario="Operator starts the system",
        )
        ast = make_ast(sequence=[step], interlocks=[])
        vars_ = ld_ir_gen._build_device_var_map(ast)
        network = ld_ir_gen._build_sequence_network(
            step, [d.name for d in ast.devices], vars_
        )
        self.assertEqual(network.network_id, "SEQ-1")
        self.assertEqual(network.coil.variable, "SL_301")
        self.assertIn("set", network.coil.coil_type)  # 'turns on' -> set
        self.assertEqual(network.source_step_id, 1)
        self.assertEqual(network.contacts[0].variable, "PB_101")

    def test_missing_target_builds_placeholder_coil(self) -> None:
        step = SequenceStepNode(
            node_id="SEQ-1",
            step_id=1,
            action="run the process",
            target_device=None,
            condition=None,
            source_step_id=1,
        )
        ast = make_ast(sequence=[step], interlocks=[])
        network = ld_ir_gen._build_sequence_network(
            step, [d.name for d in ast.devices], ld_ir_gen._build_device_var_map(ast)
        )
        self.assertEqual(network.coil.variable, "TODO_UNMAPPED_TARGET_SEQ_1")
        self.assertEqual(network.contacts, [])

    def test_unsupported_condition_emits_notes(self) -> None:
        step = SequenceStepNode(
            node_id="SEQ-1",
            step_id=1,
            action="start pump",
            target_device="SL-301",
            condition="level reaches 80%",
            source_step_id=1,
        )
        ast = make_ast(sequence=[step], interlocks=[])
        network = ld_ir_gen._build_sequence_network(
            step, [d.name for d in ast.devices], ld_ir_gen._build_device_var_map(ast)
        )
        self.assertEqual(network.contacts, [])
        self.assertTrue(any("TODO_UNSUPPORTED_CONDITION" in note for note in network.notes))


class InterlockTargetsTests(unittest.TestCase):
    def test_affected_not_in_condition_are_targeted(self) -> None:
        interlock = InterlockNode(
            node_id="ILK-1",
            condition="ES-1 is pressed",
            forced_action="close EV-101",
            affected_devices=["EV-101"],
            priority=1,
            source_interlock_condition="ES-1 is pressed",
        )
        devices = [
            DeviceNode(node_id="DEV-EV-101", name="EV-101", device_type="Valve", source_equipment="EV-101"),
            DeviceNode(node_id="DEV-ES-1", name="ES-1", device_type="EStop", source_equipment="ES-1"),
        ]
        ast = make_ast(sequence=[], interlocks=[interlock], devices=devices)
        targets = ld_ir_gen._interlock_targets(
            interlock, [d.name for d in ast.devices], ld_ir_gen._build_device_var_map(ast)
        )
        self.assertEqual(targets, ["EV-101"])

    def test_all_affected_when_everyone_in_condition(self) -> None:
        interlock = InterlockNode(
            node_id="ILK-1",
            condition="EV-101 is stuck",
            forced_action="close EV-101",
            affected_devices=["EV-101"],
            priority=1,
            source_interlock_condition="EV-101 is stuck",
        )
        devices = [DeviceNode(node_id="DEV-EV-101", name="EV-101", device_type="Valve", source_equipment="EV-101")]
        ast = make_ast(sequence=[], interlocks=[interlock], devices=devices)
        targets = ld_ir_gen._interlock_targets(
            interlock, [d.name for d in ast.devices], ld_ir_gen._build_device_var_map(ast)
        )
        self.assertEqual(targets, ["EV-101"])


class BuildInterlockNetworksTests(unittest.TestCase):
    def test_single_target_keeps_bare_network_id(self) -> None:
        interlock = InterlockNode(
            node_id="ILK-1",
            condition="ES-1 is pressed",
            forced_action="close EV-101",
            affected_devices=["EV-101"],
            priority=2,
            source_interlock_condition="ES-1 is pressed",
        )
        devices = [
            DeviceNode(node_id="DEV-EV-101", name="EV-101", device_type="Valve", source_equipment="EV-101"),
            DeviceNode(node_id="DEV-ES-1", name="ES-1", device_type="EStop", source_equipment="ES-1"),
        ]
        ast = make_ast(sequence=[], interlocks=[interlock], devices=devices)
        networks = ld_ir_gen._build_interlock_networks(
            interlock, [d.name for d in ast.devices], ld_ir_gen._build_device_var_map(ast)
        )
        self.assertEqual(len(networks), 1)
        self.assertEqual(networks[0].network_id, "ILK-1")
        self.assertEqual(networks[0].coil.variable, "EV_101")
        self.assertEqual(networks[0].coil.coil_type, "reset")
        self.assertEqual(networks[0].priority, 2)
        self.assertEqual(networks[0].source_interlock_condition, "ES-1 is pressed")

    def test_multi_target_splits_into_one_network_per_target(self) -> None:
        interlock = InterlockNode(
            node_id="ILK-1",
            condition="ES-1 is pressed",
            forced_action="close EV-101 and EV-102",
            affected_devices=["EV-101", "EV-102"],
            priority=1,
            source_interlock_condition="ES-1 is pressed",
        )
        devices = [
            DeviceNode(node_id="DEV-ES-1", name="ES-1", device_type="EStop", source_equipment="ES-1"),
            DeviceNode(node_id="DEV-EV-101", name="EV-101", device_type="Valve", source_equipment="EV-101"),
            DeviceNode(node_id="DEV-EV-102", name="EV-102", device_type="Valve", source_equipment="EV-102"),
        ]
        ast = make_ast(sequence=[], interlocks=[interlock], devices=devices)
        networks = ld_ir_gen._build_interlock_networks(
            interlock, [d.name for d in ast.devices], ld_ir_gen._build_device_var_map(ast)
        )
        self.assertEqual(len(networks), 2)
        ids = {network.network_id for network in networks}
        self.assertEqual(ids, {"ILK-1_EV_101", "ILK-1_EV_102"})
        self.assertEqual({n.coil.variable for n in networks}, {"EV_101", "EV_102"})

    def test_no_target_emits_placeholder_network(self) -> None:
        interlock = InterlockNode(
            node_id="ILK-1",
            condition="hazard present",
            forced_action="stop everything",
            affected_devices=[],
            priority=1,
            source_interlock_condition="hazard present",
        )
        ast = make_ast(sequence=[], interlocks=[interlock])
        networks = ld_ir_gen._build_interlock_networks(
            interlock, [d.name for d in ast.devices], ld_ir_gen._build_device_var_map(ast)
        )
        self.assertEqual(len(networks), 1)
        self.assertTrue(networks[0].coil.variable.startswith("TODO_UNMAPPED_INTERLOCK_TARGET"))


class BuildLdProgramTests(unittest.TestCase):
    def test_program_name_from_feature_title_or_fallback(self) -> None:
        ast = make_ast(sequence=[], interlocks=[], feature_title="Light Demo")
        program = ld_ir_gen.build_ld_program(ast, Path("data/ast/x.json"), "fallback")
        self.assertEqual(program.program_name, "Light_Demo")

        ast_blank = make_ast(sequence=[], interlocks=[], feature_title="   ")
        program_blank = ld_ir_gen.build_ld_program(ast_blank, Path("data/ast/x.json"), "fallback")
        self.assertEqual(program_blank.program_name, "fallback")

    def test_sequence_networks_precede_interlock_networks(self) -> None:
        ast = make_ast(
            sequence=[
                SequenceStepNode(
                    node_id="SEQ-1",
                    step_id=1,
                    action="turn on SL-301",
                    target_device="SL-301",
                    condition="PB-101 is pressed",
                    source_step_id=1,
                )
            ],
            interlocks=[
                InterlockNode(
                    node_id="ILK-1",
                    condition="PB-101 is pressed",
                    forced_action="turn off SL-301",
                    affected_devices=["SL-301"],
                    priority=1,
                    source_interlock_condition="PB-101 is pressed",
                )
            ],
        )
        program = ld_ir_gen.build_ld_program(ast, Path("data/ast/x.json"), "x")
        network_ids = [network.network_id for network in program.networks]
        # Single interlock target keeps the bare network_id.
        self.assertEqual(network_ids, ["SEQ-1", "ILK-1"])

    def test_write_ld_file_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ast_path = Path(tmp) / "demo.json"
            ast = make_ast(sequence=[], interlocks=[])
            ast_path.write_text(ast.model_dump_json(), encoding="utf-8")
            output_path, program = ld_ir_gen.write_ld_file(ast_path, Path(tmp) / "out")
            self.assertTrue(output_path.is_file())
            self.assertEqual(output_path.name, "demo_ld.json")
            self.assertEqual(program.source_ast_file, str(ast_path.resolve()))


if __name__ == "__main__":
    unittest.main()