# AutoPLC Agent - Jira Kanban Board

This document serves as a lightweight project management tracker representing a Jira Kanban board. It is organized into Epics, Stories, and Tasks.

## 📋 Epics

* **EPIC-1: Infrastructure & Environment Setup** (Local RAG and LLM setup)
* **EPIC-2: Core Agent Pipeline** (Requirement ingestion to PLC code generation)
* **EPIC-3: Validation & Export** (Testing, review workflows, and standard exports)

---

## 📌 Interim Presentation Feedback (8 Jul 2026)

Action items captured from supervisor's feedback during the interim presentation.

* **RAG Pipeline Stress Testing (EPIC-1 follow-up)**
  * Large document test: evaluate retrieval quality and response accuracy on a long document (e.g. 50+ pages) to assess how the pipeline degrades at scale.
  * Context window saturation test: observe generation quality when retrieved chunks fill the LLM's context window.
  * Input format diversity test (student-added): extend beyond `.txt` to PDF and other formats; verify that format conversion does not degrade retrieval quality.
  * Not blocking EPIC-2 progress; can be pursued in parallel.

* **RPC / Structured Function-Call Integration (E2S3 consideration)**
  * Kieran suggested exploring RPC (Remote Procedure Call) as a design pattern for LLM invocation: rather than having the LLM emit free-form JSON, structure its output as a trigger for a concrete function call (analogous to OpenAI function calling / tool use).
  * For E2S3 AST generation, this translates to a third candidate approach alongside (a) direct LLM JSON output and (b) third-party parsing library: (c) LLM triggers a structured AST builder via a function-call interface. All three approaches to be evaluated on output quality and correctness.

* **Negative / Failure-Path Testing (ongoing, all stages)**
  * Current verification samples are all simple happy-path inputs (signal light, basic valve control). Kieran noted the lack of failure-path and edge-case testing.
  * Planned: introduce more complex, realistic industrial requirement texts; design explicit negative test cases covering ambiguous or incomplete requirements, contradictory interlock conditions, and inputs missing key equipment information.
  * Applies across E2S1, E2S2, and future E2S3/E2S4 stages.

---

## 📝 To Do

### EPIC-3: Validation & Export

#### E3S1: Output artifact verification
* **[E3S1T1] Add pytest structural checks for parsed `SystemRequirement` artifacts** — complete.
  * Added `tests/test_parsed_requirements.py`: a fully offline, deterministic structural suite over `data/parsed/*_parsed_*.json`. Each artifact deserializes to the `SystemRequirement` model; equipment/sequence/interlock fields are non-empty; `step_id` is monotonic and continuous from 1; and device tags referenced in interlock/sequence text ground to `equipment_list` (matching `name` or `type` to stay valid for the `local` backend, which historically embeds tags in `type`). 6 tests pass; full suite now 36 tests.
* **[E3S1T2] Add pytest structural checks for Gherkin `.feature` artifacts** — complete.
  * Added `tests/test_gherkin_features.py`: a fully offline suite parsing `data/gherkin/*.feature` with `gherkin-official` — standard-Gherkin syntax validity, feature title / at-least-one-scenario, valid step keywords and a `When` + `Then` per scenario, and scenario coverage of the paired `data/parsed/*_parsed_*.json` items (steps + interlocks). 7 tests pass; full suite now 43 tests.
  * Known coverage gap: the E2S2 `local` backend skipped one source step for `sample_control_local.feature` (6 scenarios vs 7 source items); marked with `expectedFailure` (pytest `xfail` equivalent) so the gap is surfaced without failing the suite.
  * Traceability boundary: `.feature` text does not carry `source_step_id` / `source_interlock_condition` (they live on the in-memory `GherkinScenario` and are not emitted by the renderer); per-scenario traceability cannot be asserted from this artifact and is deferred to a generator-side change that persists the traceability JSON.
