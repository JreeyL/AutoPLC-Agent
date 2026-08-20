"""Structural validation of the hybrid generators' outputs (E3S1T6).

Fully offline and strictly structural: no LLM, no network, and NO business-logic
semantic review. This suite verifies that the hybrid generators (``st_gen_hybrid``
/ ``ld_ir_gen_hybrid``) correctly render their declared hybrid capabilities
(timers as TON blocks, analogue thresholds as REAL comparisons / operator+threshold
contacts, colour/state intents as review notes) into well-formed structure. It
deliberately does NOT judge whether the rendered logic is semantically correct or
matches the original requirement intent — that end-to-end semantic evaluation is
planned separately in E3S3T1.

Known capability mapping for the two example requirements (structural, not
semantic):
- ``sample_control`` has timer and analogue requirements; its hybrid outputs must
  carry timer and analogue structure.
- ``signal_light_demo`` has colour-state requirements; its hybrid outputs must
  carry colour-state structure.
"""

from pathlib import Path
import re
import unittest


ST_DIR = Path("data/plc/st")
LD_DIR = Path("data/plc/ld")

_VALID_OPERATORS = {">=", "<=", ">", "<", "=="}


def _st_hybrid_files() -> list[Path]:
    return sorted(ST_DIR.glob("*_st_hybrid_*.st"))


def _ld_hybrid_files() -> list[Path]:
    return sorted(LD_DIR.glob("*_ld_hybrid_*.json"))


def _load_ld(path: Path):
    import json
    return json.loads(path.read_text(encoding="utf-8"))


class StHybridMechanismTests(unittest.TestCase):
    """Mechanism consistency of hybrid ST structure (presence implies validity)."""

    def test_ton_declaration_and_invocation_are_consistent(self) -> None:
        for f in _st_hybrid_files():
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                decls = set(re.findall(r"(\bTON_\w+)\s*:\s*TON\b", t))
                invokes = set(re.findall(r"(\bTON_\w+)\s*\(IN := TRUE, PT := T#\d", t))
                # Any invoked timer must have a matching declaration and a constant PT.
                for name in invokes:
                    self.assertIn(name, decls, f"{name} invoked but not declared in {f.name}")
                    self.assertTrue(
                        re.search(re.escape(name) + r"\(IN := TRUE, PT := T#\d+(?:\.\d+)?s", t),
                        f"{name} PT assignment malformed in {f.name}",
                    )

    def test_real_comparison_uses_valid_operator(self) -> None:
        for f in _st_hybrid_files():
            with self.subTest(file=f.name):
                t = f.read_text(encoding="utf-8")
                if "REAL" not in t:
                    continue
                for m in re.finditer(r"\b\w+\s*(>=|<=|>|<|==)\s*-?\d", t):
                    self.assertIn(m.group(1), _VALID_OPERATORS,
                                  f"invalid comparison operator in {f.name}")

    def test_hybrid_renderer_marker_comment_present(self) -> None:
        for f in _st_hybrid_files():
            with self.subTest(file=f.name):
                self.assertIn("// Hybrid", f.read_text(encoding="utf-8"),
                              f"missing hybrid renderer marker in {f.name}")


class LdHybridMechanismTests(unittest.TestCase):
    """Mechanism consistency of hybrid LD IR structure."""

    def test_analogue_contacts_have_valid_operator_and_threshold(self) -> None:
        for f in _ld_hybrid_files():
            with self.subTest(file=f.name):
                prog = _load_ld(f)
                for n in prog["networks"]:
                    for c in n["contacts"]:
                        if c.get("operator") is not None:
                            self.assertIn(c["operator"], _VALID_OPERATORS)
                            self.assertIsInstance(c.get("threshold"), (int, float),
                                                  f"{n['network_id']} analogue contact "
                                                  f"missing numeric threshold")

    def test_timer_metadata_is_positive_when_present(self) -> None:
        for f in _ld_hybrid_files():
            with self.subTest(file=f.name):
                prog = _load_ld(f)
                for n in prog["networks"]:
                    if n.get("timer_duration_seconds") is not None:
                        self.assertGreater(n["timer_duration_seconds"], 0,
                                           f"{n['network_id']} timer duration must be > 0")


class SampleCapabilityCoverageTests(unittest.TestCase):
    """Hybrid renders the declared capability structure for each example sample."""

    def test_sample_control_implements_timer_and_analogue_in_st(self) -> None:
        f = ST_DIR / "sample_control_api_AST_C_st_hybrid_api.st"
        t = f.read_text(encoding="utf-8")
        self.assertIn("TON_", t, "sample_control hybrid ST must carry timer structure")
        self.assertIn("REAL", t, "sample_control hybrid ST must declare an analogue REAL")
        self.assertTrue(re.search(r">=\s*\d", t), "sample_control hybrid ST missing analogue comparison")

    def test_sample_control_implements_analogue_and_timer_in_ld(self) -> None:
        prog = _load_ld(LD_DIR / "sample_control_api_AST_C_ld_hybrid_api.json")
        has_analogue = any(c.get("operator") for n in prog["networks"] for c in n["contacts"])
        has_timer = any(n.get("timer_duration_seconds") for n in prog["networks"])
        self.assertTrue(has_analogue, "sample_control hybrid LD missing analogue contact")
        self.assertTrue(has_timer, "sample_control hybrid LD missing timer metadata")

    def test_signal_light_implements_colour_in_st(self) -> None:
        t = (ST_DIR / "signal_light_demo_api_AST_C_st_hybrid_api.st").read_text(encoding="utf-8")
        self.assertIn("Hybrid colour-state intent", t,
                      "signal_light hybrid ST missing colour-state intent comment")

    def test_signal_light_implements_colour_in_ld(self) -> None:
        prog = _load_ld(LD_DIR / "signal_light_demo_api_AST_C_ld_hybrid_api.json")
        colour_notes = [str(x) for n in prog["networks"] for x in n.get("notes", [])
                        if "COLOUR" in str(x) or "-> " in str(x)]
        self.assertTrue(colour_notes, "signal_light hybrid LD missing colour-state notes")


class BackendConsistencyTests(unittest.TestCase):
    """Hybrid api and local outputs expose the same structural features."""

    def test_sample_control_st_api_and_local_markers_match(self) -> None:
        def markers(p: Path) -> set:
            t = p.read_text(encoding="utf-8")
            return set(re.findall(r"TON_\w+ : TON|tank_level_sensor : REAL|>= \d", t))

        api = markers(ST_DIR / "sample_control_api_AST_C_st_hybrid_api.st")
        loc = markers(ST_DIR / "sample_control_api_AST_C_st_hybrid_local.st")
        self.assertEqual(api, loc, "sample_control ST hybrid api/local markers differ")

    def test_sample_control_ld_api_and_local_features_match(self) -> None:
        def features(p: Path):
            prog = _load_ld(p)
            return (
                sorted({c["variable"] for n in prog["networks"] for c in n["contacts"]
                        if c.get("operator")}),
                sorted({n.get("timer_duration_seconds") for n in prog["networks"]
                        if n.get("timer_duration_seconds")}),
            )
        api = features(LD_DIR / "sample_control_api_AST_C_ld_hybrid_api.json")
        loc = features(LD_DIR / "sample_control_api_AST_C_ld_hybrid_local.json")
        self.assertEqual(api, loc, "sample_control LD hybrid api/local features differ")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
