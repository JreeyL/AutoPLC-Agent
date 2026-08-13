"""Generate Gherkin .feature files from parsed SystemRequirement JSON (E2S2T1).

This is the main execution script for the BDD/Gherkin-generation stage. It
consumes the *output* of E2S1 (a ``data/parsed/<stem>_parsed_<backend>.json``
file produced by :mod:`src.req_parser`), not a raw ``.txt`` requirement, and
turns it into a standard Gherkin ``.feature`` file under ``data/gherkin/``.

The conversion is deliberately **per source item, not one batch call**: each
:class:`~src.schemas.ControlSequence` step and each
:class:`~src.schemas.Interlock` is turned into one
:class:`~src.gherkin_schemas.GherkinScenario` via its own
``.with_structured_output()`` call. As documented in
:mod:`src.gherkin_schemas`, this isolates failures -- a malformed or failed
item is skipped with a warning while the remaining items still generate
cleanly, working around the local model's unreliability on large multi-item
structured outputs. The :class:`~src.gherkin_schemas.GherkinFeature` is then
assembled in Python from the collected scenarios.

Usage::

    python -m src.gherkin_gen data/parsed/sample_control_parsed_local.json
"""

import argparse
import re
import sys
import time
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

try:
    # When run as a module (python -m src.gherkin_gen).
    from src.gherkin_schemas import GherkinFeature, GherkinScenario
    from src.req_parser import build_llm
    from src.schemas import ControlSequence, Interlock, SystemRequirement
except ImportError:
    # When run directly from inside the src/ directory.
    from gherkin_schemas import GherkinFeature, GherkinScenario
    from req_parser import build_llm
    from schemas import ControlSequence, Interlock, SystemRequirement


SYSTEM_PROMPT = (
    "You are an expert BDD test engineer specializing in industrial "
    "automation and PLC control logic. Your task is to convert a single PLC "
    "control requirement item into exactly one concrete, executable Gherkin "
    "scenario expressed as Given (pre-conditions), When (triggering actions), "
    "and Then (expected outcomes)."
)

# Shared constraints appended to every per-item prompt. These mirror
# req_parser.py's no-hallucination principle and call out the abstract
# placeholder failure mode observed in this project's own E2S1 local output.
INSTRUCTION = (
    "Strict rules:\n"
    "- Use ONLY the information in the single source item provided below. Do "
    "NOT invent any scenario, step, condition, action, or piece of equipment "
    "that is not present in that item.\n"
    "- Every Given/When/Then string must be concrete and executable, naming "
    "the actual signal, device, or state, e.g. 'the signal light SL-301 turns "
    "green' or 'pump PMP-200 stops'. Do NOT emit abstract, placeholder-style "
    "phrases such as 'Signal Light State Change' or 'Pump Action' -- a "
    "scenario step must read like something a tester can actually observe.\n"
    "- Do NOT include the literal words 'Given', 'When', or 'Then' inside the "
    "returned strings; the renderer adds those keywords separately.\n"
    "- Reference equipment only by name inside the step strings; equipment is "
    "never its own scenario."
)

# Mapping rule shown to the model for a ControlSequence step.
STEP_MAPPING = (
    "This source item is ONE step of the normal operating control sequence. "
    "Split its single narrative description across the three categories:\n"
    "- given: the pre-condition(s) that must already hold before this step.\n"
    "- when: the triggering action that starts this step.\n"
    "- then: the resulting outcome once the action completes.\n"
    "If the source item's description does not state or clearly imply a "
    "precondition, return an empty list for 'given' rather than inventing one. "
    "An empty given list is valid per the schema and is strongly preferred over "
    "fabricated content such as 'the system is ready'.\n"
    "Example: from 'When the operator presses the start pushbutton, SL-301 "
    "must turn green.' produce given=[] (no precondition stated), when=['the "
    "operator presses the start pushbutton'], then=['the signal light SL-301 "
    "turns green']."
)