* **[E3S1T3] Add pytest structural checks for `PLC_AST` artifacts** — complete.
  * Added `tests/test_ast_validation.py`: a fully offline suite over every `data/ast/*.json` — schema deserialization to `PLC_AST`, non-empty devices with continuous `step_id` from 1, interlocks with non-empty condition/forced_action/affected_devices and `priority >= 1`, provenance stamps (`source_step_id` / `source_interlock_condition`) present with `source_requirement_file` / `source_gherkin_file` resolving to real files, and grounding of `device.source_equipment` into the source parsed `equipment_list` plus resolution of device tags referenced in sequence/interlock text. 8 tests pass; full suite now 51 tests.
* **[E3S1T4] Add pytest structural checks for generated ST artifacts** — complete.
  * Added `tests/test_st_validation.py`: a fully offline suite over `data/plc/st/*.st` with a two-tier check. Basic contract (all files): `PROGRAM`/`END_PROGRAM` wrapper, non-empty executable logic, no Markdown fences. Strict checks (Python-rendered deterministic + hybrid): `VAR`/`END_VAR` block, balanced `IF`/`END_IF`, traceability comments, `Sequence Logic` + `Safety Interlocks` section headers, and interlock-override placement after the sequence. LLM Direct (raw draft) is validated to the basic contract only, with strict ST conformance deferred to the MATIEC check (E3S1T7). 10 tests pass; full suite now 61 tests.
* **[E3S1T5] Add pytest structural checks for generated LD IR artifacts** — complete.
  * Added `tests/test_ld_ir_validation.py`: a fully offline suite over `data/plc/ld/*.json`. Common checks (all files): `LDProgram` schema validity, unique network IDs, legal contact/coil types, non-empty coil per network, sequence-before-interlock ordering, and a `source_ast_node_id` stamp per network. Rendered checks (deterministic + hybrid): `priority >= 1` and per-network step/interlock traceability. LLM Direct (comparison draft) is validated to the common contract plus non-negative priority and `source_ast_node_id`. 10 tests pass; full suite now 71 tests.
* **[E3S1T6] Extend the verification suite to hybrid generator outputs** — complete.
  * Added `tests/test_hybrid_validation.py`: a fully offline, strictly structural suite over `data/plc/st/*_st_hybrid_*.st` and `data/plc/ld/*_ld_hybrid_*.json` — hybrid capability structure only, no LLM and NO business-logic semantic review (that evaluation is deferred to E3S3T1). Verifies ST hybrid mechanism (TON declaration/invocation/`PT` consistency, valid REAL comparison operators, `// Hybrid` renderer markers), LD hybrid mechanism (valid analogue `operator`/`threshold`, positive timer metadata), per-sample capability coverage (`sample_control` -> timer+analogue, `signal_light_demo` -> colour), and api/local structural consistency. 11 tests pass; full suite now 82 tests.
* **[E3S1T7] Investigate MATIEC for IEC 61131-3 ST syntax / compile checking** — complete.
  * Added `src/matiec_checker.py`: a compiler wrapper locating `iec2c` (`is_matiec_available()`), discovering the MATIEC standard library (ieclib.txt), stripping `//` line comments (MATIEC only accepts `(* *)`), optionally synthesizing a minimal `CONFIGURATION`/`RESOURCE`/`TASK` wrapper for POU containment, copying the library into an isolated tempdir, running `iec2c`, and returning a `CompilationResult`; temp dirs are always cleaned up.
  * Added `tests/test_matiec_compilation.py` (7 tests, skip-if-not-available): every `data/plc/st/*.st` is compiled with `iec2c`. Deterministic + hybrid (`signal_light_demo`) compile successfully; LLM Direct `api` compiles. Known divergences marked `expectedFailure`: hybrid `sample_control` has a `REAL >= INT` literal (`tank_level_sensor >= 80`, needs `80.0`), and LLM Direct `local` outputs carry non-standard syntax (dangling `ELSIF` / missing `;`). Full suite now 89 tests.
  * Generator refinement action item: the `REAL >= INT` literal (`tank_level_sensor >= 80`) is isolated to `src/st_gen_hybrid.py`'s rendering template and is slated for a deterministic float-formatting fix (emit `80.0`) in subsequent generator refinement. LLM Direct `local` non-standard syntax also noted for follow-up.
