from pathlib import Path
import unittest

from src.st_hybrid_schemas import (
    AnalogueIntent,
    ColourStateIntent,
    InterlockCodeIntent,
    SequenceCodeIntent,
    TimerIntent,
)
from src.ast_schemas import PLC_AST
from src.ld_ir_gen_hybrid import (
    build_hybrid_ld_program,
    load_ast,
)
from src.ld_ir_gen_llm_direct import validate_ld_structure


class HybridLDRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.signal_ast_path = Path("data/ast/signal_light_demo_api_AST_C.json")
        cls.control_ast_path = Path("data/ast/sample_control_api_AST_C.json")

    def _program_with_intents(self, ast_path, sequence_intents, interlock_intents):
        """Build a hybrid LD program with mock intents (no LLM calls)."""
        import src.ld_ir_gen_hybrid as mod

        def fake_collect(ast, backend):
            return sequence_intents, interlock_intents

        original = mod._collect_intents
        mod._collect_intents = fake_collect
        try:
            ast = load_ast(ast_path)
            program = build_hybrid_ld_program(ast, ast_path, "api")
        finally:
            mod._collect_intents = original
        return program

    def test_analogue_contact_carries_operator_and_threshold(self) -> None:
        program = self._program_with_intents(
            self.control_ast_path,
            {
                3: SequenceCodeIntent(
                    analogue_conditions=[
                        AnalogueIntent(
                            device="tank level sensor",
                            operator=">=",
                            threshold=80.0,
                            description="close filling valve at 80% level",
                        )
                    ]
                )
            },
            {},
        )
        networks = {n.network_id: n for n in program.networks}
        seq3 = networks["SEQ-3"]
        self.assertEqual(len(seq3.contacts), 1)
        self.assertEqual(seq3.contacts[0].variable, "tank_level_sensor")
        self.assertEqual(seq3.contacts[0].operator, ">=")
        self.assertEqual(seq3.contacts[0].threshold, 80.0)
        self.assertIn("Hybrid analogue condition", seq3.notes[0])

    def test_timer_metadata_rendered_on_network(self) -> None:
        program = self._program_with_intents(
            self.control_ast_path,
            {
                4: SequenceCodeIntent(
                    timers=[
                        TimerIntent(
                            duration_seconds=5, description="settling delay"
                        )
                    ]
                )
            },
            {},
        )
        networks = {n.network_id: n for n in program.networks}
        seq4 = networks["SEQ-4"]
        self.assertEqual(seq4.timer_duration_seconds, 5.0)
        self.assertEqual(seq4.timer_description, "settling delay")
        self.assertIn("Hybrid timer", seq4.notes[0])

    def test_colour_and_state_notes_on_interlock(self) -> None:
        program = self._program_with_intents(
            self.signal_ast_path,
            {
                1: SequenceCodeIntent(
                    colour_states=[
                        ColourStateIntent(device="SL-301", colour="green")
                    ]
                )
            },
            {
                1: InterlockCodeIntent(
                    colour_states=[
                        ColourStateIntent(device="SL-301", colour="red")
                    ],
                    state_notes=["must latch until reset"],
                )
            },
        )
        networks = {n.network_id: n for n in program.networks}
        self.assertTrue(
            any("SL-301 -> green" in note for note in networks["SEQ-1"].notes)
        )
        self.assertTrue(
            any("SL-301 -> red" in note for note in networks["ILK-1"].notes)
        )
        self.assertTrue(
            any("must latch until reset" in note for note in networks["ILK-1"].notes)
        )

    def test_hybrid_output_passes_structural_validation(self) -> None:
        for path, seq_intents in (
            (self.signal_ast_path, {1: SequenceCodeIntent()}),
            (
                self.control_ast_path,
                {
                    3: SequenceCodeIntent(
                        analogue_conditions=[
                            AnalogueIntent(
                                device="tank level sensor",
                                operator=">=",
                                threshold=80.0,
                            )
                        ]
                    ),
                    4: SequenceCodeIntent(
                        timers=[
                            TimerIntent(duration_seconds=5, description="delay")
                        ]
                    ),
                },
            ),
        ):
            with self.subTest(path=path.name):
                program = self._program_with_intents(path, seq_intents, {})
                # Deterministic hybrid output must satisfy the same structural
                # rules enforced on LLM-direct output.
                validate_ld_structure(program)
                self.assertTrue(program.networks)
                self.assertTrue(program.source_ast_file)

    def test_baseline_unsupported_condition_is_replaced_by_intent(self) -> None:
        # SEQ-3 "tank level reaches 80%" is an unsupported condition in the
        # deterministic baseline (empty contacts + TODO note). With hybrid
        # analogue intent it becomes a real comparison contact.
        program = self._program_with_intents(
            self.control_ast_path,
            {
                3: SequenceCodeIntent(
                    analogue_conditions=[
                        AnalogueIntent(
                            device="tank level sensor",
                            operator=">=",
                            threshold=80.0,
                        )
                    ]
                )
            },
            {},
        )
        seq3 = {n.network_id: n for n in program.networks}["SEQ-3"]
        self.assertEqual(len(seq3.contacts), 1)
        self.assertFalse(
            any("TODO_UNSUPPORTED" in note for note in seq3.notes)
        )


if __name__ == "__main__":
    unittest.main()
