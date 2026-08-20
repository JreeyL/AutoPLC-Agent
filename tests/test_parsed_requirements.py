"""Deterministic structural validation for E2S1 parsed SystemRequirement artifacts (E3S1T1).

This suite is fully offline: every test deserializes an existing file under
``data/parsed/`` into the ``SystemRequirement`` Pydantic model and asserts
project-level structural constraints. No LLM, network, or backend is invoked.

Field note: the ``SystemRequirement`` schema names the lists ``equipment_list``,
``interlocks``, and ``sequences``. The ``Interlock`` model carries
``condition``/``action`` (there is no separate ``priority`` field); the
``ControlSequence`` model carries ``step_id``/``description``.
"""

from pathlib import Path
import re
import unittest

from src.schemas import SystemRequirement


PARSED_DIR = Path("data/parsed")

# Equipment tags look like engineering identifiers, e.g. EV-101, SL-301, PMP-200.
_TAG_RE = re.compile(r"\b[A-Z]{1,4}-\d+\b")


def _parsed_files() -> list[Path]:
    return sorted(PARSED_DIR.glob("*_parsed_*.json"))


def _load(path: Path) -> SystemRequirement:
    return SystemRequirement.model_validate_json(path.read_text(encoding="utf-8"))


def _tag_resolves(equipment, tag: str) -> bool:
    """A tag resolves if it appears in some equipment item's ``name`` or ``type``.

    The E2S1 ``local`` backend historically embeds the engineering tag in the
    ``type`` field (e.g. ``"type": "Valve/Actuator (EV-101)"``) while the ``api``
    backend puts it in ``name``. Accepting either keeps grounding valid across
    both backends.
    """
    for eq in equipment:
        if tag in eq.name or tag in eq.type:
            return True
    return False


class SchemaValidationTests(unittest.TestCase):
    def test_all_artifacts_deserialize_to_system_requirement(self) -> None:
        files = _parsed_files()
        self.assertGreater(len(files), 0, "no *_parsed_*.json artifacts found")
        for f in files:
            with self.subTest(file=f.name):
                obj = _load(f)
                self.assertIsInstance(obj, SystemRequirement)


class RequiredFieldTests(unittest.TestCase):
    def test_equipment_items_have_non_empty_name_and_type(self) -> None:
        for f in _parsed_files():
            with self.subTest(file=f.name):
                req = _load(f)
                self.assertTrue(req.equipment_list, "equipment_list must not be empty")
                for eq in req.equipment_list:
                    self.assertTrue(eq.name.strip())
                    self.assertTrue(eq.type.strip())

    def test_sequences_start_at_1_with_non_empty_descriptions(self) -> None:
        for f in _parsed_files():
            with self.subTest(file=f.name):
                req = _load(f)
                self.assertTrue(req.sequences, "sequences must not be empty")
                for seq in req.sequences:
                    self.assertTrue(seq.description.strip())

    def test_interlocks_have_non_empty_condition_and_action(self) -> None:
        for f in _parsed_files():
            with self.subTest(file=f.name):
                req = _load(f)
                self.assertTrue(req.interlocks, "interlocks must not be empty")
                for il in req.interlocks:
                    self.assertTrue(il.condition.strip())
                    self.assertTrue(il.action.strip())


class SequenceIntegrityTests(unittest.TestCase):
    def test_step_ids_are_monotonic_and_continuous(self) -> None:
        for f in _parsed_files():
            with self.subTest(file=f.name):
                req = _load(f)
                ids = [s.step_id for s in req.sequences]
                self.assertEqual(
                    ids,
                    list(range(1, len(ids) + 1)),
                    "step_ids must be exactly 1, 2, 3, ... with no gaps",
                )


class GroundingTests(unittest.TestCase):
    def test_referenced_device_tags_resolve_to_equipment_list(self) -> None:
        for f in _parsed_files():
            with self.subTest(file=f.name):
                req = _load(f)
                texts = [il.condition for il in req.interlocks]
                texts += [il.action for il in req.interlocks]
                texts += [s.description for s in req.sequences]
                tags = sorted(set(_TAG_RE.findall(" || ".join(texts))))
                for tag in tags:
                    self.assertTrue(
                        _tag_resolves(req.equipment_list, tag),
                        f"device tag {tag!r} from interlock/sequence text "
                        f"does not map to any item in equipment_list",
                    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