* **[E3S1T8] Compile and validate generated PLC logic with OpenPLC Editor / Runtime (primary target)** — planned.
  * OpenPLC is the primary practical target for compiling and open-source runtime simulation in the Linux/WSL environment. Install OpenPLC Editor / Runtime in WSL, compile the generated ST (and LD IR exported as ST), and run open-source runtime simulation to confirm the logic behaves as specified.
  * Record any ST syntax deviations that MATIEC/OpenPLC surfaces and feed them back to the generators.
* **[E3S1T9] TIA Portal / PLCSIM validation — documentation-only feasibility study (lower priority)** — planned.
  * Siemens TIA Portal / PLCSIM is Windows-only, licensed commercial software that cannot run inside the Linux/WSL environment. Treat this as a lower-priority, documentation-only / theoretical feasibility study: describe how the generated artifacts would map to TIA Portal and how PLCSIM could be used for closed-loop simulation, without attempting a live run.

#### E3S2: PLCopen XML export
* **[E3S2T1] Create export module mapping PLC_AST to interoperable PLCopen XML** — planned.
* **[E3S2T2] Validate generated PLCopen XML** — planned.
  * Check XML schema conformance, required element completeness, traceability preservation, and readability by standard PLC engineering tools.

#### E3S3: Component tests and validation framework
* **[E3S3T1] Build a two-tier validation framework** — planned.
  * **Tier 1 — Deterministic grounding & schema validation:** consolidate the device, step, and scenario grounding rules from E2S2 (Gherkin scenario grounding) and E2S3 Approach C (equipment/scenario grounding, authoritative field protection) into reusable validation helpers.
  * **Tier 2 — LLM-based semantic intent evaluator:** implement a structured function-calling / tool-calling evaluation pipeline (following the E2S3 Approach C design pattern) where the LLM inspects generated ST and LD artifacts against the original requirements and emits structured review verdicts — business-logic coverage, missing-step alerts, and safety-hazard flags — while Python retains deterministic aggregation and pass/fail gate authority.
* **[E3S3T2] Add unit tests for parsers and generators** — planned.
  * Cover `req_parser.py`, `gherkin_gen.py`, `ast_gen_A/B/C.py`, `st_gen.py`, `ld_ir_gen.py`, and the `llm_direct` wrappers.
* **[E3S3T3] Add negative / failure-path test cases** — planned.
  * From the interim feedback: ambiguous or incomplete requirements, contradictory interlock conditions, and inputs missing key equipment information; applies across the E2S1-E2S4 stages.

---

## 🏃 In Progress

*(No tasks currently in progress)*

---

## 🔍 In Review

*(No tasks currently in review)*

---

## ✅ Done

### EPIC-1: Infrastructure & Environment Setup

#### E1S0: [Step 0] Environments and GitHub Initialization
* **[E1S0T1] Environments and GitHub Initialization**
  * Initialize the Git repository.
  * Create virtual environment setup instructions.
* **[E1S0T2] Create the initial repository documentation**
  * Draft the `README.md` with project overview, features, and workflow.
* **[E1S0T3] Add root ignore rules**
  * Configure `.gitignore` for virtual environments, Python caches, `.env` files, and local `data/`.
* **[E1S0T4] Initial Repository Scaffold**
  * Set up the base directory structure (`.agents/`, `.codex/`, `data/`, `notebooks/`, `src/`).

#### E1S1: [Phase 1] LM Studio deployment and models pulling
* **[E1S1T1]** Download and install LM Studio.
* **[E1S1T2]** Identify and pull appropriate local LLM models for testing natural language understanding.

#### E1S2: [Phase 2] Connection of the API from Windows to WSL
* **[E1S2T1] Configure WSL network settings to access the Windows host LM Studio API server**
* **[E1S2T2] Create a test script in `src/` to verify API connectivity from within WSL**

