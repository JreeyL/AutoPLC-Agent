"""Deterministic structural validation for E2S2 Gherkin `.feature` artifacts (E3S1T2).

Fully offline: every test parses an existing file under ``data/gherkin/`` with
the standard ``gherkin-official`` parser and asserts structural constraints. No
LLM, network, or backend is invoked.

Scope:
- L1 syntax: each `.feature` parses cleanly with the standard Gherkin parser.
- L2 structure: exactly one feature with a non-empty title; at least one
  scenario; every scenario has a non-empty name and valid Given/When/Then/And
  steps; every scenario carries at least one ``When`` and one ``Then``.
- L3 coverage: the number of generated scenarios is at least the number of
  source items (control-sequence steps + interlocks) in the paired
  ``data/parsed/*_parsed_*.json`` for the same backend.

Traceability boundary: the `.feature` text does not carry the
``source_step_id`` / ``source_interlock_condition`` fields (they live on the
in-memory ``GherkinScenario`` model and are not emitted by the renderer), so
per-scenario traceability cannot be asserted from this artifact. It is noted in
the task description and deferred to a generator-side change that persists the
traceability JSON.

Known coverage gap: the E2S2 ``local`` backend skipped one source step for
``sample_control_local.feature`` (6 scenarios vs 7 source items). That file is
handled by an ``expectedFailure`` test (the unit-test equivalent of pytest
``xfail``) so the gap is surfaced without failing the suite.
"""

from pathlib import Path
import unittest

from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner

from src.schemas import SystemRequirement


GHERKIN_DIR = Path("data/gherkin")
PARSED_DIR = Path("data/parsed")

# E2S2 known coverage gap: local skipped one source step -> 6 scenarios vs 7 items.
KNOWN_COVERAGE_GAP = "sample_control_local.feature"

_STEP_KEYWORDS = ("Given", "When", "Then", "And", "But")


def _feature_files() -> list[Path]:
    return sorted(GHERKIN_DIR.glob("*.feature"))


def _parsed_for_feature(feature_path: Path) -> Path:
    """Map a .feature to its paired parsed JSON for the same backend."""
    stem = feature_path.stem  # e.g. sample_control_api
    if stem.endswith("_api"):
        base, backend = stem[:-4], "api"
    elif stem.endswith("_local"):
        base, backend = stem[:-6], "local"
    else:
        raise ValueError(f"unrecognized feature stem: {stem!r}")
    return PARSED_DIR / f"{base}_parsed_{backend}.json"


def _parse(feature_path: Path):
    """Parse with gherkin-official; raises on invalid Gherkin syntax."""
    return Parser().parse(TokenScanner(feature_path.read_text(encoding="utf-8")))


def _scenarios(feature_doc) -> list:
    return [c["scenario"] for c in feature_doc["feature"]["children"] if "scenario" in c]


class SyntaxValidationTests(unittest.TestCase):
    def test_all_features_parse_with_standard_gherkin_parser(self) -> None:
        files = _feature_files()
        self.assertGreater(len(files), 0, "no *.feature artifacts found")
        for f in files:
            with self.subTest(file=f.name):
                _parse(f)  # raises ParserError on invalid Gherkin

    def test_each_feature_has_title_and_at_least_one_scenario(self) -> None:
        for f in _feature_files():
            with self.subTest(file=f.name):
                doc = _parse(f)
                self.assertTrue(doc["feature"]["name"].strip(), "feature must have a title")
                self.assertGreater(len(_scenarios(doc)), 0, "feature must have scenarios")


class StructureTests(unittest.TestCase):
    def test_scenarios_use_valid_step_keywords(self) -> None:
        for f in _feature_files():
            with self.subTest(file=f.name):
                doc = _parse(f)
                for sc in _scenarios(doc):
                    for step in sc["steps"]:
                        self.assertIn(step["keyword"].strip(), _STEP_KEYWORDS,
                                      f"invalid step keyword in {sc['name']!r}")

    def test_each_scenario_has_a_when_and_a_then(self) -> None:
        for f in _feature_files():
            with self.subTest(file=f.name):
                doc = _parse(f)
                for sc in _scenarios(doc):
                    kws = {s["keyword"].strip() for s in sc["steps"]}
                    self.assertIn("When", kws, f"{sc['name']!r} has no When step")
                    self.assertIn("Then", kws, f"{sc['name']!r} has no Then step")

    def test_scenario_names_and_step_text_are_non_empty(self) -> None:
        for f in _feature_files():
            with self.subTest(file=f.name):
                doc = _parse(f)
                for sc in _scenarios(doc):
                    self.assertTrue(sc["name"].strip())
                    for step in sc["steps"]:
                        self.assertTrue(step["text"].strip())


class CoverageTests(unittest.TestCase):
    @staticmethod
    def _expected_items(parsed_path: Path) -> int:
        req = SystemRequirement.model_validate_json(parsed_path.read_text(encoding="utf-8"))
        return len(req.sequences) + len(req.interlocks)

    @staticmethod
    def _actual_scenarios(feature_path: Path) -> int:
        return len(_scenarios(_parse(feature_path)))

    def test_feature_scenarios_cover_source_items(self) -> None:
        covered = 0
        for f in _feature_files():
            if f.name == KNOWN_COVERAGE_GAP:
                continue
            with self.subTest(file=f.name):
                actual = self._actual_scenarios(f)
                expected = self._expected_items(_parsed_for_feature(f))
                self.assertGreaterEqual(
                    actual,
                    expected,
                    f"{f.name}: {actual} scenarios < source items ({expected})",
                )
                covered += 1
        self.assertGreater(covered, 0)

    @unittest.expectedFailure  # E2S2 known gap: local skipped one source step
    def test_local_sample_control_coverage_known_gap(self) -> None:
        f = GHERKIN_DIR / KNOWN_COVERAGE_GAP
        actual = self._actual_scenarios(f)          # 6
        expected = self._expected_items(_parsed_for_feature(f))  # 5 steps + 2 = 7
        self.assertGreaterEqual(
            actual,
            expected,
            f"{f.name}: {actual} scenarios < source items ({expected})",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