# Mapping rule shown to the model for an Interlock.
INTERLOCK_MAPPING = (
    "This source item is ONE safety interlock. Map it as:\n"
    "- given/when: the triggering event described by the interlock's "
    "'condition' (the hazardous state and the moment it occurs).\n"
    "- then: the forced safety response described by the interlock's "
    "'action'.\n"
    "If the interlock's condition does not state or clearly imply a separate "
    "precondition that must already hold, return an empty list for 'given' "
    "rather than inventing one. An empty given list is valid per the schema and "
    "is strongly preferred over fabricated content such as 'the system is "
    "ready'.\n"
    "Example: from condition='Emergency Stop button is pressed', "
    "action='SL-301 must immediately switch to red' produce when=['the "
    "operator presses the Emergency Stop button'], then=['the signal light "
    "SL-301 immediately switches to red']."
)


def load_requirement(input_path: Path) -> SystemRequirement:
    """Read and validate a parsed SystemRequirement JSON file.

    A missing file, empty file, or JSON that fails SystemRequirement
    validation is treated as a fatal error (``sys.exit(1)``), matching
    req_parser.py's error-handling style.
    """
    if not input_path.is_file():
        print(f"❌ Input file not found: {input_path}")
        sys.exit(1)

    raw = input_path.read_text(encoding="utf-8").strip()
    if not raw:
        print(f"❌ Input file is empty: {input_path}")
        sys.exit(1)

    try:
        return SystemRequirement.model_validate_json(raw)
    except ValidationError as exc:
        print(
            f"❌ Input is not a valid SystemRequirement JSON: {input_path}\n{exc}"
        )
        sys.exit(1)


def resolve_output_path(input_path: Path, backend: str) -> tuple[Path, str]:
    """Map a parsed-JSON input to its .feature destination.

    The input is named ``<stem>_parsed_<input_backend>.json``. The ``<stem>``
    is recovered from the filename, but the output suffix reflects ``backend``
    -- the ``--backend`` actually used for this run's generation calls -- not
    the input JSON's backend, so the filename tracks how the .feature was made
    and local/api runs coexist and can be diffed::

        sample_control_parsed_local.json --backend api
            -> data/gherkin/sample_control_api.feature
        signal_light_demo_parsed_api.json --backend api
            -> data/gherkin/signal_light_demo_api.feature

    The input JSON's own backend tag is used only to strip the ``_parsed_*``
    suffix off the stem; it does not appear in the output name.

    Returns ``(output_path, stem)``. The ``data/gherkin/`` directory (a sibling
    of ``data/parsed/``) is created if it does not yet exist. A filename that
    does not follow the ``_parsed_<backend>`` convention is a fatal error.
    """
    name = input_path.stem  # filename without the .json extension
    if "_parsed_" not in name:
        print(
            "❌ Input filename does not match the expected "
            f"'<stem>_parsed_<backend>.json' convention: {input_path.name}"
        )
        sys.exit(1)

    stem, _input_backend = name.rsplit("_parsed_", 1)
    output_dir = input_path.resolve().parent.parent / "gherkin"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{stem}_{backend}.feature", stem


# Tokens below this length are too generic to count as concrete grounding
# (articles, prepositions, "is", "the", ...). 4+ characters keeps real
# domain words (signal, light, pump, green, pressed, ...) while discarding
# filler, with no hand-maintained stop-word list to drift out of date.
_MIN_GROUNDING_WORD_LEN = 4


def _content_words(text: str) -> set[str]:
    """Lowercased alphanumeric/hyphen tokens of meaningful length."""
    return {
        word
        for word in re.findall(r"[a-z0-9\-]+", text.lower())
        if len(word) >= _MIN_GROUNDING_WORD_LEN
    }


def flag_unsupported_given(
    scenario: GherkinScenario,
    source_text: str,
    equipment_names: list[str],
) -> GherkinScenario:
    """Drop fabricated 'given' steps that share no grounding with the source.

    Deterministic, prompt-independent backstop against invented preconditions
    (e.g. a generic "the system is ready"). A given entry is kept only if it
    is concretely grounded in the item it came from -- it either mentions an
    equipment name from ``equipment_names`` or shares at least one meaningful
    content word with ``source_text``. Anything else is dropped with a warning.
    Empty/whitespace-only entries are left untouched here; they are handled by
    :func:`render_feature`'s filter. No LLM call is made. Mutates and returns
    ``scenario`` for convenience.
    """
    equip_lower = [name.lower() for name in equipment_names if name.strip()]
    source_words = _content_words(source_text)

    kept: list[str] = []
    for entry in scenario.given:
        text = entry.strip()
        if not text:
            # Empty entry: render_feature() is responsible for filtering it.
            kept.append(entry)
            continue
        lowered = text.lower()
        grounded = any(name in lowered for name in equip_lower) or bool(
            _content_words(text) & source_words
        )
        if grounded:
            kept.append(entry)
        else:
            print(
                f"⚠️  Scenario '{scenario.name}': dropped ungrounded given "
                f"entry: '{text}'"
            )
    scenario.given = kept
    return scenario