#### E1S3: [Phase 3] Deployment Weaviate vector DB (Docker in WSL)
* **[E1S3T1] Verify Docker installation in the WSL environment**
* **[E1S3T2] Create `docker-compose.yml` for Weaviate vector database**
* **[E1S3T3] Deploy Weaviate instance and verify its running status and API accessibility**

#### E1S4: [Phase 4] Build RAG pipeline and evaluation of frameworks
* **[E1S4T1] Build a prototype RAG pipeline connecting the LLM to the Weaviate DB using LlamaIndex**
* **[E1S4T2] Build a prototype RAG pipeline connecting the LLM to the Weaviate DB using LangChain**
* **[E1S4T3] Evaluate LangChain vs. LlamaIndex for this specific AutoPLC use case. Document the findings and finalize framework selection.**

### EPIC-2: Core Agent Pipeline

#### E2S1: Natural-language requirement ingestion
* **[E2S1T1] Develop the parser and input interface for control sequences, equipment behavior, and interlocks.**

#### E2S2: BDD/Gherkin generation and validation
* **[E2S2T1] Prompt engineering to convert requirements into Gherkin `Feature`, `Scenario`, `Given`, `When`, `Then` syntax**
  * Added `src/gherkin_schemas.py` (`GherkinScenario`/`GherkinFeature`) and `src/gherkin_gen.py`: per-item `with_structured_output(GherkinScenario)` calls per sequence step and interlock, deterministic non-LLM `.feature` renderer, failure isolation (skip with warning), and `source_step_id`/`source_interlock_condition` traceability stamping.
  * Hallucination prevention: deterministic `flag_unsupported_given()` strips ungrounded `given` entries; empty-field filters before rendering (fixed local-backend hallucinated placeholders).
  * Backend & rate limiting: migrated `api` to `gemini-3.1-flash-lite`; added `--call-delay` to prevent rate-limit exhaustion during multi-call runs.
  * Deferred: `local` backend occasionally hallucinates ungrounded `GherkinScenario.name`; planned fix extends grounding checks to the `name` field.
  * Verified end to end against both backends, producing valid `.feature` files for `signal_light_demo` and `sample_control`.

#### E2S3: AST/JSON intermediate representation
* **[E2S3T1]** Create the JSON schema for the AST that connects requirements, scenarios, and code blocks.
  * Approach A — LLM direct: single structured `with_structured_output(PLC_AST)` call over the combined requirement + Gherkin text (complete).
  * Approach B — deterministic gherkin-official construction: zero-LLM src/ast_gen_B.py using rule-based text matching (complete).
  * Approach C — RPC/function calling: LLM triggers structured builder calls for sequence/interlock semantic mappings; Python performs deterministic device construction, grounding checks, Pydantic validation, provenance stamping, and final assembly (complete; `src/ast_builders.py` and `src/ast_gen_C.py`).
  * Local fixes: LM Studio rejected object-style `tool_choice`, so local now uses `tool_choice="required"` while API keeps `tool_choice=expected_name`; local `sample_control` also paraphrased step 3's `action`, so Python now overwrites source-owned sequence/interlock fields before builder validation. Approach C local now runs after these compatibility and robustness fixes.
  * Deterministic `affected_devices`: all equipment mentioned in the interlock condition or forced action, preserving `equipment_list` order and avoiding partial-name matches such as `EV-101` matching `EV-1012`.

| Output group | Summary |
| --- | --- |
| A API | Strong semantics; full-AST LLM generation. |
| B | Deterministic and backend-free; can misidentify semantic roles (`signal_light_demo`: `start pushbutton` instead of `SL-301`). |
| C API | Best overall; semantic mapping plus deterministic Python validation/assembly (`sample_control` strongest output). |
| A local | Valid but model-dependent. |
| C local | Runs after fixes; structurally stable, but optional semantic fields may be weaker/null. |

  * Conclusion: C API is preferred, while local quality remains model-dependent.

