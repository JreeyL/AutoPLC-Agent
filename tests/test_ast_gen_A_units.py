"""Unit tests for src/ast_gen_A.py (E3S3T2).

Approach A is a single LLM-direct call; the LLM boundary is not exercised here.
These tests cover the deterministic surface: requirement/Gherkin loading with
their fatal paths, backend-tagged output path resolution, and CLI argument
parsing.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import src.ast_gen_A as ast_gen_A


class LoadRequirementTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_valid_requirement_loads(self) -> None:
        requirement = ast_gen_A.load_requirement(
            Path("data/parsed/signal_light_demo_parsed_api.json")
        )
        self.assertGreater(len(requirement.sequences), 0)

    def test_missing_file_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            ast_gen_A.load_requirement(self.dir / "missing.json")

    def test_empty_file_is_fatal(self) -> None:
        path = self.dir / "empty.json"
        path.write_text("\n  ", encoding="utf-8")
        with self.assertRaises(SystemExit):
            ast_gen_A.load_requirement(path)

    def test_invalid_json_is_fatal(self) -> None:
        path = self.dir / "bad.json"
        path.write_text('{"unrelated": true}', encoding="utf-8")
        with self.assertRaises(SystemExit):
            ast_gen_A.load_requirement(path)


class LoadGherkinTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_valid_feature_loads_as_raw_text(self) -> None:
        text = ast_gen_A.load_gherkin(Path("data/gherkin/signal_light_demo_api.feature"))
        self.assertIn("Feature:", text)

    def test_missing_file_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            ast_gen_A.load_gherkin(self.dir / "missing.feature")

    def test_empty_file_is_fatal(self) -> None:
        path = self.dir / "empty.feature"
        path.write_text("   ", encoding="utf-8")
        with self.assertRaises(SystemExit):
            ast_gen_A.load_gherkin(path)


class ResolveOutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.parsed = self.base / "parsed"
        self.parsed.mkdir()

    def test_local_backend_gets_bare_stem(self) -> None:
        inp = self.parsed / "sample_control_parsed_api.json"
        self.assertEqual(
            ast_gen_A.resolve_output_path(inp, "local"),
            self.base / "ast" / "sample_control_local.json",
        )

    def test_api_backend_gets_api_suffix(self) -> None:
        inp = self.parsed / "signal_light_demo_parsed_local.json"
        self.assertEqual(
            ast_gen_A.resolve_output_path(inp, "api"),
            self.base / "ast" / "signal_light_demo_api.json",
        )

    def test_ast_directory_is_created(self) -> None:
        inp = self.parsed / "x_parsed_local.json"
        ast_gen_A.resolve_output_path(inp, "local")
        self.assertTrue((self.base / "ast").is_dir())

    def test_non_conventional_filename_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            ast_gen_A.resolve_output_path(self.parsed / "plain.json", "local")


class ParseArgsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        with mock.patch.object(
            sys, "argv", ["ast_gen_A", "req.json", "feat.feature"]
        ):
            args = ast_gen_A.parse_args()
        self.assertEqual(args.requirement_file, Path("req.json"))
        self.assertEqual(args.gherkin_file, Path("feat.feature"))
        self.assertEqual(args.backend, "local")

    def test_backend_choice_is_validated(self) -> None:
        with mock.patch.object(
            sys, "argv", ["ast_gen_A", "req.json", "feat.feature", "--backend", "x"]
        ):
            with self.assertRaises(SystemExit):
                ast_gen_A.parse_args()


if __name__ == "__main__":
    unittest.main()