def scenario_from_step(
    structured_llm, step: ControlSequence, equipment_names: list[str]
) -> GherkinScenario:
    """Run one per-item LLM call converting a ControlSequence step."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", f"{SYSTEM_PROMPT}\n\n{INSTRUCTION}\n\n{STEP_MAPPING}"),
            (
                "human",
                "Source item (one control-sequence step) as JSON:\n{item}",
            ),
        ]
    )
    chain = prompt | structured_llm
    scenario: GherkinScenario = chain.invoke({"item": step.model_dump_json()})
    # Stamp provenance deterministically rather than trusting the model.
    scenario.source_step_id = step.step_id
    scenario.source_interlock_condition = None
    # Deterministic backstop against fabricated preconditions.
    flag_unsupported_given(scenario, step.description, equipment_names)
    return scenario


def scenario_from_interlock(
    structured_llm, interlock: Interlock, equipment_names: list[str]
) -> GherkinScenario:
    """Run one per-item LLM call converting an Interlock."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", f"{SYSTEM_PROMPT}\n\n{INSTRUCTION}\n\n{INTERLOCK_MAPPING}"),
            (
                "human",
                "Source item (one safety interlock) as JSON:\n{item}",
            ),
        ]
    )
    chain = prompt | structured_llm
    scenario: GherkinScenario = chain.invoke(
        {"item": interlock.model_dump_json()}
    )
    # Interlock has no numeric id; trace back by its verbatim condition text.
    scenario.source_step_id = None
    scenario.source_interlock_condition = interlock.condition
    # The given/when derive from the interlock's condition, so ground against
    # that text. Deterministic backstop against fabricated preconditions.
    flag_unsupported_given(scenario, interlock.condition, equipment_names)
    return scenario


def generate_feature_meta(llm, requirement: SystemRequirement) -> GherkinFeature:
    """Generate the feature title and description via one real LLM call.

    Binds GherkinFeature for structured output but uses only ``title`` and
    ``description`` from the result; the scenario list is assembled separately
    in Python.
    """
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                f"{SYSTEM_PROMPT}\n\n{INSTRUCTION}\n\n"
                "Given the full structured requirement below, produce only a "
                "concise feature 'title' (a short noun phrase naming the "
                "overall capability) and a 1-3 sentence 'description' "
                "summarizing the behaviour it covers. Leave 'scenarios' empty; "
                "the scenarios are assembled separately.",
            ),
            ("human", "Full requirement as JSON:\n{requirement}"),
        ]
    )
    chain = prompt | llm.with_structured_output(GherkinFeature)
    return chain.invoke({"requirement": requirement.model_dump_json()})


