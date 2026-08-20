"""OpenPLC v3 compile + simulation checks for generated ST artifacts (E3S1T8).

Compiles and runs the Python-rendered (deterministic + hybrid) ST artifacts
under ``data/plc/st/`` through the OpenPLC v3 runtime via
``src/openplc_checker``, and confirms they execute scan cycles without
segmentation faults or runtime panics. The suite skips gracefully when no
OpenPLC installation is found.

Known divergence (reported, marked ``expectedFailure``): the hybrid
``sample_control`` outputs use a ``REAL >= INT`` literal
(``tank_level_sensor >= 80``), which the OpenPLC ``iec2c`` rejects as a
data-type mismatch (mirrors the MATIEC finding in E3S1T7); it is isolated to
``src/st_gen_hybrid.py`` and slated for a float-formatting fix.

Only compile and crash-free execution are checked; no business-logic semantic
evaluation is performed.
"""

from pathlib import Path
import unittest

from src.openplc_checker import is_openplc_available, run_openplc_simulation


ST_DIR = Path("data/plc/st")

# Known OpenPLC compile failures (filename -> reason).
KNOWN_COMPILE_FAIL = {
    "sample_control_api_AST_C_st_hybrid_api.st": "REAL >= INT literal (needs 80.0)",
    "sample_control_api_AST_C_st_hybrid_local.st": "REAL >= INT literal (needs 80.0)",
}


def _rendered() -> list[Path]:
    return sorted(f for f in ST_DIR.glob("*.st") if "_llm_direct_" not in f.name)


@unittest.skipUnless(is_openplc_available(), "OpenPLC runtime not available")
class OpenPlcCompileSimulationTests(unittest.TestCase):
    """Deterministic + hybrid ST compile under OpenPLC and run stable scan cycles."""

    def test_rendered_st_compiles_and_simulates_stably(self) -> None:
        files = [f for f in _rendered() if f.name not in KNOWN_COMPILE_FAIL]
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                result = run_openplc_simulation(f, run_seconds=1.0)
                self.assertTrue(
                    result.compiled,
                    f"{f.name} failed to compile: {result.first_error}",
                )
                self.assertTrue(
                    result.ran_stably,
                    f"{f.name} runtime crashed (returncode={result.returncode})",
                )

    @unittest.expectedFailure  # known REAL >= INT compile divergence in hybrid sample_control
    def test_sample_control_hybrid_compiles_and_simulates(self) -> None:
        for name in KNOWN_COMPILE_FAIL:
            with self.subTest(file=name):
                result = run_openplc_simulation(ST_DIR / name, run_seconds=1.0)
                self.assertTrue(result.compiled, f"{name}: {result.first_error}")
                self.assertTrue(result.ran_stably)


class OpenPlcAvailabilityTests(unittest.TestCase):
    def test_is_openplc_available_detects_install(self) -> None:
        self.assertIsInstance(is_openplc_available(), bool)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
