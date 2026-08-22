"""PLCopen TC6 XML validation tests (E3S2T2).

Validates every exported PLCopen XML in ``data/plc/xml/`` with
``src.plcopen_xml_validator`` and cross-checks it against the originating
``data/ast/*.json``: schema-shaped structure and metadata completeness,
POU interface variable types, ``body > ST`` code integrity, and AST provenance
traceability.
"""

from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from src.ast_schemas import PLC_AST
from src.plcopen_xml_exporter import PLCOPEN_NS
from src.plcopen_xml_validator import validate_plcopen_directory, validate_plcopen_xml
from src.st_gen import sanitize_var_name


XML_DIR = Path("data/plc/xml")
AST_DIR = Path("data/ast")


def _xml_files() -> list[Path]:
    return sorted(XML_DIR.glob("*.xml"))


def _ast_for(xml_path: Path) -> PLC_AST:
    return PLC_AST.model_validate_json((AST_DIR / f"{xml_path.stem}.json").read_text(encoding="utf-8"))


class ValidatorSuitesTests(unittest.TestCase):
    def test_all_exported_xml_validate(self) -> None:
        results = validate_plcopen_directory(XML_DIR)
        self.assertEqual(len(results), len(_xml_files()))
        for result, xml_path in zip(results, _xml_files()):
            with self.subTest(file=xml_path.name):
                self.assertTrue(result.valid, f"{xml_path.name}: {result.errors}")


class SchemaStructureTests(unittest.TestCase):
    def test_root_namespace_and_project(self) -> None:
        for xml_path in _xml_files():
            with self.subTest(file=xml_path.name):
                root = ET.parse(xml_path).getroot()
                self.assertEqual(root.tag, f"{{{PLCOPEN_NS}}}project")

    def test_header_and_pou_sections_present(self) -> None:
        for xml_path in _xml_files():
            with self.subTest(file=xml_path.name):
                root = ET.parse(xml_path).getroot()
                ns = f"{{{PLCOPEN_NS}}}"
                self.assertIsNotNone(root.find(f"{ns}fileHeader"))
                self.assertIsNotNone(root.find(f"{ns}contentHeader"))
                pou = root.find(f"{ns}types/{ns}pous/{ns}pou")
                self.assertIsNotNone(pou)
                self.assertEqual(pou.attrib["pouType"], "program")
                self.assertTrue(pou.attrib["name"])
                self.assertIsNotNone(pou.find(f"{ns}interface/{ns}localVars"))
                self.assertIsNotNone(pou.find(f"{ns}body/{ns}ST"))


class MetadataTests(unittest.TestCase):
    def test_file_header_metadata_is_complete(self) -> None:
        for xml_path in _xml_files():
            with self.subTest(file=xml_path.name):
                root = ET.parse(xml_path).getroot()
                fh = root.find(f"{{{PLCOPEN_NS}}}fileHeader")
                for attr in ("companyName", "productName", "productVersion", "creationDateTime"):
                    self.assertTrue(fh.attrib.get(attr),
                                    f"{xml_path.name}: fileHeader missing {attr}")

    def test_content_header_name_matches_program(self) -> None:
        for xml_path in _xml_files():
            with self.subTest(file=xml_path.name):
                root = ET.parse(xml_path).getroot()
                ns = f"{{{PLCOPEN_NS}}}"
                ch_name = root.find(f"{ns}contentHeader").attrib["name"]
                pou_name = root.find(f"{ns}types/{ns}pous/{ns}pou").attrib["name"]
                self.assertEqual(ch_name, pou_name)


class VariableConsistencyTests(unittest.TestCase):
    def test_pou_variables_have_names_and_types(self) -> None:
        for xml_path in _xml_files():
            with self.subTest(file=xml_path.name):
                root = ET.parse(xml_path).getroot()
                ns = f"{{{PLCOPEN_NS}}}"
                local_vars = root.find(f"{ns}types/{ns}pous/{ns}pou/{ns}interface/{ns}localVars")
                vars_ = local_vars.findall(f"{ns}variable")
                self.assertGreater(len(vars_), 0)
                for v in vars_:
                    self.assertTrue(v.attrib["name"])
                    self.assertIsNotNone(v.find(f"{ns}type/{ns}BOOL"))

    def test_xml_variables_match_ast_devices(self) -> None:
        for xml_path in _xml_files():
            with self.subTest(file=xml_path.name):
                ast = _ast_for(xml_path)
                root = ET.parse(xml_path).getroot()
                ns = f"{{{PLCOPEN_NS}}}"
                local_vars = root.find(f"{ns}types/{ns}pous/{ns}pou/{ns}interface/{ns}localVars")
                declared = {v.attrib["name"] for v in local_vars.findall(f"{ns}variable")}
                expected = {sanitize_var_name(d.name) for d in ast.devices}
                self.assertTrue(expected <= declared)


class BodyAndTraceabilityTests(unittest.TestCase):
    def test_st_body_is_non_empty_and_structured(self) -> None:
        for xml_path in _xml_files():
            with self.subTest(file=xml_path.name):
                root = ET.parse(xml_path).getroot()
                ns = f"{{{PLCOPEN_NS}}}"
                st = root.find(f"{ns}types/{ns}pous/{ns}pou/{ns}body/{ns}ST")
                body = st.text or ""
                self.assertGreater(len(body.strip()), 0)
                self.assertIn("PROGRAM", body)
                self.assertIn("END_PROGRAM", body)

    def test_st_body_preserves_ast_provenance_traceability(self) -> None:
        for xml_path in _xml_files():
            with self.subTest(file=xml_path.name):
                ast = _ast_for(xml_path)
                root = ET.parse(xml_path).getroot()
                ns = f"{{{PLCOPEN_NS}}}"
                st = root.find(f"{ns}types/{ns}pous/{ns}pou/{ns}body/{ns}ST")
                body = st.text or ""
                for step in ast.sequence:
                    self.assertIn(f"Source step: {step.step_id}", body,
                                  f"{step.node_id} trace missing from {xml_path.name}")
                self.assertIn("Source", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
