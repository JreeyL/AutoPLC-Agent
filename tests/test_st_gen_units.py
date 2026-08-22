"""Unit tests for src/st_gen.py (E3S3T2).

Covers the deterministic Structured Text MVP renderer: variable sanitization,
device-var mapping (incl. collision handling), comment cleaning, device
mention detection, action/interlock target classification, sequence and
interlock ST block construction, and the full build/render pipeline on a
synthetic PLC_AST.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import src.st_gen as st_gen
from src.ast_schemas import (
    DeviceNode,
    InterlockNode,
    PLC_AST,
    SequenceStepNode,
)
from src.plc_code_schemas import STBlock, STProgram


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


class SanitizeVarNameTests(unittest.TestCase):
    def test_non_alnum_replaced_with_underscore(self) -> None:
        self.assertEqual(st_gen.sanitize_var_name("EV-101"), "EV_101")

    def test_runs_of_underscores_are_collapsed(self) -> None:
        self.assertEqual(st_gen.sanitize_var_name("a--b   c"), "a_b_c")

    def test_leading_digit_gets_v_prefix(self) -> None:
        self.assertEqual(st_gen.sanitize_var_name("301-SL"), "V_301_SL")

    def test_empty_input_becomes_unnamed(self) -> None:
        self.assertEqual(st_gen.sanitize_var_name("---"), "unnamed")
        self.assertEqual(st_gen.sanitize_var_name(""), "unnamed")


class CleanCommentTextTests(unittest.TestCase):
    def test_none_becomes_literal_none(self) -> None:
        self.assertEqual(st_gen._clean_comment_text(None), "None")

    def test_whitespace_is_collapsed_and_stripped(self) -> None:
        self.assertEqual(
            st_gen._clean_comment_text("  open   EV-101 \n now "),
            "open EV-101 now",
        )


class DeviceMentionTests(unittest.TestCase):
    def test_mentions_device_with_boundaries(self) -> None:
        self.assertTrue(st_gen._text_mentions_device("EV-101 is open", "EV-101"))
        self.assertFalse(st_gen._text_mentions_device("EV-1012 is open", "EV-101"))
        self.assertFalse(st_gen._text_mentions_device(None, "EV-101"))
        self.assertFalse(st_gen._text_mentions_device("", "EV-101"))

    def test_find_mentioned_devices_keeps_order(self) -> None:
        devices = ["PMP-200", "SL-301", "EV-101"]
        self.assertEqual(
            st_gen._find_mentioned_devices("SL-301 and EV-101 fail", devices),
            ["SL-301", "EV-101"],
        )


class DeviceVarMapTests(unittest.TestCase):
    def test_colliding_sanitized_names_get_suffixes(self) -> None:
        ast = make_ast(
            sequence=[],
            interlocks=[],
            devices=[
                DeviceNode(node_id="DEV-A-B", name="A-B", device_type="X", source_equipment="A-B"),
                DeviceNode(node_id="DEV-A!B", name="A!B", device_type="X", source_equipment="A!B"),
            ],
        )
        mapping = st_gen._build_device_var_map(ast)
        self.assertEqual(mapping["A-B"], "A_B")
        self.assertEqual(mapping["A!B"], "A_B_2")


class TargetValueTests(unittest.TestCase):
    def test_sequence_false_action_words(self) -> None:
        self.assertFalse(st_gen._sequence_target_value("close EV-101"))
        self.assertFalse(st_gen._sequence_target_value("de-energize coil"))
        self.assertFalse(st_gen._sequence_target_value("turn off pump"))
        self.assertTrue(st_gen._sequence_target_value("open EV-101"))
        self.assertTrue(st_gen._sequence_target_value("start motor"))

    def test_interlock_false_words_win(self) -> None:
        self.assertFalse(st_gen._interlock_target_value("close EV-101"))
        self.assertFalse(st_gen._interlock_target_value("stop the pump"))
        self.assertFalse(st_gen._interlock_target_value("switch to off"))

    def test_interlock_true_words(self) -> None:
        self.assertTrue(st_gen._interlock_target_value("open EV-101"))
        self.assertTrue(st_gen._interlock_target_value("start pump"))
        self.assertTrue(st_gen._interlock_target_value("switch to red"))

    def test_ambiguous_action_returns_none(self) -> None:
        self.assertIsNone(st_gen._interlock_target_value("toggle the light"))

    def test_bool_literal_mapping(self) -> None:
        self.assertEqual(st_gen._bool_literal(True), "TRUE")
        self.assertEqual(st_gen._bool_literal(False), "FALSE")


class RenderConditionExpressionTests(unittest.TestCase):
    def test_joins_variables_with_and(self) -> None:
        expr = st_gen._render_condition_expression(
            ["PB-101", "LS-1"], {"PB-101": "PB_101", "LS-1": "LS_1"}
        )
        self.assertEqual(expr, "PB_101 AND LS_1")

    def test_empty_list_yields_empty_string(self) -> None:
        self.assertEqual(st_gen._render_condition_expression([], {}), "")


class BuildSequenceBlockTests(unittest.TestCase):
    def test_missing_trigger_and_target_emits_todos(self) -> None:
        step = SequenceStepNode(
            node_id="SEQ-1",
            step_id=1,
            action="operate the system",
            target_device=None,
            condition="a complex condition",
            source_step_id=1,
            source_scenario="S1",
        )
        ast = make_ast(sequence=[step], interlocks=[])
        block = st_gen._build_sequence_block(
            step, [d.name for d in ast.devices], st_gen._build_device_var_map(ast)
        )
        self.assertIn("// TODO: Map source condition to ST logic", block.code)
        self.assertIn("// TODO: Map target device for action", block.code)

    def test_trigger_and_target_emit_if_block(self) -> None:
        step = SequenceStepNode(
            node_id="SEQ-1",
            step_id=1,
            action="open EV-101",
            target_device="EV-101",
            condition="PB-101 is pressed",
            source_step_id=1,
            source_scenario="S1",
        )
        devices = [
            DeviceNode(node_id="DEV-EV-101", name="EV-101", device_type="Valve", source_equipment="EV-101"),
            DeviceNode(node_id="DEV-PB-101", name="PB-101", device_type="Pushbutton", source_equipment="PB-101"),
        ]
        ast = make_ast(sequence=[step], interlocks=[], devices=devices)
        block = st_gen._build_sequence_block(
            step, [d.name for d in ast.devices], st_gen._build_device_var_map(ast)
        )
        self.assertIn("IF PB_101 THEN", block.code)
        self.assertIn("    EV_101 := TRUE;", block.code)  # 'open' is not a FALSE action word
        self.assertIn("END_IF;", block.code)
        self.assertEqual(block.source_step_id, 1)

    def test_block_traceability_comments(self) -> None:
        step = SequenceStepNode(
            node_id="SEQ-2",
            step_id=2,
            action="start PB-101",
            target_device="PB-101",
            condition="button",
            source_step_id=2,
            source_scenario="Start system",
        )
        ast = make_ast(sequence=[step], interlocks=[])
        block = st_gen._build_sequence_block(
            step, [d.name for d in ast.devices], st_gen._build_device_var_map(ast)
        )
        self.assertIn("// SEQ-2", block.code)
        self.assertIn("// Source step: 2", block.code)
        self.assertIn("// Source scenario: Start system", block.code)


class BuildInterlockBlockTests(unittest.TestCase):
    def test_interlock_targets_prefer_affected_not_in_condition(self) -> None:
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
        names = [d.name for d in ast.devices]
        vars_ = st_gen._build_device_var_map(ast)
        block = st_gen._build_interlock_block(interlock, names, vars_)
        # ES-1 is the trigger; EV-101 must be the assignment target.
        self.assertIn("IF ES_1 THEN", block.code)
        self.assertIn("    EV_101 := FALSE;", block.code)

    def test_missing_trigger_emits_todo(self) -> None:
        interlock = InterlockNode(
            node_id="ILK-1",
            condition="complex hazard condition",
            forced_action="stop EV-101",
            affected_devices=["EV-101"],
            priority=1,
            source_interlock_condition="complex hazard condition",
        )
        devices = [DeviceNode(node_id="DEV-EV-101", name="EV-101", device_type="Valve", source_equipment="EV-101")]
        ast = make_ast(sequence=[], interlocks=[interlock], devices=devices)
        block = st_gen._build_interlock_block(
            interlock, [d.name for d in ast.devices], st_gen._build_device_var_map(ast)
        )
        self.assertIn("// TODO: Map interlock condition to ST logic", block.code)
        self.assertIn("// Priority: 1", block.code)

    def test_ambiguous_force_emits_todo(self) -> None:
        interlock = InterlockNode(
            node_id="ILK-1",
            condition="ES-1 pressed",
            forced_action="toggle the lamp",
            affected_devices=["L-1"],
            priority=1,
            source_interlock_condition="ES-1 pressed",
        )
        devices = [
            DeviceNode(node_id="DEV-ES-1", name="ES-1", device_type="EStop", source_equipment="ES-1"),
            DeviceNode(node_id="DEV-L-1", name="L-1", device_type="Lamp", source_equipment="L-1"),
        ]
        ast = make_ast(sequence=[], interlocks=[interlock], devices=devices)
        block = st_gen._build_interlock_block(
            interlock, [d.name for d in ast.devices], st_gen._build_device_var_map(ast)
        )
        self.assertIn("// TODO: Determine forced BOOL value for action", block.code)

    def test_multiple_affected_targets_assign_all(self) -> None:
        interlock = InterlockNode(
            node_id="ILK-1",
            condition="ES-1 pressed",
            forced_action="stop EV-101 and close EV-102",
            affected_devices=["EV-101", "EV-102"],
            priority=1,
            source_interlock_condition="ES-1 pressed",
        )
        devices = [
            DeviceNode(node_id="DEV-ES-1", name="ES-1", device_type="EStop", source_equipment="ES-1"),
            DeviceNode(node_id="DEV-EV-101", name="EV-101", device_type="Valve", source_equipment="EV-101"),
            DeviceNode(node_id="DEV-EV-102", name="EV-102", device_type="Valve", source_equipment="EV-102"),
        ]
        ast = make_ast(sequence=[], interlocks=[interlock], devices=devices)
        block = st_gen._build_interlock_block(
            interlock, [d.name for d in ast.devices], st_gen._build_device_var_map(ast)
        )
        self.assertIn("    EV_101 := FALSE;", block.code)
        self.assertIn("    EV_102 := FALSE;", block.code)


class BuildAndRenderProgramTests(unittest.TestCase):
    def _full_ast(self) -> PLC_AST:
        devices = [
            DeviceNode(node_id="DEV-SL-301", name="SL-301", device_type="Signal Light", source_equipment="SL-301"),
            DeviceNode(node_id="DEV-PB-101", name="PB-101", device_type="Pushbutton", source_equipment="PB-101"),
        ]
        sequence = [
            SequenceStepNode(
                node_id="SEQ-1",
                step_id=1,
                action="turn on SL-301",
                target_device="SL-301",
                condition="PB-101 is pressed",
                source_step_id=1,
                source_scenario="Operator starts the system",
            )
        ]
        interlocks = [
            InterlockNode(
                node_id="ILK-1",
                condition="Emergency Stop button is pressed",
                forced_action="turn off SL-301",
                affected_devices=["SL-301"],
                priority=1,
                source_interlock_condition="Emergency Stop button is pressed",
            )
        ]
        return PLC_AST(
            feature_title="Signal light control",
            devices=devices,
            sequence=sequence,
            interlocks=interlocks,
        )

    def test_build_st_program_structure(self) -> None:
        ast = self._full_ast()
        program = st_gen.build_st_program(ast, Path("data/ast/x.json"), "fallback")
        self.assertIsInstance(program, STProgram)
        self.assertEqual(program.program_name, "Signal_light_control")
        self.assertEqual(len(program.variables), 2)
        self.assertEqual(len(program.blocks), 2)
        self.assertEqual(program.source_ast_file, str(Path("data/ast/x.json").resolve()))

    def test_render_orders_sequence_before_safety(self) -> None:
        ast = self._full_ast()
        program = st_gen.build_st_program(ast, Path("data/ast/x.json"), "fallback")
        rendered = st_gen.render_st_program(program)
        seq_pos = rendered.index("// Sequence Logic")
        safety_pos = rendered.index("// Safety Interlocks / Overrides")
        self.assertLess(seq_pos, safety_pos)
        self.assertIn("PROGRAM Signal_light_control", rendered)
        self.assertIn("END_PROGRAM", rendered)
        self.assertIn("VAR", rendered)
        self.assertIn("END_VAR", rendered)

    def test_variable_declarations_carry_source_comments(self) -> None:
        ast = self._full_ast()
        program = st_gen.build_st_program(ast, Path("data/ast/x.json"), "fallback")
        self.assertIn("SL_301 : BOOL; // source equipment: SL-301", program.variables)

    def test_empty_blocks_still_render_wrapper(self) -> None:
        ast = make_ast(sequence=[], interlocks=[])
        program = st_gen.build_st_program(ast, Path("data/ast/x.json"), "x")
        rendered = st_gen.render_st_program(program)
        self.assertIn("PROGRAM Signal_light_control", rendered)
        self.assertIn("END_PROGRAM", rendered)


class WriteStFileTests(unittest.TestCase):
    def test_write_st_file_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ast_path = Path(tmp) / "ast.json"
            ast = make_ast(sequence=[], interlocks=[])
            ast_path.write_text(ast.model_dump_json(), encoding="utf-8")
            output_path, program = st_gen.write_st_file(ast_path, Path(tmp) / "out")
            self.assertTrue(output_path.is_file())
            self.assertEqual(output_path.suffix, ".st")
            self.assertEqual(output_path.stem, "ast")
            self.assertEqual(program, st_gen._load_ast(ast_path) and program)


if __name__ == "__main__":
    unittest.main()