#### E2S4: IEC 61131-3 ST and LD generation
* **[E2S4T1] Define ST/LD output contracts**
  * E2S4T1 — Define ST/LD output contracts: added lightweight Pydantic schemas for Structured Text blocks and Ladder Diagram intermediate networks. Generation logic deferred to later E2S4 tasks.
* **[E2S4T2] Implement deterministic Structured Text generator**
  * E2S4T2 — Implement ST generator: added deterministic AST-to-ST renderer with sanitized variable names, BOOL declarations, sequence IF blocks, safety interlock override blocks, and traceability comments. Verified against signal_light_demo and sample_control AST outputs.
  * Known limitation: current ST output is a deterministic MVP draft. It does not yet model signal-light colour states, sequence state, timers, or analogue thresholds.
  * Deferred: pytest structural checks, MATIEC syntax checking, and OpenPLC Editor / Runtime validation are planned under EPIC-3 E3S1 Output artifact verification.
* **[E2S4T3] Implement LD IR generator**
  * E2S4T3 — Implement LD IR generator: added `src/ld_ir_gen.py`, a deterministic AST-to-LD-IR renderer with sanitized variable names, controlled action-to-coil mapping (open/start/on/energize/activate/run map to set coils; close/stop/off/de-energize/deactivate/reset map to reset coils; ambiguous or negated actions fall back to normal coils), sequence networks and safety interlock networks (one coil per network), contacts, coils, priority, traceability links, and unsupported-condition notes; writes LD IR JSON to `data/plc/ld/*.json`. Verified 2 networks for `signal_light_demo` and 8 networks for `sample_control`.
  * Known limitation: current LD IR is a structural MVP, not graphical LD or PLCopen XML. It represents only simple positive AND conditions as serial normally-open contacts and does not yet support graphical layout, parallel branches, timers, analogue thresholds, runtime validation, or vendor-specific PLCopen XML export.
* **[E2S4T4] Add LLM Direct Structured Text generator**
  * E2S4T4 — Add LLM Direct ST generator: added `src/st_gen_llm_direct.py`, a separate `llm_direct` AST-to-ST renderer with local/API backend support, backend-specific output suffixes, PLC_AST input validation, Markdown-fence cleanup, and light ST structure checks. Generated API and local comparison outputs for signal_light_demo and sample_control.
  * Comparison: deterministic Python ST remains the most reproducible baseline; API LLM Direct is the cleaner MVP LLM draft and follows sequence-before-safety ordering more closely; local LLM Direct is slower and more speculative, with higher syntax/semantic risk.
  * Verification recorded: `py_compile`, both API runs, both local runs, and `git diff --check` completed during implementation; `git diff --check` reported line-ending warnings only.
  * Known limitation: generated ST remains MVP draft output. MATIEC syntax checking, OpenPLC validation, runtime simulation, and vendor-specific validation remain deferred to EPIC-3 (E3S1 Output artifact verification) or later.
* **[E2S4T5] Add LLM Direct LD IR generator**
  * E2S4T5 — Add LLM Direct LD IR generator: added `src/ld_ir_gen_llm_direct.py`, a separate `llm_direct` AST-to-LD-IR JSON renderer with local/API backend support, backend-specific output suffixes, PLC_AST input validation, JSON cleanup/parsing, LDProgram schema validation, and light LD structure checks.
  * Prompt refinement: sequence networks must appear before interlock networks despite higher logical safety priority; multi-target interlocks must split into one network per target coil; contact/coil variables must be IEC-compatible; unsupported timer/analogue/sequence-state logic must remain notes plus valid placeholder variables.
  * Retry handling: API gets one validation-feedback retry; local gets two validation-feedback retries and uses `json_schema` response format to keep larger LD IR JSON structurally valid.
  * Troubleshooting result: local Gemma E4B initially failed on `sample_control` due to ordering, variable naming, and weak interlock coil issues; prompt hardening plus retry feedback now saves an 8-network valid JSON artifact.
  * Verification recorded: `py_compile`, both API runs, both local runs, existing LD IR unit tests, and `git diff --check` completed. API and local backends generated `signal_light_demo` and `sample_control` LD Direct outputs.
  * Known limitation: generated LD IR remains MVP draft output. API output is useful for comparison, while local output remains more model-dependent; graphical LD, PLCopen XML, MATIEC/OpenPLC validation, runtime simulation, and vendor-specific validation remain deferred to EPIC-3 (E3S1 Output artifact verification) or later.
