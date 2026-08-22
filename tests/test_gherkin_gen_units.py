"""Unit tests for src/gherkin_gen.py (E3S3T2).

Covers the deterministic surface of the E2S2 Gherkin generator: content-word
tokenization, the fabricated-given backstop, the pure .feature renderer,
path resolution, requirement loading (including fatal paths), and per-item
scenario conversion provenance stamping with a fake structured LLM.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import src.gherkin_gen as gherkin_gen
from src.gherkin_schemas import GherkinFeature, GherkinScenario
from src.schemas import ControlSequence, Interlock


class ContentWordsTests(unittest.TestCase):
    def test_short_filler_words_are_filtered(self) -> None:
        self.assertNotIn("is", gherkin_gen._content_words("the light is green"))
        self.assertNotIn("the", gherkin_gen._content_words("the light is green"))

    def test_meaningful_words_are_kept_lowercased(self) -> None:
        words = gherkin_gen._content_words("The Signal Light Turns GREEN")
        self.assertIn("signal", words)
        self.assertIn("green", words)

    def test_hyphenated_tokens_survive(self) -> None:
        words = gherkin_gen._content_words("open EV-101 valve")
        self.assertIn("ev-101", words)

    def test_empty_text_yields_empty_set(self) -> None:
        self.assertEqual(gherkin_gen._content_words("   "), set())


class FlagUnsupportedGivenTests(unittest.TestCase):
    def _scenario(self, given: list[str]) -> GherkinScenario:
        return GherkinScenario(
            name="Scenario A", given=given, when=[], then=[]
        )

    def test_equipment_name_grounding_keeps_entry(self) -> None:
        scenario = self._scenario(["the operator presses the start pushbutton"])
        gherkin_gen.flag_unsupported_given(
            scenario,
            source_text="Operator starts the system",
            equipment_names=["SL-301", "Start Pushbutton"],
        )
        self.assertEqual(len(scenario.given), 1)

    def test_content_word_overlap_keeps_entry_without_equipment(self) -> None:
        scenario = self._scenario(["the pump is stopped"])
        gherkin_gen.flag_unsupported_given(
            scenario,
            source_text="pump PMP-200 stops after the tank empties",
            equipment_names=["SL-301"],
        )
        self.assertEqual(len(scenario.given), 1)

    def test_ungrounded_generic_entry_is_dropped(self) -> None:
        scenario = self._scenario(["the system is ready"])
        gherkin_gen.flag_unsupported_given(
            scenario,
            source_text="pump PMP-200 starts when the tank is full",
            equipment_names=["PMP-200"],
        )
        self.assertEqual(scenario.given, [])

    def test_empty_entry_is_left_untouched(self) -> None:
        scenario = self._scenario(["", "  "])
        gherkin_gen.flag_unsupported_given(
            scenario,
            source_text="nothing in common here",
            equipment_names=[],
        )
        self.assertEqual(scenario.given, ["", "  "])

    def test_whitespace_padded_grounded_entry_is_kept(self) -> None:
        scenario = self._scenario(["  SL-301 is green  "])
        gherkin_gen.flag_unsupported_given(
            scenario,
            source_text="SL-301 turns green",
            equipment_names=["SL-301"],
        )
        self.assertEqual(scenario.given, ["  SL-301 is green  "])


class RenderFeatureTests(unittest.TestCase):
    def _feature_with(self, scenario: GherkinScenario) -> GherkinFeature:
        return GherkinFeature(
            title="Signal light control",
            description="Manages the signal light.",
            scenarios=[scenario],
        )

    def test_header_and_description_lines(self) -> None:
        feature = self._feature_with(
            GherkinScenario(name="S1", given=[], when=["x"], then=["y"])
        )
        rendered = gherkin_gen.render_feature(feature)
        lines = rendered.splitlines()
        self.assertEqual(lines[0], "Feature: Signal light control")
        self.assertEqual(lines[1], "  Manages the signal light.")
        self.assertTrue(rendered.endswith("\n"))

    def test_keyword_sequence_with_and_for_subsequent_steps(self) -> None:
        feature = self._feature_with(
            GherkinScenario(
                name="S1",
                given=["a", "b"],
                when=["c"],
                then=["d", "e", "f"],
            )
        )
        rendered = gherkin_gen.render_feature(feature)
        self.assertIn("    Given a\n    And b\n", rendered)
        self.assertIn("    When c\n", rendered)
        self.assertIn("    Then d\n    And e\n    And f\n", rendered)

    def test_empty_and_whitespace_steps_are_filtered(self) -> None:
        feature = self._feature_with(
            GherkinScenario(
                name="S1",
                given=["", "real given"],
                when=["  "],
                then=["real then"],
            )
        )
        rendered = gherkin_gen.render_feature(feature)
        self.assertNotIn("Given ", rendered.split("When")[0].replace(
            "    Given real given\n", ""
        ))
        self.assertNotIn("When ", rendered)
        self.assertIn("    Given real given\n", rendered)
        self.assertIn("    Then real then\n", rendered)

    def test_multiple_scenarios_are_kept_ordered(self) -> None:
        feature = GherkinFeature(
            title="T",
            description="D",
            scenarios=[
                GherkinScenario(name="First", given=[], when=["a"], then=[]),
                GherkinScenario(name="Second", given=[], when=["b"], then=[]),
            ],
        )
        rendered = gherkin_gen.render_feature(feature)
        self.assertLess(rendered.index("Scenario: First"), rendered.index("Scenario: Second"))

    def test_multiline_description_is_kept(self) -> None:
        feature = GherkinFeature(
            title="T",
            description="first line\nsecond line",
            scenarios=[],
        )
        rendered = gherkin_gen.render_feature(feature)
        self.assertIn("  first line\n  second line\n", rendered)


class ResolveOutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.parsed = self.base / "parsed"
        self.parsed.mkdir()

    def test_backend_suffix_reflects_generation_backend(self) -> None:
        inp = self.parsed / "sample_control_parsed_local.json"
        output, stem = gherkin_gen.resolve_output_path(inp, "api")
        self.assertEqual(output, self.base / "gherkin" / "sample_control_api.feature")
        self.assertEqual(stem, "sample_control")

    def test_input_backend_is_stripped_from_stem(self) -> None:
        inp = self.parsed / "signal_light_demo_parsed_api.json"
        output, _ = gherkin_gen.resolve_output_path(inp, "api")
        self.assertEqual(output.name, "signal_light_demo_api.feature")

    def test_output_directory_is_created(self) -> None:
        inp = self.parsed / "sample_control_parsed_local.json"
        self.assertFalse((self.base / "gherkin").exists())
        gherkin_gen.resolve_output_path(inp, "local")
        self.assertTrue((self.base / "gherkin").is_dir())

    def test_non_conventional_filename_is_fatal(self) -> None:
        inp = self.parsed / "plain_name.json"
        with self.assertRaises(SystemExit):
            gherkin_gen.resolve_output_path(inp, "local")


class LoadRequirementTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_missing_file_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            gherkin_gen.load_requirement(self.dir / "missing.json")

    def test_empty_file_is_fatal(self) -> None:
        path = self.dir / "empty.json"
        path.write_text("   \n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            gherkin_gen.load_requirement(path)

    def test_invalid_json_is_fatal(self) -> None:
        path = self.dir / "bad.json"
        path.write_text('{"not": "a requirement"}', encoding="utf-8")
        with self.assertRaises(SystemExit):
            gherkin_gen.load_requirement(path)

    def test_valid_requirement_loads(self) -> None:
        output = gherkin_gen.load_requirement(
            Path("data/parsed/signal_light_demo_parsed_api.json")
        )
        self.assertGreater(len(output.sequences), 0)
        self.assertGreater(len(output.interlocks), 0)


class ScenarioConversionTests(unittest.TestCase):
    def test_scenario_from_step_stamps_provenance(self) -> None:
        step = ControlSequence(
            step_id=7, description="When the operator presses start, SL-301 turns green"
        )

        def fake_structured(_input) -> GherkinScenario:
            return GherkinScenario(
                name="Made up by model",
                given=["the system is ready"],
                when=["press start"],
                then=["green"],
            )

        scenario = gherkin_gen.scenario_from_step(
            fake_structured, step, equipment_names=["SL-301"]
        )
        self.assertEqual(scenario.source_step_id, 7)
        self.assertIsNone(scenario.source_interlock_condition)
        # The ungrounded fabricated given must be dropped by the backstop.
        self.assertEqual(scenario.given, [])

    def test_scenario_from_step_keeps_grounded_given(self) -> None:
        step = ControlSequence(step_id=1, description="SL-301 turns green on start")

        def fake_structured(_input) -> GherkinScenario:
            return GherkinScenario(
                name="S",
                given=["SL-301 turns green"],
                when=["start"],
                then=["green"],
            )

        scenario = gherkin_gen.scenario_from_step(
            fake_structured, step, equipment_names=["SL-301"]
        )
        self.assertEqual(scenario.given, ["SL-301 turns green"])

    def test_scenario_from_interlock_stamps_verbatim_condition(self) -> None:
        interlock = Interlock(
            condition="Emergency Stop button is pressed",
            action="SL-301 must immediately switch to red",
        )

        def fake_structured(_input) -> GherkinScenario:
            return GherkinScenario(
                name="Escalation",
                given=[],
                when=["Emergency Stop button is pressed"],
                then=["red"],
            )

        scenario = gherkin_gen.scenario_from_interlock(
            fake_structured, interlock, equipment_names=["SL-301"]
        )
        self.assertIsNone(scenario.source_step_id)
        self.assertEqual(
            scenario.source_interlock_condition,
            "Emergency Stop button is pressed",
        )

    def test_generate_feature_meta_uses_structured_output(self) -> None:
        class FakeLLM:
            bound_schema = None

            def with_structured_output(self, schema):
                self.bound_schema = schema
                FakeLLM.bound_schema = schema

                def invoke(_input) -> GherkinFeature:
                    return GherkinFeature(
                        title="Signal light control",
                        description="Short summary.",
                        scenarios=[],
                    )

                return invoke

        requirement = gherkin_gen.load_requirement(
            Path("data/parsed/signal_light_demo_parsed_api.json")
        )
        meta = gherkin_gen.generate_feature_meta(FakeLLM(), requirement)
        self.assertEqual(meta.title, "Signal light control")
        self.assertEqual(meta.scenarios, [])
        self.assertEqual(FakeLLM.bound_schema, GherkinFeature)


if __name__ == "__main__":
    unittest.main()