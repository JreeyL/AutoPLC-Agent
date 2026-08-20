"""MATIEC iec2c compilation checks for generated ST artifacts (E3S1T7).

Compiles every generated ``.st`` file under ``data/plc/st/`` with the MATIEC
``iec2c`` toolchain via ``src/matiec_checker``. The suite skips gracefully when
MATIEC is not installed.

Known MATIEC compatibility divergences (reported, marked ``expectedFailure``):
- Python-rendered ``sample_control`` hybrid ST uses a ``REAL >= INT`` literal
  (``tank_level_sensor >= 80``), which MATIEC rejects as a data-type mismatch
  (needs ``80.0``).
- LLM Direct ``local`` outputs for both samples carry non-standard syntax
  (a dangling ``ELSIF`` / missing ``;``), so they fail to compile.

These are compiler-compatibility findings, not business-logic semantic checks.
"""

from pathlib import Path
import unittest

from src.matiec_checker import (
    _configuration_wrapper,
    _strip_line_comments,
    compile_st_file,
    is_matiec_available,
)


ST_DIR = Path("data/plc/st")

# Known MATIEC compile divergences (filename -> reason).
TIER1_KNOWN_FAIL = {
    "sample_control_api_AST_C_st_hybrid_api.st": "REAL >= INT literal (needs 80.0)",
    "sample_control_api_AST_C_st_hybrid_local.st": "REAL >= INT literal (needs 80.0)",
}
TIER2_KNOWN_FAIL = {
    "sample_control_api_AST_C_st_llm_direct_local.st": "dangling ELSIF / missing ';'",
    "signal_light_demo_api_AST_C_st_llm_direct_local.st": "dangling ELSIF / missing ';'",
}


def _rendered() -> list[Path]:
    return sorted(f for f in ST_DIR.glob("*.st") if "_llm_direct_" not in f.name)


def _direct() -> list[Path]:
    return sorted(f for f in ST_DIR.glob("*.st") if "_llm_direct_" in f.name)


@unittest.skipUnless(is_matiec_available(), "MATIEC iec2c not found on PATH")
class Tier1DeterministicHybridTests(unittest.TestCase):
    """Deterministic + hybrid ST must compile (minus known divergences)."""

    def test_rendered_st_compiles(self) -> None:
        files = [f for f in _rendered() if f.name not in TIER1_KNOWN_FAIL]
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                result = compile_st_file(f)
                self.assertTrue(
                    result.compiled,
                    f"{f.name} failed to compile: {result.first_error}",
                )

    @unittest.expectedFailure  # known REAL >= INT data-type divergence in hybrid
    def test_sample_control_hybrid_compiles(self) -> None:
        for name in TIER1_KNOWN_FAIL:
            with self.subTest(file=name):
                result = compile_st_file(ST_DIR / name)
                self.assertTrue(result.compiled, f"{name}: {result.first_error}")


@unittest.skipUnless(is_matiec_available(), "MATIEC iec2c not found on PATH")
class Tier2LlmDirectTests(unittest.TestCase):
    """LLM Direct ST: API compiles; local carries known non-standard syntax."""

    def test_llm_direct_api_compiles(self) -> None:
        files = [f for f in _direct() if f.name.endswith("_api.st")]
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                result = compile_st_file(f)
                self.assertTrue(result.compiled, f"{f.name}: {result.first_error}")

    @unittest.expectedFailure  # known dangling ELSIF / missing ';' in local
    def test_llm_direct_local_compiles(self) -> None:
        files = [f for f in _direct() if f.name.endswith("_local.st")]
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                result = compile_st_file(f)
                self.assertTrue(result.compiled, f"{f.name}: {result.first_error}")


class MatiecCheckerUtilitiesTests(unittest.TestCase):
    """White-box checks for the compiler wrapper helpers (no MATIEC required)."""

    def test_is_matiec_available_detects_binary(self) -> None:
        self.assertIsInstance(is_matiec_available(), bool)

    def test_strip_line_comments_removes_slash_slash(self) -> None:
        code = "x : BOOL; // source equipment: x\nx := TRUE;\n"
        stripped = _strip_line_comments(code)
        self.assertNotIn("//", stripped)
        self.assertIn("x := TRUE;", stripped)

    def test_configuration_wrapper_embeds_program(self) -> None:
        wrapper = _configuration_wrapper("my_prog")
        self.assertIn("CONFIGURATION main_cfg", wrapper)
        self.assertIn("PROGRAM main_p WITH main_t : my_prog;", wrapper)
        self.assertIn("TASK main_t(INTERVAL := T#1s, PRIORITY := 0);", wrapper)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
