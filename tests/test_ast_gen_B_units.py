"""Unit tests for src/ast_gen_B.py (E3S3T2).

Approach B is the fully deterministic zero-LLM AST pipeline. These tests cover
the text-matching utilities (tokenization, Dice coefficient, word-boundary
name matching), scenario extraction/matching, condition extraction, device
targeting, path resolution, and the end-to-end build_ast() pipeline against
the real data/parsed + data/gherkin fixtures.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import src.ast_gen_B as ast_gen_B
from src.ast_schemas import PLC_AST


class TokenizeTests(unittest.TestCase):
    def test_stopwords_are_removed(self) -> None:
        tokens = ast_gen_B._tokenize("the pump and the valve are open")
        self.assertNotIn("the", tokens)
        self.assertNotIn("and", tokens)
        self.assertIn("pump", tokens)
        self.assertIn("valve", tokens)

    def test_short_tokens_are_removed(self) -> None:
        tokens = ast_gen_B._tokenize("a b cd abc")
        self.assertNotIn("a", tokens)
        self.assertNotIn("b", tokens)
        self.assertNotIn("cd", tokens)
        self.assertIn("abc", tokens)

    def test_hyphenated_equipment_names_are_kept_intact(self) -> None:
        tokens = ast_gen_B._tokenize("open EV-101 and SL-301")
        self.assertIn("ev-101", tokens)
        self.assertIn("sl-301", tokens)

    def test_output_is_lowercased(self) -> None:
        self.assertEqual(ast_gen_B._tokenize("Green Light"), {"green", "light"})

    def test_empty_text_yields_empty_set(self) -> None:
        self.assertEqual(ast_gen_B._tokenize(""), set())


class MatchScoreTests(unittest.TestCase):
    def test_identical_texts_score_one(self) -> None:
        self.assertAlmostEqual(
            ast_gen_B._match_score("pump starts when tank is full", "pump starts when tank is full"),
            1.0,
        )

    def test_disjoint_texts_score_zero(self) -> None:
        self.assertEqual(ast_gen_B._match_score("green light", "red alarm"), 0.0)

    def test_partial_overlap_scores_between_zero_and_one(self) -> None:
        score = ast_gen_B._match_score("pump starts and valve opens", "pump stops and valve closes")
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_empty_token_set_scores_zero(self) -> None:
        self.assertEqual(ast_gen_B._match_score("the and of", "pump starts"), 0.0)


class TextContainsNameTests(unittest.TestCase):
    def test_exact_name_matches(self) -> None:
        self.assertTrue(ast_gen_B._text_contains_name("EV-101 opens", "EV-101"))

    def test_name_inside_longer_token_does_not_match(self) -> None:
        self.assertFalse(ast_gen_B._text_contains_name("EV-1012 opens", "EV-101"))
        self.assertFalse(ast_gen_B._text_contains_name("NEV-101 opens", "EV-101"))

    def test_punctuation_around_name_is_allowed(self) -> None:
        self.assertTrue(ast_gen_B._text_contains_name("(EV-101) opens", "EV-101"))

    def test_match_is_case_insensitive(self) -> None:
        self.assertTrue(ast_gen_B._text_contains_name("ev-101 opens", "EV-101"))


class ExtractScenariosTests(unittest.TestCase):
    def test_plain_scenarios_are_extracted(self) -> None:
        ast = {
            "feature": {
                "children": [
                    {"scenario": {"name": "S1"}},
                    {"scenario": {"name": "S2"}},
                    {"background": {"name": "BG"}},
                ]
            }
        }
        names = [s["name"] for s in ast_gen_B._extract_scenarios(ast)]
        self.assertEqual(names, ["S1", "S2"])

    def test_missing_feature_yields_empty_list(self) -> None:
        self.assertEqual(ast_gen_B._extract_scenarios({}), [])


class BestScenarioForTextTests(unittest.TestCase):
    def _scenarios(self) -> list[dict]:
        return [
            {
                "name": "Start pump",
                "steps": [
                    {"keyword": "Given ", "text": "tank is full"},
                    {"keyword": "When ", "text": "operator starts the pump"},
                ],
            },
            {
                "name": "Stop pump",
                "steps": [{"keyword": "When ", "text": "pump stops on high level"}],
            },
        ]

    def test_best_matching_scenario_is_selected(self) -> None:
        scenario, score = ast_gen_B._best_scenario_for_text(
            "pump stops when the level is high", self._scenarios()
        )
        self.assertEqual(scenario["name"], "Stop pump")
        self.assertGreater(score, 0.0)

    def test_threshold_discards_weak_matches(self) -> None:
        scenario, score = ast_gen_B._best_scenario_for_text(
            "completely unrelated electrical topic", self._scenarios()
        )
        self.assertIsNone(scenario)
        self.assertEqual(score, 0.0)


class ExtractConditionTests(unittest.TestCase):
    def test_first_given_or_when_step_wins_document_order(self) -> None:
        scenario = {
            "steps": [
                {"keyword": "Given ", "text": "tank is full."},
                {"keyword": "When ", "text": "operator presses start."},
            ]
        }
        # The first Given/When step in document order wins.
        self.assertEqual(
            ast_gen_B._extract_condition(scenario, "irrelevant"),
            "tank is full",
        )

    def test_given_step_used_when_no_when(self) -> None:
        scenario = {"steps": [{"keyword": "Given ", "text": "valve EV-101 is open"}]}
        self.assertEqual(
            ast_gen_B._extract_condition(scenario, "irrelevant"), "valve EV-101 is open"
        )

    def test_no_scenario_falls_back_to_when_clause(self) -> None:
        self.assertEqual(
            ast_gen_B._extract_condition(
                None, "When the operator presses start, the pump runs"
            ),
            "the operator presses start",
        )

    def test_no_scenario_falls_back_to_if_clause(self) -> None:
        self.assertEqual(
            ast_gen_B._extract_condition(None, "If the tank is full. Stop."),
            "the tank is full",
        )

    def test_no_trigger_returns_none(self) -> None:
        self.assertIsNone(ast_gen_B._extract_condition(None, "pump runs"))
        self.assertIsNone(ast_gen_B._extract_condition({"steps": []}, "pump runs"))


class DeviceTargetingTests(unittest.TestCase):
    EQUIPMENT = ["PMP-200", "SL-301", "EV-101"]

    def test_find_target_device_returns_first_equipment_list_match(self) -> None:
        # Search order follows equipment_list, not document order.
        self.assertEqual(
            ast_gen_B._find_target_device("EV-101 and SL-301 open", self.EQUIPMENT),
            "SL-301",
        )

    def test_find_target_device_returns_none_when_absent(self) -> None:
        self.assertIsNone(
            ast_gen_B._find_target_device("nothing referenced here", self.EQUIPMENT)
        )

    def test_find_affected_devices_returns_all_in_order(self) -> None:
        self.assertEqual(
            ast_gen_B._find_affected_devices("EV-101 fails, then PMP-200 stops", self.EQUIPMENT),
            ["PMP-200", "EV-101"],
        )

    def test_find_affected_devices_empty_when_none_mentioned(self) -> None:
        self.assertEqual(
            ast_gen_B._find_affected_devices("no devices", self.EQUIPMENT), []
        )


class ResolveOutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.parsed = self.base / "parsed"
        self.parsed.mkdir()

    def test_maps_to_ast_b_suffix(self) -> None:
        inp = self.parsed / "signal_light_demo_parsed_api.json"
        self.assertEqual(
            ast_gen_B.resolve_output_path(inp),
            self.base / "ast" / "signal_light_demo_AST_B.json",
        )

    def test_output_directory_is_created(self) -> None:
        inp = self.parsed / "x_parsed_local.json"
        ast_gen_B.resolve_output_path(inp)
        self.assertTrue((self.base / "ast").is_dir())

    def test_non_conventional_filename_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            ast_gen_B.resolve_output_path(self.parsed / "plain.json")


class FatalLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_load_requirement_missing_file_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            ast_gen_B.load_requirement(self.dir / "missing.json")

    def test_load_requirement_invalid_json_is_fatal(self) -> None:
        path = self.dir / "bad.json"
        path.write_text('{"nope": 1}', encoding="utf-8")
        with self.assertRaises(SystemExit):
            ast_gen_B.load_requirement(path)

    def test_load_gherkin_missing_file_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            ast_gen_B.load_and_parse_gherkin(self.dir / "missing.feature")

    def test_load_gherkin_empty_file_is_fatal(self) -> None:
        path = self.dir / "empty.feature"
        path.write_text("  ", encoding="utf-8")
        with self.assertRaises(SystemExit):
            ast_gen_B.load_and_parse_gherkin(path)

    def test_load_gherkin_invalid_syntax_is_fatal(self) -> None:
        # Missing Feature header is a hard parser error for gherkin-official.
        path = self.dir / "broken.feature"
        path.write_text("Given a bare step without a feature\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            ast_gen_B.load_and_parse_gherkin(path)


class BuildAstPipelineTests(unittest.TestCase):
    def test_signal_light_demo_pipeline_builds_valid_ast(self) -> None:
        ast = ast_gen_B.build_ast(
            Path("data/parsed/signal_light_demo_parsed_api.json"),
            Path("data/gherkin/signal_light_demo_api.feature"),
        )
        self.assertIsInstance(ast, PLC_AST)
        self.assertGreater(len(ast.devices), 0)
        self.assertGreater(len(ast.sequence), 0)
        self.assertGreater(len(ast.interlocks), 0)

    def test_sequence_nodes_carry_grounded_target_devices(self) -> None:
        ast = ast_gen_B.build_ast(
            Path("data/parsed/signal_light_demo_parsed_api.json"),
            Path("data/gherkin/signal_light_demo_api.feature"),
        )
        equipment_names = [d.name for d in ast.devices]
        for node in ast.sequence:
            if node.target_device is not None:
                self.assertIn(node.target_device, equipment_names)
            # Deterministic provenance: step references mirror the source id.
            self.assertEqual(node.source_step_id, node.step_id)

    def test_interlock_nodes_complete_affected_devices_deterministically(self) -> None:
        ast = ast_gen_B.build_ast(
            Path("data/parsed/signal_light_demo_parsed_api.json"),
            Path("data/gherkin/signal_light_demo_api.feature"),
        )
        equipment_names = [d.name for d in ast.devices]
        for node in ast.interlocks:
            self.assertEqual(node.source_interlock_condition, node.condition)
            for device in node.affected_devices:
                self.assertIn(device, equipment_names)

    def test_sample_control_pipeline_builds_valid_ast(self) -> None:
        ast = ast_gen_B.build_ast(
            Path("data/parsed/sample_control_parsed_local.json"),
            Path("data/gherkin/sample_control_local.feature"),
        )
        self.assertIsInstance(ast, PLC_AST)
        self.assertEqual(len(ast.devices), len(
            ast_gen_B.load_requirement(
                Path("data/parsed/sample_control_parsed_local.json")
            ).equipment_list
        ))


if __name__ == "__main__":
    unittest.main()