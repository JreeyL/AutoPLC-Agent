"""PLCopen TC6 XML export tests (E3S2T1).

Validates that ``src.plcopen_xml_exporter`` produces well-formed, schema-shaped
PLCopen TC6 XML 2.01 documents from every ``data/ast/*.json``: well-formed XML
with the correct root and namespace, required project sections
(``fileHeader`` / ``contentHeader`` / ``types > pous > pou`` /
``interface`` / ``body > ST``), interface ``localVars`` matching the AST
devices, and the ST body carrying generator traceability comments.
"""

from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from src.ast_schemas import PLC_AST
from src.plcopen_xml_exporter import PLCOPEN_NS, _q, export_ast_to_plcopen_xml
from src.st_gen import sanitize_var_name


def _export_all(tmp: Path) -> list[Path]:
    results = []
    for ast_path in sorted(Path("data/ast").glob("*.json")):
        results.append(export_ast_to_plcopen_xml(ast_path, tmp / f"{ast_path.stem}.xml"))
    return results


def _pou(root: ET.Element) -> ET.Element:
    _types = root.find(_q("types"))
    _pous = _types.find(_q("pous"))
    return _pous.find(_q("pou"))


class XmlWellFormedTests(unittest.TestCase):
    def test_all_ast_export_and_parse_well_formed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = _export_all(Path(tmp))
            self.assertGreater(len(files), 0)
            for xml_path in files:
                with self.subTest(file=xml_path.name):
                    root = ET.parse(xml_path).getroot()
                    self.assertEqual(root.tag, f"{{{PLCOPEN_NS}}}project")

    def test_root_schema_location_and_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = ET.parse(_export_all(Path(tmp))[0]).getroot()
            self.assertEqual(root.tag, f"{{{PLCOPEN_NS}}}project")
            self.assertEqual(
                root.attrib.get(f"{{http://www.w3.org/2001/XMLSchema-instance}}schemaLocation"),
                f"{PLCOPEN_NS} http://www.plcopen.org/xml/tc6_0201_v2.01.xsd",
            )


class SchemaStructureTests(unittest.TestCase):
    def test_required_sections_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for xml_path in _export_all(Path(tmp)):
                with self.subTest(file=xml_path.name):
                    root = ET.parse(xml_path).getroot()
                    self.assertIsNotNone(root.find(_q("fileHeader")))
                    self.assertIsNotNone(root.find(_q("contentHeader")))
                    pou = _pou(root)
                    self.assertIsNotNone(pou)
                    self.assertIsNotNone(pou.find(f"{_q('interface')}/{_q('localVars')}"))
                    self.assertIsNotNone(pou.find(f"{_q('body')}/{_q('ST')}"))

    def test_pou_has_program_name_and_program_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ast_paths = sorted(Path("data/ast").glob("*.json"))
            for ast_path in ast_paths:
                with self.subTest(file=ast_path.name):
                    ast = PLC_AST.model_validate_json(ast_path.read_text(encoding="utf-8"))
                    root = ET.parse(
                        export_ast_to_plcopen_xml(ast_path, Path(tmp) / f"{ast_path.stem}.xml")
                    ).getroot()
                    self.assertEqual(_pou(root).attrib["pouType"], "program")


class VariableDeclarationTests(unittest.TestCase):
    def test_local_vars_match_ast_devices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for ast_path in sorted(Path("data/ast").glob("*.json")):
                with self.subTest(file=ast_path.name):
                    ast = PLC_AST.model_validate_json(ast_path.read_text(encoding="utf-8"))
                    root = ET.parse(
                        export_ast_to_plcopen_xml(ast_path, Path(tmp) / f"{ast_path.stem}.xml")
                    ).getroot()
                    var_el = _pou(root).find(f"{_q('interface')}/{_q('localVars')}")
                    declared = {
                        v.attrib["name"] for v in var_el.findall(_q("variable"))
                    }
                    expected = {sanitize_var_name(d.name) for d in ast.devices}
                    self.assertTrue(expected <= declared,
                                    f"{ast_path.name}: missing vars "
                                    f"{expected - declared}")
                    for v in var_el.findall(_q("variable")):
                        self.assertIsNotNone(v.find(f"{_q('type')}/{_q('BOOL')}"))


class TraceabilityTests(unittest.TestCase):
    def test_st_body_has_generator_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for ast_path in sorted(Path("data/ast").glob("*.json")):
                with self.subTest(file=ast_path.name):
                    root = ET.parse(
                        export_ast_to_plcopen_xml(ast_path, Path(tmp) / f"{ast_path.stem}.xml")
                    ).getroot()
                    st = _pou(root).find(f"{_q('body')}/{_q('ST')}")
                    body_text = st.text or ""
                    self.assertIn("Source", body_text,
                                  f"{ast_path.name}: ST body lacks traceability comments")

    def test_st_body_references_ast_sequence_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for ast_path in sorted(Path("data/ast").glob("*.json")):
                with self.subTest(file=ast_path.name):
                    ast = PLC_AST.model_validate_json(ast_path.read_text(encoding="utf-8"))
                    root = ET.parse(
                        export_ast_to_plcopen_xml(ast_path, Path(tmp) / f"{ast_path.stem}.xml")
                    ).getroot()
                    st = _pou(root).find(f"{_q('body')}/{_q('ST')}")
                    body_text = st.text or ""
                    for step in ast.sequence:
                        self.assertIn(f"Source step: {step.step_id}", body_text,
                                      f"{ast_path.name}: missing step {step.step_id} trace")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
