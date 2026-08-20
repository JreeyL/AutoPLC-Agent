"""Deterministic structural validation for generated Structured Text artifacts (E3S1T4).

Fully offline: every test reads an existing artifact under ``data/plc/st/`` and
asserts structural constraints. No LLM, network, or backend is invoked.

The ST outputs come from three generator strategies with different expectations:

- Deterministic (`st_gen.py`) and hybrid (`st_gen_hybrid.py`) are Python-rendered
  and are validated strictly: a `VAR`/`END_VAR` block, balanced `IF`/`END_IF`,
  traceability comments, `Sequence Logic` and `Safety Interlocks` section
  headers, and interlock-override placement after the sequence.
- LLM Direct (`st_gen_llm_direct.py`) is a raw LLM draft (per project convention
  it is a comparison artifact, not validated PLC code); it is validated only to
  a basic contract: a `PROGRAM`/`END_PROGRAM` wrapper, a `VAR` block, and no
  Markdown fences. Strict ST conformance of LLM Direct output (e.g. `ELSIF`
  placement) is intentionally deferred to the MATIEC compiler check (E3S1T7).
"""

from pathlib import Path
import re
import unittest


ST_DIR = Path("data/plc/st")


def _st_files() -> list[Path]:
    return sorted(ST_DIR.glob("*.st"))


def _is_llm_direct(path: Path) -> bool:
    return "_llm_direct_" in path.name


def _is_rendered(path: Path) -> bool:
    """Python-rendered outputs: deterministic + hybrid (everything but LLM Direct)."""
    return not _is_llm_direct(path)


class BasicContractTests(unittest.TestCase):
    def test_all_st_files_have_program_wrapper(self) -> None:
        for f in _st_files():
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                self.assertIn("PROGRAM", t, "missing PROGRAM")
                self.assertIn("END_PROGRAM", t, "missing END_PROGRAM")

    def test_all_st_files_are_non_empty_with_executable_logic(self) -> None:
        for f in _st_files():
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                self.assertTrue((":=" in t) or re.search(r"\bIF\b", t),
                                "no executable logic (assignment or IF block)")

    def test_no_markdown_fences(self) -> None:
        for f in _st_files():
            with self.subTest(file=f.name):
                self.assertNotIn("```", f.read_text(encoding="utf-8"),
                                 "Markdown fence leaked into ST output")


class RenderedStructureTests(unittest.TestCase):
    """Strict checks for Python-rendered outputs (deterministic + hybrid)."""

    @staticmethod
    def _rendered() -> list[Path]:
        return [f for f in _st_files() if _is_rendered(f)]

    def test_rendered_have_var_block(self) -> None:
        files = self._rendered()
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                self.assertIn("\nVAR", t, "missing VAR block")
                self.assertIn("END_VAR", t, "missing END_VAR")

    def test_rendered_if_and_end_if_balanced(self) -> None:
        for f in self._rendered():
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                if_count = len(re.findall(r"^\s*IF\s", t, re.M))
                endif_count = t.count("END_IF")
                self.assertEqual(if_count, endif_count,
                                 f"IF ({if_count}) / END_IF ({endif_count}) mismatch")

    def test_rendered_have_traceability_comments(self) -> None:
        for f in self._rendered():
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                self.assertTrue(re.search(r"source", t, re.IGNORECASE),
                                "no traceability comment")

    def test_rendered_have_sequence_and_safety_sections(self) -> None:
        for f in self._rendered():
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                self.assertIn("Sequence Logic", t, "missing Sequence Logic section")
                self.assertIn("Safety Interlocks", t, "missing Safety Interlocks section")

    def test_rendered_interlock_override_appears_after_sequence(self) -> None:
        for f in self._rendered():
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                seq_pos = t.find("Sequence Logic")
                safe_pos = t.find("Safety Interlocks")
                self.assertGreater(safe_pos, seq_pos,
                                   "Safety Interlocks should follow Sequence Logic")


class LlmDirectContractTests(unittest.TestCase):
    """Basic contract only, reflecting the LLM Direct draft role."""

    @staticmethod
    def _direct() -> list[Path]:
        return [f for f in _st_files() if _is_llm_direct(f)]

    def test_llm_direct_have_program_and_var_wrapper(self) -> None:
        files = self._direct()
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                self.assertIn("PROGRAM", t)
                self.assertIn("END_PROGRAM", t)
                self.assertIn("VAR", t)

    def test_llm_direct_no_markdown_fences(self) -> None:
        for f in self._direct():
            with self.subTest(file=f.name):
                self.assertNotIn("```", f.read_text(encoding="utf-8"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