def render_feature(feature: GherkinFeature) -> str:
    """Render a GherkinFeature as standard .feature text (no LLM, no validation).

    Guarantees syntactic correctness regardless of LLM output quality: it only
    formats keywords and indentation, never inspects content. The first item in
    each Given/When/Then list uses the bare keyword; subsequent items use
    ``And``. Empty/whitespace-only steps are filtered before rendering so a
    bare ``Given``/``When``/``Then`` line can never be emitted; a removal is
    reported as a warning rather than fixed silently.
    """
    lines: list[str] = [f"Feature: {feature.title}"]
    for desc_line in feature.description.splitlines() or [feature.description]:
        lines.append(f"  {desc_line}")

    for scenario in feature.scenarios:
        lines.append("")
        lines.append(f"  Scenario: {scenario.name}")
        for keyword, steps in (
            ("Given", scenario.given),
            ("When", scenario.when),
            ("Then", scenario.then),
        ):
            filtered = [step for step in steps if step.strip()]
            removed = len(steps) - len(filtered)
            if removed:
                entry_word = "entry" if removed == 1 else "entries"
                print(
                    f"⚠️  Scenario '{scenario.name}': filtered {removed} empty "
                    f"{keyword.lower()} {entry_word}"
                )
            for index, step in enumerate(filtered):
                word = keyword if index == 0 else "And"
                lines.append(f"    {word} {step}")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a parsed SystemRequirement JSON file (E2S1 output) into a "
            "Gherkin .feature file."
        )
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Path to the parsed requirement JSON file "
        "(e.g. data/parsed/sample_control_parsed_local.json).",
    )
    parser.add_argument(
        "--backend",
        choices=["local", "api"],
        default="local",
        help="Inference backend used for generation. 'local' (default) uses "
        "the LM Studio server on the Windows host; 'api' uses the Gemini "
        "cloud API (requires GEMINI_API_KEY) for demos where local inference "
        "is too slow.",
    )
    parser.add_argument(
        "--call-delay",
        type=float,
        default=5.0,
        help="Seconds to sleep after each per-item LLM call, applied ONLY when "
        "--backend api (the local backend is never delayed). The 5-second "
        "default targets roughly 12 requests/minute, leaving headroom under "
        "the api backend's 15 RPM free-tier ceiling.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path: Path = args.input_file

    # Component 1: File reading and validation.
    requirement = load_requirement(input_path)
    output_path, _stem = resolve_output_path(input_path, args.backend)

    # Reuse req_parser.py's backend construction unchanged.
    llm = build_llm(args.backend)
    structured_llm = llm.with_structured_output(GherkinScenario)

    # Components 2 & 3: one per-item structured call each, with failure
    # isolation -- a single failed item is warned about and skipped.
    # Equipment names ground the deterministic given-fabrication check below.
    equipment_names = [e.name for e in requirement.equipment_list]

    scenarios: list[GherkinScenario] = []
    seq_count = 0
    for step in requirement.sequences:
        print(f"Generating scenario for sequence step {step.step_id}...", flush=True)
        try:
            scenarios.append(
                scenario_from_step(structured_llm, step, equipment_names)
            )
            seq_count += 1
        except Exception as exc:  # noqa: BLE001 - isolate per-item failure.
            print(
                f"⚠️  Skipping sequence step {step.step_id}: generation "
                f"failed ({exc})"
            )
        # Space out api calls to stay under the free-tier RPM ceiling; the
        # local backend has no such limit so it is never delayed.
        if args.backend == "api":
            time.sleep(args.call_delay)

    interlock_count = 0
    for interlock in requirement.interlocks:
        print(
            f"Generating scenario for interlock '{interlock.condition}'...",
            flush=True,
        )
        try:
            scenarios.append(
                scenario_from_interlock(
                    structured_llm, interlock, equipment_names
                )
            )
            interlock_count += 1
        except Exception as exc:  # noqa: BLE001 - isolate per-item failure.
            print(
                f"⚠️  Skipping interlock '{interlock.condition}': generation "
                f"failed ({exc})"
            )
        # Space out api calls to stay under the free-tier RPM ceiling; the
        # local backend has no such limit so it is never delayed.
        if args.backend == "api":
            time.sleep(args.call_delay)

    # One additional real LLM call for the feature title/description, then
    # assemble the final GherkinFeature in Python from the collected scenarios.
    # This is a required call: a failure propagates and exits the script,
    # consistent with load_requirement()/build_llm() -- no fallback file.
    print("Generating feature title and description...", flush=True)
    meta = generate_feature_meta(llm, requirement)

    feature = GherkinFeature(
        title=meta.title, description=meta.description, scenarios=scenarios
    )

    # Component 4: deterministic rendering and output.
    output_path.write_text(render_feature(feature), encoding="utf-8")

    print(
        f"✅ Generated {len(scenarios)} scenarios "
        f"({seq_count} from sequences, {interlock_count} from interlocks). "
        f"Saved to {output_path}."
    )


if __name__ == "__main__":
    main()
