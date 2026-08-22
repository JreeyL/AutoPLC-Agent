"""PLCopen TC6 XML 2.01 validation (E3S2T2).

Validates exported PLCopen XML documents (``data/plc/xml/*.xml``) against the
project's PLCopen TC6 XML 2.01 required-element specification: correct
namespace and ``schemaLocation``, complete ``fileHeader`` / ``contentHeader``
metadata, a ``program`` POU with interface ``localVars`` carrying named,
typed variables, a non-empty ``body > ST`` with generator traceability
comments, and structural well-formedness. Uses ``lxml`` when available and
falls back to the standard ``xml.etree.ElementTree``.

No external XSD is required; conformance is checked against the published
TC6 v2.01 element set (namespace ``http://www.plcopen.org/xml/tc6_0201``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.plcopen_xml_exporter import DEFAULT_XML_DIR, PLCOPEN_NS

_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_REQUIRED_FH_ATTRS = ("companyName", "productName", "productVersion", "creationDateTime")


def _etree():
    """Return a parser module: lxml if available, else standard ElementTree."""
    try:
        from lxml import etree  # type: ignore
        return etree
    except ImportError:  # pragma: no cover - stdlib fallback path
        import xml.etree.ElementTree as etree
        return etree


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _find(child, tag_ns: str, local: str):
    return child.find(f"{tag_ns}{local}")


def validate_plcopen_xml(xml_path: Path | str) -> ValidationResult:
    """Validate one PLCopen XML document; return a :class:`ValidationResult`."""
    errors: list[str] = []
    et = _etree()

    try:
        root = et.parse(str(xml_path)).getroot()
    except Exception as exc:  # noqa: BLE001 - capture any parse failure
        return ValidationResult(valid=False, errors=[f"not well-formed: {exc}"])

    if root.tag.startswith("{"):
        ns_bare = root.tag[1: root.tag.rfind("}")]
        tag_ns = f"{{{ns_bare}}}"
    else:
        tag_ns, ns_bare = "", ""
    if not root.tag.endswith("}project") or ns_bare != PLCOPEN_NS:
        errors.append(f"root is not PLCopen project in namespace {PLCOPEN_NS}")

    schema_loc = root.attrib.get(f"{{{_XSI_NS}}}schemaLocation", "")
    if PLCOPEN_NS not in schema_loc:
        errors.append("missing/incorrect xsi:schemaLocation")

    fh = _find(root, tag_ns, "fileHeader")
    if fh is None:
        errors.append("missing fileHeader")
    else:
        for attr in _REQUIRED_FH_ATTRS:
            if not fh.attrib.get(attr):
                errors.append(f"fileHeader missing attribute '{attr}'")

    if _find(root, tag_ns, "contentHeader") is None:
        errors.append("missing contentHeader")

    types_el = _find(root, tag_ns, "types")
    pous = _find(types_el, tag_ns, "pous") if types_el is not None else None
    pou = _find(pous, tag_ns, "pou") if pous is not None else None
    if pou is None:
        errors.append("missing types/pous/pou")
    else:
        if pou.attrib.get("pouType") != "program":
            errors.append("pou pouType is not 'program'")
        if not pou.attrib.get("name"):
            errors.append("pou missing name attribute")

        interface = _find(pou, tag_ns, "interface")
        local_vars = _find(interface, tag_ns, "localVars") if interface is not None else None
        if local_vars is None:
            errors.append("missing interface/localVars")
        else:
            variables = local_vars.findall(f"{tag_ns}variable")
            if not variables:
                errors.append("localVars contains no variables")
            for var in variables:
                if not var.attrib.get("name"):
                    errors.append("variable missing name attribute")
                if _find(var, tag_ns, "type") is None:
                    errors.append(f"variable '{var.attrib.get('name')}' missing type")

        body = _find(pou, tag_ns, "body")
        st = _find(body, tag_ns, "ST") if body is not None else None
        st_text = (st.text or "") if st is not None else ""
        if st is None or not st_text.strip():
            errors.append("missing or empty body/ST")
        else:
            for marker in ("PROGRAM", "END_PROGRAM"):
                if marker not in st_text:
                    errors.append(f"ST body missing '{marker}'")
            if "Source" not in st_text:
                errors.append("ST body missing traceability comments")

    return ValidationResult(valid=not errors, errors=errors)


def validate_plcopen_directory(
    xml_dir: Path | str | None = None,
) -> list[ValidationResult]:
    """Validate every PLCopen XML under ``xml_dir`` (default ``data/plc/xml``)."""
    directory = Path(xml_dir) if xml_dir else DEFAULT_XML_DIR
    results = []
    for xml_path in sorted(directory.glob("*.xml")):
        results.append(validate_plcopen_xml(xml_path))
    return results
