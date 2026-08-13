from pathlib import Path
import unittest

from src.st_gen_hybrid import (
    _build_hybrid_sequence_block,
    _build_hybrid_interlock_block,
    _build_device_var_map,
    _parse_analogue_entry,
    _parse_colour_entry,
    _parse_timer_entry,
    _validate_sequence_intent,
    build_hybrid_st_program,
    render_st_program,
)
from src.st_hybrid_schemas import (
    AnalogueIntent,
    ColourStateIntent,
    InterlockCodeIntent,
    SequenceCodeIntent,
    TimerIntent,
)
from src.ast_schemas import PLC_AST


_DEVICES = {
    "SL-301",
    "start pushbutton",
    "Emergency Stop button",
    "tank level sensor",
    "EV-101",
    "EV-102",
}


class IntentNormalizationTests(unittest.TestCase):
    def test_colour_string_forms_parse(self) -> None:
        self.assertEqual(_parse_colour_entry("SL-301: green", _DEVICES)["colour"], "green")
        self.assertEqual(_parse_colour_entry("SL-301 -> red", _DEVICES)["colour"], "red")
        self.assertEqual(_parse_colour_entry("SL-301 turns green", _DEVICES)["colour"], "green")

    def test_colour_dict_passthrough(self) -> None:
        parsed = _parse_colour_entry({"device": "SL-301", "colour": "yellow"}, _DEVICES)
        self.assertEqual((parsed["device"], parsed["colour"]), ("SL-301", "yellow"))

    def test_colour_grounding_rejects_unknown_device(self) -> None:
        with self.assertRaises(ValueError):
            _parse_colour_entry("Halloween light -> orange", _DEVICES)

    def test_analogue_symbol_and_word_forms(self) -> None:
        symbol = _parse_analogue_entry("tank level sensor >= 80", _DEVICES)
        self.assertEqual((symbol["operator"], symbol["threshold"]), (">=", 80.0))
        word = _parse_analogue_entry("tank level sensor reaches 80", _DEVICES)
        self.assertEqual((word["operator"], word["threshold"]), (">=", 80.0))
        below = _parse_analogue_entry("tank level sensor drops below 20", _DEVICES)
        self.assertEqual((below["operator"], below["threshold"]), ("<=", 20.0))

    def test_timer_string_and_bare_number(self) -> None:
        unit = _parse_timer_entry("5s settling delay")
        self.assertEqual(unit["duration_seconds"], 5.0)
        hyphen = _parse_timer_entry("5-second settling delay")
        self.assertEqual(hyphen["duration_seconds"], 5.0)
        bare = _parse_timer_entry("5")
        self.assertEqual(bare["duration_seconds"], 5.0)


class HybridRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.signal_ast_path = Path("data/ast/signal_light_demo_api_AST_C.json")
        cls.control_ast_path = Path("data/ast/sample_control_api_AST_C.json")

    def test_analogue_device_is_declared_real(self) -> None:
        ast = PLC_AST.model_validate_json(self.control_ast_path.read_text(encoding="utf-8"))
        device_vars = _build_device_var_map(ast)
        intent = SequenceCodeIntent(
            analogue_conditions=[
                AnalogueIntent(device="tank level sensor", operator=">=", threshold=80.0)
            ]
        )
        ton_decls: list[str] = []
        block = _build_hybrid_sequence_block(
            ast.sequence[2], intent, [d.name for d in ast.devices], device_vars, ton_decls
        )
        self.assertIn("tank_level_sensor >= 80", block.code)
        self.assertIn("EV_101 := FALSE;", block.code)

    def test_timer_renders_ton_fb(self) -> None:
        ast = PLC_AST.model_validate_json(self.control_ast_path.read_text(encoding="utf-8"))
        device_vars = _build_device_var_map(ast)
        intent = SequenceCodeIntent(
            timers=[TimerIntent(duration_seconds=5, description="settling delay")]
        )
        ton_decls: list[str] = []
        block = _build_hybrid_sequence_block(
            ast.sequence[3], intent, [d.name for d in ast.devices], device_vars, ton_decls
        )
        self.assertEqual(ton_decls, ["TON_4_1 : TON; // hybrid timer: settling delay"])
        self.assertIn("TON_4_1(IN := TRUE, PT := T#5s);", block.code)
        self.assertIn("IF TON_4_1.Q THEN", block.code)
        self.assertIn("EV_102 := TRUE;", block.code)

    def test_colour_intent_emits_review_comment(self) -> None:
        ast = PLC_AST.model_validate_json(self.signal_ast_path.read_text(encoding="utf-8"))
        device_vars = _build_device_var_map(ast)
        intent = SequenceCodeIntent(
            colour_states=[ColourStateIntent(device="SL-301", colour="green")]
        )
        ton_decls: list[str] = []
        block = _build_hybrid_sequence_block(
            ast.sequence[0], intent, [d.name for d in ast.devices], device_vars, ton_decls
        )
        self.assertIn("SL-301 -> green", block.code)
        self.assertIn("enumerated colour variable", block.code)

    def test_interlock_colour_intent(self) -> None:
        ast = PLC_AST.model_validate_json(self.signal_ast_path.read_text(encoding="utf-8"))
        device_vars = _build_device_var_map(ast)
        intent = InterlockCodeIntent(
            colour_states=[ColourStateIntent(device="SL-301", colour="red")]
        )
        block = _build_hybrid_interlock_block(
            ast.interlocks[0], intent, [d.name for d in ast.devices], device_vars
        )
        self.assertIn("SL-301 -> red", block.code)
        self.assertIn("IF Emergency_Stop_button THEN", block.code)

    def test_grounding_failure_on_unknown_intent_device(self) -> None:
        args = {
            "colour_states": [{"device": "Halloween light", "colour": "green"}],
        }
        with self.assertRaises(ValueError):
            _validate_sequence_intent(args, _DEVICES, 1)

    def test_hybrid_program_with_mock_intents(self) -> None:
        # Monkeypatch intent collection so the test stays fully deterministic
        # (no LLM calls) while exercising the full build + render path.
        import src.st_gen_hybrid as mod

        def fake_collect(ast, backend):
            seq = {
                1: SequenceCodeIntent(
                    colour_states=[ColourStateIntent(device="SL-301", colour="green")]
                ),
            }
            ilk = {
                1: InterlockCodeIntent(
                    colour_states=[ColourStateIntent(device="SL-301", colour="red")]
                ),
            }
            return seq, ilk

        original = mod._collect_intents
        mod._collect_intents = fake_collect
        try:
            ast = PLC_AST.model_validate_json(self.signal_ast_path.read_text(encoding="utf-8"))
            program = build_hybrid_st_program(ast, self.signal_ast_path, "api")
            text = render_st_program(program)
        finally:
            mod._collect_intents = original

        self.assertIn("PROGRAM Signal_light_control_and_safety_interlocks", text)
        self.assertIn("SL-301 -> green", text)
        self.assertIn("SL-301 -> red", text)
        self.assertIn("END_PROGRAM", text)


if __name__ == "__main__":
    unittest.main()
