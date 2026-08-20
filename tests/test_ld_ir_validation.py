"""Deterministic structural validation for generated LD IR artifacts (E3S1T5).

Fully offline: every test deserializes an existing artifact under
``data/plc/ld/`` into the ``LDProgram`` schema and asserts structural
constraints. No LLM, network, or backend is invoked.

Common checks apply to all LD IR files (deterministic, hybrid, LLM Direct):
schema validity, unique network IDs, legal contact/coil types, a non-empty coil
per network, and sequence-before-interlock ordering. Python-rendered outputs
(deterministic + hybrid) are additionally required to carry ``priority >= 1``
and full traceability (``source_ast_node_id`` plus a
step/interlock/condition stamp per network). LLM Direct output is validated to
the common contract plus a ``source_ast_node_id`` stamp and non-negative
priority, reflecting its comparison-artifact role (its richer traceability is
known to be sparse, e.g. ``llm_direct_local``).
"""

from pathlib import Path
import unittest

from src.plc_code_schemas import LDProgram


LD_DIR = Path("data/plc/ld")

_VALID_CONTACT_TYPES = {"normally_open", "normally_closed"}
_VALID_COIL_TYPES = {"normal", "set", "reset"}


def _ld_files() -> list[Path]:
    return sorted(LD_DIR.glob("*.json"))


def _is_llm_direct(path: Path) -> bool:
    return "_llm_direct_" in path.name


def _is_rendered(path: Path) -> bool:
    return not _is_llm_direct(path)


def _load(path: Path) -> LDProgram:
    return LDProgram.model_validate_json(path.read_text(encoding="utf-8"))


class SchemaAndStructureTests(unittest.TestCase):
    """Common checks for every LD IR artifact."""

    def test_all_artifacts_deserialize_to_ld_program(self) -> None:
        files = _ld_files()
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                self.assertIsInstance(_load(f), LDProgram)

    def test_network_ids_are_unique(self) -> None:
        for f in _ld_files():
            with self.subTest(file=f.name):
                prog = _load(f)
                ids = [n.network_id for n in prog.networks]
                self.assertEqual(len(ids), len(set(ids)), f"duplicate network_id in {f.name}")

    def test_contact_and_coil_types_are_valid(self) -> None:
        for f in _ld_files():
            with self.subTest(file=f.name):
                prog = _load(f)
                for n in prog.networks:
                    self.assertIn(n.coil.coil_type, _VALID_COIL_TYPES)
                    for c in n.contacts:
                        self.assertIn(c.contact_type, _VALID_CONTACT_TYPES)

    def test_every_network_has_non_empty_coil(self) -> None:
        for f in _ld_files():
            with self.subTest(file=f.name):
                prog = _load(f)
                self.assertTrue(prog.networks, f"no networks in {f.name}")
                for n in prog.networks:
                    self.assertTrue(n.coil.variable.strip(), f"{n.network_id} has empty coil")

    def test_sequence_networks_before_interlock_networks(self) -> None:
        for f in _ld_files():
            with self.subTest(file=f.name):
                prog = _load(f)
                seq_idx = [i for i, n in enumerate(prog.networks) if n.network_id.startswith("SEQ")]
                ilk_idx = [i for i, n in enumerate(prog.networks) if not n.network_id.startswith("SEQ")]
                if seq_idx and ilk_idx:
                    self.assertLess(max(seq_idx), min(ilk_idx),
                                    f"interlock network precedes sequence in {f.name}")

    def test_every_network_stamped_with_source_ast_node(self) -> None:
        for f in _ld_files():
            with self.subTest(file=f.name):
                prog = _load(f)
                for n in prog.networks:
                    self.assertTrue(n.source_ast_node_id,
                                    f"{n.network_id} missing source_ast_node_id")


class RenderedTraceabilityTests(unittest.TestCase):
    """Full checks for Python-rendered outputs (deterministic + hybrid)."""

    @staticmethod
    def _rendered() -> list[Path]:
        return [f for f in _ld_files() if _is_rendered(f)]

    def test_rendered_priority_is_at_least_one(self) -> None:
        files = self._rendered()
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                prog = _load(f)
                for n in prog.networks:
                    self.assertGreaterEqual(n.priority, 1, f"{n.network_id} priority < 1")

    def test_rendered_networks_have_step_or_interlock_traceability(self) -> None:
        for f in self._rendered():
            with self.subTest(file=f.name):
                prog = _load(f)
                for n in prog.networks:
                    has_trace = (
                        n.source_step_id is not None
                        or bool(n.source_interlock_condition)
                        or bool(n.source_condition)
                    )
                    self.assertTrue(has_trace,
                                    f"{n.network_id} has no step/interlock traceability")


class LlmDirectTraceabilityTests(unittest.TestCase):
    """Minimal traceability contract for LLM Direct output (comparison draft)."""

    @staticmethod
    def _direct() -> list[Path]:
        return [f for f in _ld_files() if _is_llm_direct(f)]

    def test_llm_direct_priority_is_non_negative(self) -> None:
        files = self._direct()
        self.assertGreater(len(files), 0)
        for f in files:
            with self.subTest(file=f.name):
                prog = _load(f)
                for n in prog.networks:
                    self.assertGreaterEqual(n.priority, 0, f"{n.network_id} priority < 0")

    def test_llm_direct_networks_have_source_ast_stamp(self) -> None:
        for f in self._direct():
            with self.subTest(file=f.name):
                prog = _load(f)
                for n in prog.networks:
                    self.assertTrue(n.source_ast_node_id,
                                    f"{n.network_id} missing source_ast_node_id")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
