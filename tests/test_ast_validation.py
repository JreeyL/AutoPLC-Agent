"""Deterministic structural validation for PLC_AST artifacts (E3S1T3).

Fully offline: every test deserializes an existing artifact under
``data/ast/`` into the ``PLC_AST`` schema and asserts structural, provenance,
and grounding constraints. No LLM, network, or backend is invoked.

Checks:
- Schema: every ``*.json`` deserializes cleanly into ``PLC_AST``.
- Structure: non-empty devices (name/type/source_equipment), continuous
  ``step_id`` sequence, and interlocks with non-empty condition/forced_action/
  affected_devices and ``priority >= 1``.
- Provenance: ``source_step_id`` / ``source_interlock_condition`` stamps exist,
  and ``source_requirement_file`` / ``source_gherkin_file`` are non-empty and
  resolve to real files.
- Grounding: each device's ``source_equipment`` maps verbatim into the source
  parsed ``equipment_list``, and every device tag referenced in sequence /
  interlock text resolves to a known device.
"""

from pathlib import Path
import re
import unittest

from src.ast_schemas import PLC_AST
from src.schemas import SystemRequirement


AST_DIR = Path("data/ast")

# Equipment tags look like engineering identifiers, e.g. EV-101, SL-301, PMP-200.
_TAG_RE = re.compile(r"\b[A-Z]{1,4}-\d+\b")


def _ast_files() -> list[Path]:
    return sorted(AST_DIR.glob("*.json"))


def _load(path: Path) -> PLC_AST:
    return PLC_AST.model_validate_json(path.read_text(encoding="utf-8"))


class SchemaValidationTests(unittest.TestCase):
    def test_all_artifacts_deserialize_to_plc_ast(self) -> None:
        files = _ast_files()
        self.assertGreater(len(files), 0, "no PLC_AST artifacts found")
        for f in files:
            with self.subTest(file=f.name):
                obj = _load(f)
                self.assertIsInstance(obj, PLC_AST)


class StructureTests(unittest.TestCase):
    def test_devices_have_non_empty_fields(self) -> None:
        for f in _ast_files():
            with self.subTest(file=f.name):
                ast = _load(f)
                self.assertTrue(ast.devices, "devices must not be empty")
                for dev in ast.devices:
                    self.assertTrue(dev.name.strip())
                    self.assertTrue(dev.device_type.strip())
                    self.assertTrue(dev.source_equipment.strip())

    def test_sequence_step_ids_are_continuous_from_one(self) -> None:
        for f in _ast_files():
            with self.subTest(file=f.name):
                ast = _load(f)
                self.assertTrue(ast.sequence, "sequence must not be empty")
                ids = [s.step_id for s in ast.sequence]
                self.assertEqual(ids, list(range(1, len(ids) + 1)),
                                 "step_ids must be 1, 2, 3, ... continuous")
                for s in ast.sequence:
                    self.assertTrue(s.action.strip())

    def test_interlocks_have_required_fields_and_priority(self) -> None:
        for f in _ast_files():
            with self.subTest(file=f.name):
                ast = _load(f)
                for il in ast.interlocks:
                    self.assertTrue(il.condition.strip())
                    self.assertTrue(il.forced_action.strip())
                    self.assertTrue(il.affected_devices, "affected_devices must not be empty")
                    self.assertGreaterEqual(il.priority, 1)


class ProvenanceTests(unittest.TestCase):
    def test_source_file_stamps_resolve_to_real_files(self) -> None:
        for f in _ast_files():
            with self.subTest(file=f.name):
                ast = _load(f)
                self.assertTrue(ast.source_requirement_file,
                                "source_requirement_file must be stamped")
                self.assertTrue(ast.source_gherkin_file,
                                "source_gherkin_file must be stamped")
                self.assertTrue(Path(ast.source_requirement_file).exists(),
                                f"missing source requirement {ast.source_requirement_file!r}")
                self.assertTrue(Path(ast.source_gherkin_file).exists(),
                                f"missing source gherkin {ast.source_gherkin_file!r}")

    def test_cross_reference_stamps_exist(self) -> None:
        for f in _ast_files():
            with self.subTest(file=f.name):
                ast = _load(f)
                for s in ast.sequence:
                    self.assertIsNotNone(s.source_step_id, f"{s.node_id} lacks source_step_id")
                for il in ast.interlocks:
                    self.assertTrue(il.source_interlock_condition.strip(),
                                    f"{il.node_id} lacks source_interlock_condition")


class GroundingTests(unittest.TestCase):
    def test_source_equipment_maps_into_parsed_equipment_list(self) -> None:
        for f in _ast_files():
            with self.subTest(file=f.name):
                ast = _load(f)
                req = SystemRequirement.model_validate_json(
                    Path(ast.source_requirement_file).read_text(encoding="utf-8")
                )
                parsed_names = {e.name for e in req.equipment_list}
                for dev in ast.devices:
                    self.assertIn(dev.source_equipment, parsed_names,
                                  f"device {dev.name!r} source_equipment "
                                  f"{dev.source_equipment!r} not in source parsed list")

    def test_referenced_device_tags_resolve_to_devices(self) -> None:
        for f in _ast_files():
            with self.subTest(file=f.name):
                ast = _load(f)
                texts = []
                for s in ast.sequence:
                    texts.append(s.action)
                    if s.condition:
                        texts.append(s.condition)
                for il in ast.interlocks:
                    texts.append(il.condition)
                    texts.append(il.forced_action)
                    texts.extend(il.affected_devices)
                tags = sorted(set(_TAG_RE.findall(" || ".join(texts))))
                known = [d.name for d in ast.devices] + [d.device_type for d in ast.devices]
                for tag in tags:
                    self.assertTrue(
                        any(tag in k for k in known),
                        f"device tag {tag!r} in sequence/interlock text "
                        f"does not resolve to any device",
                    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
