"""Generate a PLC AST deterministically from requirement JSON + Gherkin .feature (E2S3, Approach B).

Unlike Approach A (:mod:`src.ast_gen_A`) which uses a single LLM call, Approach B
is 100 % deterministic.  It uses the ``gherkin-official`` Python library to parse
``.feature`` files and standard JSON parsing to read requirement files, merging
them into a validated :class:`~src.ast_schemas.PLC_AST` object using pure Python
logic and rule-based text matching.

Usage::

    python -m src.ast_gen_B \\
        data/parsed/signal_light_demo_parsed_api.json \\
        data/gherkin/signal_light_demo_api.feature
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner
from pydantic import ValidationError

try:
    from src.ast_schemas import (
        PLC_AST,
        DeviceNode,
        InterlockNode,
        SequenceStepNode,
    )
    from src.schemas import SystemRequirement
except ImportError:
    from ast_schemas import (
        PLC_AST,
        DeviceNode,
        InterlockNode,
        SequenceStepNode,
    )
    from schemas import SystemRequirement

# ---------------------------------------------------------------------------
# Stopwords for text matching
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset = frozenset({
    "the", "and", "for", "are", "was", "were", "been", "being",
    "have", "has", "had", "will", "would", "could", "should", "may",
    "might", "shall", "can", "must", "to", "of", "in", "on", "with",
    "at", "by", "from", "as", "into", "through", "during", "before",
    "after", "but", "not", "nor", "all", "each", "every", "both",
    "more", "most", "some", "such", "than", "too", "very", "just",
    "also", "when", "then", "else", "this", "that", "these", "those",
    "its", "any", "one", "two", "new", "now", "per", "via", "does",
    "done", "gets",
})


# ---------------------------------------------------------------------------
# Text-matching helpers  (deterministic, rule-based, no LLM)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    """Split *text* into a set of lowercased, meaningful tokens.

    Steps:
    1. Extract alphanumeric/hyphen/quote sequences (keeps names like ``EV-101`` intact).
    2. Remove short tokens (length ≤ 2) — this discards most single-letter or
       two-letter items that carry little semantic weight.
    3. Remove common English stopwords from the curated :data:`_STOPWORDS` set.

    The result is a pure set of content words used for Dice-coefficient matching
    between requirement step descriptions and Gherkin scenario steps.
    """
    tokens = re.findall(r"[a-z0-9][a-z0-9-']*", text.lower())
    return {t for t in tokens if len(t) > 2 and t not in _STOPWORDS}


def _match_score(text_a: str, text_b: str) -> float:
    """Dice coefficient **[*0*, *1*]** between the token sets of two texts.

    .. math::

        score = \\frac{2 \\, |A \\cap B|}{|A| + |B|}

    Returns 0 when either set is empty.
    """
    a_tokens = _tokenize(text_a)
    b_tokens = _tokenize(text_b)
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    return 2.0 * len(intersection) / (len(a_tokens) + len(b_tokens))


def _text_contains_name(text: str, name: str) -> bool:
    """Check whether *name* appears in *text* bounded by non-alnum characters.

    Uses word-boundary-style lookarounds so that ``"EV-101"`` does not
    register in ``"EV-1012"`` or ``"NEV-101"``, while correctly matching
    ``"SL-301"`` in ``"signal light SL-301 turns green"``.
    """
    escaped = re.escape(name.lower())
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text.lower()))


def _extract_scenarios(gherkin_ast: dict) -> list[dict]:
    """Pull scenario dicts from the parsed Gherkin AST.

    Only plain ``Scenario`` children are extracted (Background and Rule are
    not produced by the upstream Gherkin generator).
    """
    return [
        child["scenario"]
        for child in gherkin_ast.get("feature", {}).get("children", [])
        if "scenario" in child
    ]


def _best_scenario_for_text(
    text: str,
    scenarios: list[dict],
    threshold: float = 0.15,
) -> tuple[dict | None, float]:
    """Find the Gherkin scenario whose **combined step texts** best match *text*.

    Parameters
    ----------
    text:
        The requirement-side string to match (e.g. a step description or an
        interlock condition + action).
    scenarios:
        List of Gherkin scenario dicts extracted by :func:`_extract_scenarios`.
    threshold:
        Minimum :func:`_match_score` required to return a non-None scenario.

    Returns
    -------
    tuple:
        ``(scenario_dict | None, score)``.
    """
    best = (None, 0.0)
    for scenario in scenarios:
        step_text = " ".join(s["text"] for s in scenario.get("steps", []))
        score = _match_score(text, step_text)
        if score > best[1]:
            best = (scenario, score)
    if best[1] < threshold:
        return (None, 0.0)
    return best


def _extract_condition(
    scenario: dict | None,
    description: str,
) -> str | None:
    """Extract the triggering condition for a sequence step.

    Strategy
    ~~~~~~~~
    1. If *scenario* is not ``None``, return the text of its first
       ``When`` / ``Given`` step (the most authorative source for the
       trigger condition).
    2. Otherwise, fall back to a heuristic: if *description* starts with
       ``"When "`` or ``"If "``, clip the remainder up to the first comma
       or period.
    """
    if scenario is not None:
        for step in scenario.get("steps", []):
            kw = step.get("keyword", "").strip().lower()
            if kw in ("when", "given"):
                txt = step["text"].rstrip("., ")
                return txt if txt else None

    # Fallback heuristic.
    text = description.strip()
    for prefix in ("when ", "if "):
        if text.lower().startswith(prefix):
            remainder = text[len(prefix) :]
            end = len(remainder)
            for sep in (",", "."):
                pos = remainder.find(sep)
                if pos != -1:
                    end = min(end, pos)
            return remainder[:end].strip().rstrip("., ") or None

    return None


def _find_target_device(
    text: str,
    equipment_names: list[str],
) -> str | None:
    """Return the **first** equipment *name* appearing in *text*, or ``None``.

    Searches in the order of *equipment_names* and returns the earliest match
    as the primary target device for this step.
    """
    for name in equipment_names:
        if _text_contains_name(text, name):
            return name
    return None


def _find_affected_devices(
    text: str,
    equipment_names: list[str],
) -> list[str]:
    """Return **all** equipment *names* appearing in *text* (document order).

    Used for :attr:`InterlockNode.affected_devices` — any equipment
    referenced in the interlock condition or forced-action text is considered
    affected.
    """
    return [name for name in equipment_names if _text_contains_name(text, name)]


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------


def load_requirement(input_path: Path) -> SystemRequirement:
    """Read and validate a parsed ``SystemRequirement`` JSON file.

    A missing file, empty file, or JSON that fails
    :class:`~src.schemas.SystemRequirement` validation is a fatal error
    (``sys.exit(1)``), matching ``req_parser.py``'s error-handling style.
    """
    if not input_path.is_file():
        print(f"❌ Requirement file not found: {input_path}")
        sys.exit(1)

    raw = input_path.read_text(encoding="utf-8").strip()
    if not raw:
        print(f"❌ Requirement file is empty: {input_path}")
        sys.exit(1)

    try:
        return SystemRequirement.model_validate_json(raw)
    except ValidationError as exc:
        print(
            f"❌ Requirement file is not a valid SystemRequirement JSON: "
            f"{input_path}\n{exc}"
        )
        sys.exit(1)


def load_and_parse_gherkin(
    gherkin_path: Path,
) -> tuple[dict, str]:
    """Parse a ``.feature`` file with **gherkin-official**.

    Returns
    -------
    tuple:
        ``(gherkin_ast_dict, feature_title)``.  The AST dictionary follows the
        standard gherkin-official schema: ``feature > children > scenario >
        steps``.
    """
    if not gherkin_path.is_file():
        print(f"❌ Gherkin file not found: {gherkin_path}")
        sys.exit(1)

    text = gherkin_path.read_text(encoding="utf-8").strip()
    if not text:
        print(f"❌ Gherkin file is empty: {gherkin_path}")
        sys.exit(1)

    parser = Parser()
    scanner = TokenScanner(text)
    try:
        gherkin_ast = parser.parse(scanner)
    except Exception as exc:  # noqa: BLE001 — surface Gherkin parse errors clearly.
        print(f"❌ Failed to parse Gherkin file: {gherkin_path}\n{exc}")
        sys.exit(1)

    feature_title = gherkin_ast.get("feature", {}).get("name", "")
    return gherkin_ast, feature_title


def resolve_output_path(requirement_path: Path) -> Path:
    """Map parsed-requirement path → ``data/ast/<stem>_AST_B.json``.

    The ``<stem>`` is recovered by stripping the ``_parsed_<backend>`` suffix
    from the requirement filename (same convention as ``ast_gen_A.py``), then
    appending ``_AST_B`` to distinguish Approach B outputs from Approach A
    outputs::

        signal_light_demo_parsed_api.json
            → data/ast/signal_light_demo_AST_B.json

    The ``data/ast/`` directory is created if it does not exist.
    """
    name = requirement_path.stem  # e.g. "signal_light_demo_parsed_api"
    if "_parsed_" not in name:
        print(
            "❌ Requirement filename does not match the expected "
            f"'<stem>_parsed_<backend>.json' convention: {requirement_path.name}"
        )
        sys.exit(1)

    stem = name.rsplit("_parsed_", 1)[0]  # e.g. "signal_light_demo"
    output_dir = requirement_path.resolve().parent.parent / "ast"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{stem}_AST_B.json"


# ---------------------------------------------------------------------------
# Core AST construction
# ---------------------------------------------------------------------------


def build_ast(req_path: Path, feature_path: Path) -> PLC_AST:
    """Deterministically build a :class:`~src.ast_schemas.PLC_AST`.

    This is the heart of Approach B.  The pipeline is:

    1. **Load** the :class:`SystemRequirement` and parse the Gherkin ``.feature``.
    2. **DeviceNodes** — trivial 1:1 mapping from ``equipment_list``.
    3. **SequenceStepNodes** — one per ``ControlSequence`` step, with
       cross-referencing to the best-matching Gherkin scenario for
       ``source_scenario`` and ``condition``.
    4. **InterlockNodes** — one per ``Interlock``, again cross-referenced to
       the best-matching scenario.
    5. **Assemble** into a :class:`PLC_AST` and return it.

    The returned object is validated by Pydantic at construction time.  The
    ``source_requirement_file`` and ``source_gherkin_file`` fields are left
    empty here — they are stamped by the caller (:func:`main`) after the AST
    is built, maintaining the same discipline as Approach A.
    """
    # ---- Step 1: load inputs ------------------------------------------------
    requirement = load_requirement(req_path)
    gherkin_ast, feature_title = load_and_parse_gherkin(feature_path)
    scenarios = _extract_scenarios(gherkin_ast)
    equipment_names = [eq.name for eq in requirement.equipment_list]

    # ---- Step 2: DeviceNodes ------------------------------------------------
    devices = [
        DeviceNode(
            node_id=f"DEV-{eq.name}",
            name=eq.name,
            device_type=eq.type,
            source_equipment=eq.name,
        )
        for eq in requirement.equipment_list
    ]

    # ---- Step 3: SequenceStepNodes ------------------------------------------
    sequence: list[SequenceStepNode] = []
    for seq in requirement.sequences:
        scenario, _ = _best_scenario_for_text(seq.description, scenarios)
        sequence.append(
            SequenceStepNode(
                node_id=f"SEQ-{seq.step_id}",
                step_id=seq.step_id,
                action=seq.description,
                target_device=_find_target_device(
                    seq.description, equipment_names
                ),
                condition=_extract_condition(scenario, seq.description),
                source_step_id=seq.step_id,
                source_scenario=scenario["name"] if scenario else None,
            )
        )

    # ---- Step 4: InterlockNodes ---------------------------------------------
    interlocks: list[InterlockNode] = []
    for idx, ilk in enumerate(requirement.interlocks, start=1):
        interlock_text = f"{ilk.condition} {ilk.action}"
        scenario, _ = _best_scenario_for_text(interlock_text, scenarios)
        interlocks.append(
            InterlockNode(
                node_id=f"ILK-{idx}",
                condition=ilk.condition,
                forced_action=ilk.action,
                affected_devices=_find_affected_devices(
                    interlock_text, equipment_names
                ),
                priority=1,
                source_interlock_condition=ilk.condition,
                source_scenario=scenario["name"] if scenario else None,
            )
        )

    # ---- Step 5: assemble ---------------------------------------------------
    return PLC_AST(
        feature_title=feature_title,
        devices=devices,
        sequence=sequence,
        interlocks=interlocks,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Configure and parse the command-line arguments.

    Exactly two positional arguments are required (no ``--backend`` flag —
    Approach B has no LLM backend to select).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Generate a PLC AST (E2S3 Approach B) deterministically from a "
            "parsed SystemRequirement JSON and a Gherkin .feature file. "
            "No LLM is used — the AST is assembled via pure Python logic."
        )
    )
    parser.add_argument(
        "req_file",
        type=Path,
        help=(
            "Path to the parsed requirement JSON file "
            "(e.g. data/parsed/signal_light_demo_parsed_api.json)."
        ),
    )
    parser.add_argument(
        "feature_file",
        type=Path,
        help=(
            "Path to the Gherkin .feature file "
            "(e.g. data/gherkin/signal_light_demo_api.feature)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Entry point — parse args, build AST, stamp provenance, write output."""
    args = parse_args()
    req_path: Path = args.req_file
    feature_path: Path = args.feature_file

    output_path = resolve_output_path(req_path)

    # Build the AST via deterministic pure-Python logic.
    print("Building AST deterministically...", flush=True)
    result = build_ast(req_path, feature_path)

    # Stamp provenance deterministically (same discipline as Approach A).
    result.source_requirement_file = str(req_path.resolve())
    result.source_gherkin_file = str(feature_path.resolve())

    # Re-validate the fully-populated object and write.
    validated = PLC_AST.model_validate(result.model_dump())
    output_path.write_text(validated.model_dump_json(indent=2), encoding="utf-8")

    print(
        f"✅ AST generated: {len(validated.devices)} devices, "
        f"{len(validated.sequence)} sequence steps, "
        f"{len(validated.interlocks)} interlocks. "
        f"Saved to {output_path}."
    )


if __name__ == "__main__":
    main()