* **[E2S4T6] Add Hybrid Structured Text generator**
  * E2S4T6 — Add Hybrid ST generator: added `src/st_hybrid_schemas.py` (structured code-intent contracts) and `src/st_gen_hybrid.py`. Per-item LLM tool calls (`suggest_sequence_intent` / `suggest_interlock_intent`) return structured code intent for complex logic; Python validates grounding against the AST device list and renders final ST deterministically: timers as TON function blocks (`TON_<step>_<n>` declared in VAR), analogue thresholds as REAL comparisons (measured device declared `REAL`), colour states and sequence-state notes as review comments.
  * Backend-arg normalization: flattened tool args (e.g. `'SL-301: green'`, `'tank level sensor reaches 80'`, bare `'5'`) are parsed deterministically by Python before Pydantic validation, following the E2S3 Approach C principle that Python owns structure and grounding.
  * Local backend hardening (Gemma 4 E2B): E2B returns backend-flattened tool args (compact keyed mappings like `{'SL-301': 'green'}`), sometimes drops comparison operators on analogue thresholds, and can emit condition text as colour-state entries. Parser normalization now accepts compact dict mappings; the sequence prompt requires comparison operators; unparseable colour-state entries degrade to review notes while grounding failures still abort.
  * Verification: `py_compile`; API runs on both example AST files — `signal_light_demo_api_AST_C_st_hybrid_api.st` (3 variables, 2 blocks; colour intents green/red captured) and `sample_control_api_AST_C_st_hybrid_api.st` (6 variables, 6 blocks; `tank_level_sensor : REAL`, `TON_4_1 : TON` with `PT := T#5s`) — with structural checks; `tests/test_st_hybrid_gen.py` (17 tests) and existing LD tests pass; `git diff --check` clean. Local backend (Gemma 4 E2B) verified on both example AST files after hardening.
* **[E2S4T7] Add Hybrid LD IR generator**
  * E2S4T7 — Add Hybrid LD IR generator: added `src/ld_ir_gen_hybrid.py`, reusing the E2S4T6 intent pipeline (`_collect_intents`, grounding, backend-arg normalization) and the deterministic LD baseline logic from `src/ld_ir_gen.py`. Python renders analogue intents as `LDContact` entries with `operator`/`threshold`, timer intents as `LDNetwork.timer_duration_seconds`/`timer_description` metadata, and colour/state intents as review notes, replacing the baseline `TODO_UNSUPPORTED_CONDITION` placeholders for timer and analogue conditions; multi-target interlocks are deterministically split into one network per target coil, and sequence-before-interlock ordering is enforced.
  * Contract extension: `src/plc_code_schemas.py` `LDContact` gained optional `operator`/`threshold`; `LDNetwork` gained optional `timer_duration_seconds`/`timer_description`; all default `None`, so deterministic and LLM-direct outputs are unchanged.
  * Verification: `py_compile`; API runs on both example AST files — `signal_light_demo_api_AST_C_ld_hybrid_api.json` (2 networks; colour notes) and `sample_control_api_AST_C_ld_hybrid_api.json` (8 networks; SEQ-3 comparison contact `>= 80.0`, SEQ-4 timer `5s`, interlocks split per target coil) — with `validate_ld_structure` passing; `tests/test_ld_ir_gen_hybrid.py` (5 tests) and the full suite (30 tests) pass; `git diff --check` clean. Local backend (Gemma 4 E2B) verified on both example AST files: IR structure identical to the API backend across all 10 networks; the E2S4T6 hardening applied unchanged (LD reuses `_collect_intents`) and fired 6 times, degrading unparseable colour-state entries from ILK-1/ILK-2 to review notes instead of aborting.
