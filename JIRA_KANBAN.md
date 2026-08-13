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
* **[E1S2T1]** Configure WSL network settings to access the Windows host LM Studio API server.
* **[E1S2T2]** Create a test script in `src/` to verify API connectivity from within WSL.

#### E1S3: [Phase 3] Deployment Weaviate vector DB (Docker in WSL)
* **[E1S3T1]** Verify Docker installation in the WSL environment.
* **[E1S3T2]** Create `docker-compose.yml` for Weaviate vector database.
* **[E1S3T3]** Deploy Weaviate instance and verify its running status and API accessibility.

#### E1S4: [Phase 4] Build RAG pipeline and evaluation of frameworks
* **[E1S4T1]** Build a prototype RAG pipeline connecting the LLM to the Weaviate DB using LlamaIndex
* **[E1S4T2]** Build a prototype RAG pipeline connecting the LLM to the Weaviate DB using LangChain
* **[E1S4T3]** Evaluate LangChain vs. LlamaIndex for this specific AutoPLC use case. Document the findings and finalize framework selection.

### EPIC-2: Core Agent Pipeline

#### E2S1: Natural-language requirement ingestion
* **[E2S1T1]** Develop the parser and input interface for control sequences, equipment behavior, and interlocks.

#### E2S2: BDD/Gherkin generation and validation
* **[E2S2T1]** Prompt engineering to convert requirements into Gherkin `Feature`, `Scenario`, `Given`, `When`, `Then` syntax.

#### E2S3: AST/JSON intermediate representation
* **[E2S3T1]** Create the JSON schema for the AST that connects requirements, scenarios, and code blocks.
  * Delivered in three commits, one per candidate approach:
  * Approach A — LLM direct: single structured `with_structured_output(PLC_AST)` call over the combined requirement + Gherkin text (complete).
  * Approach B — deterministic gherkin-official construction: zero-LLM src/ast_gen_B.py using rule-based text matching (complete).
  * Approach C — RPC/function calling: LLM triggers structured AST builder functions rather than emitting free-form JSON (complete; `src/ast_builders.py` and `src/ast_gen_C.py`).

#### E2S4: IEC 61131-3 ST and LD generation
* Full E2S4 task plan:
* **[E2S4T1] Define ST/LD output contracts** — complete.
  * Added lightweight Pydantic schemas for Structured Text blocks and Ladder Diagram intermediate networks.
* **[E2S4T2] Implement deterministic Structured Text generator** — complete.
  * Added deterministic AST-to-ST renderer with sanitized variable names, BOOL declarations, sequence IF blocks, safety interlock override blocks, and traceability comments.
* **[E2S4T3] Implement LD IR generator** — complete.
  * Added deterministic AST-to-LD-IR rendering in `src/ld_ir_gen.py`.
  * Writes LD intermediate-representation JSON to `data/plc/ld/*.json`.
  * Generates sequence networks and safety interlock networks with one coil per network.
  * Includes contacts, coils, priority, traceability fields, and review notes using the LD output contracts.
  * Supports basic controlled action-to-coil mapping: open/start/on/energize/activate/run to set coils, and close/stop/off/de-energize/deactivate/reset to reset coils; ambiguous or negated action text falls back to normal coils.
  * Represents only simple positive AND conditions as serial normally-open contacts; OR, negation, timer/duration, and analogue/numeric comparison conditions are marked with unsupported notes rather than silently approximated.
  * Verified both example LD IR files were generated successfully: 2 networks for `signal_light_demo_api_AST_C_ld.json` and 8 networks for `sample_control_api_AST_C_ld.json`.
* **[E2S4T4] Add LLM Direct Structured Text generator** — complete.
  * Added `src/st_gen_llm_direct.py` as a separate `llm_direct` approach, not a replacement for deterministic `src/st_gen.py`.
  * Supports `--backend api` and `--backend local`, writing `_st_llm_direct_api.st` and `_st_llm_direct_local.st` outputs for comparison.
  * Performs PLC_AST input validation, Markdown-fence cleanup, and light ST structure checks before saving generated text.
  * Current comparison: deterministic Python ST is most stable and conservative; API LLM Direct output is cleaner and more conservative than local; local LLM Direct output is useful for cross-backend comparison but slower, more speculative, and less stable.
* **[E2S4T5] Add LLM Direct LD IR generator** — complete.
  * Added `src/ld_ir_gen_llm_direct.py` as a separate `llm_direct` approach, not a replacement for deterministic `src/ld_ir_gen.py`.
  * Supports `--backend api` and `--backend local`, writing `_ld_llm_direct_api.json` and `_ld_llm_direct_local.json` outputs where generation completes.
  * Performs PLC_AST input validation, JSON cleanup/parsing, LDProgram schema validation, and light LD structure checks before saving generated JSON.
  * Prompt now explicitly distinguishes sequence-first array ordering from safety/interlock logical priority, requires multi-target interlock splitting, enforces IEC-compatible variable naming, and keeps unsupported timer/analogue/sequence-state logic as TODO notes.
  * Added validation-feedback retry handling for JSON parsing, LDProgram schema, or light-validation failures; local uses schema-guided JSON output.
  * Troubleshooting note: local Gemma E4B initially failed on the larger `sample_control` case due to ordering, variable naming, and weak interlock coil issues; prompt hardening plus retry feedback now saves an 8-network valid JSON artifact.
  * API and local backends generated both example LD Direct outputs, including `sample_control_api_AST_C_ld_llm_direct_local.json`.
* **[E2S4T6] Add Hybrid Structured Text generator** — complete.
  * Combines the deterministic baseline and LLM-direct approaches: the LLM converts complex actions (timers, analogue thresholds, sequence state, colour states) into structured code intent, and Python renders the final ST code deterministically.
  * Follows the E2S3 Approach C principle: the LLM provides semantic suggestions; Python owns rendering, validation, and traceability.
  * Keeps backend compatibility (`--backend local` / `--backend api`).
  * Added `src/st_hybrid_schemas.py` (TimerIntent/ColourStateIntent/AnalogueIntent/SequenceCodeIntent/InterlockCodeIntent) and `src/st_gen_hybrid.py` with grounding checks, backend-arg normalization, TON rendering for timers, REAL comparisons for analogue conditions, and colour-state review comments.
  * Verification: `py_compile`; `api` backend runs on both `signal_light_demo` and `sample_control` AST files (structure valid: PROGRAM/VAR/END_VAR/END_PROGRAM present, balanced IF/END_IF, no Markdown fences); `tests/test_st_hybrid_gen.py` (11 deterministic tests) and existing LD tests pass; `git diff --check` clean. `local` backend inference pending manual verification.
* **[E2S4T7] Add Hybrid LD IR generator** — complete.
  * Same hybrid pattern as E2S4T6 applied to Ladder Diagram IR: the LLM supplies structured code intent for unsupported logic (timers, analogue/numeric comparisons, parallel branches), and Python renders validated LD IR JSON.
  * Added `src/ld_ir_gen_hybrid.py` reusing the E2S4T6 intent pipeline (`_collect_intents` with grounding checks and backend-arg normalization); extended `src/plc_code_schemas.py` with optional `operator`/`threshold` on `LDContact` and `timer_duration_seconds`/`timer_description` on `LDNetwork` (backward compatible).
  * Python renders analogue intents as real comparison contacts (`tank_level_sensor >= 80`), timer intents as network-level timer metadata, and colour/state intents as review notes; multi-target interlocks stay split into one network per target coil; sequence-before-interlock ordering and `validate_ld_structure` are enforced deterministically.
  * Verification: `py_compile`; `api` backend runs on both `signal_light_demo` (2 networks; colour notes green/red) and `sample_control` (8 networks; SEQ-3 comparison contact `>= 80.0`, SEQ-4 timer metadata `5s`) with structural validation passing; `tests/test_ld_ir_gen_hybrid.py` (5 tests) and the full suite (24 tests) pass; `git diff --check` clean. `local` backend inference pending manual verification.
* Graphical Ladder Diagram rendering, richer ST/LD coverage (enumerated
  colour states, multi-step timers), PLCopen XML mapping, and vendor-specific
  export remain future tasks.

### EPIC-3: Validation & Export

#### E3S1: Output artifact verification
* **[E3S1T1] Add pytest structural checks for generated ST artifacts** — planned.
  * Check required ST sections, variable declarations, traceability comments, and interlock override placement in generated `.st` files.
* **[E3S1T2] Add pytest structural checks for generated LD IR artifacts** — planned.
  * Check network structure, contact/coil types, unique network IDs, traceability, priority, and sequence-before-interlock ordering in generated LD IR JSON.
* **[E3S1T3] Investigate MATIEC for IEC 61131-3 ST syntax / compile checking** — planned.
* **[E3S1T4] Investigate OpenPLC Editor / Runtime for compiling and validating generated PLC logic** — planned.
* **[E3S1T5] Extend the verification suite to hybrid generator outputs** — planned.
  * Once the E2S4T6/E2S4T7 hybrid generators land, run the same structural and external-tool checks on their outputs.
* **[E3S1T6] Evaluate runtime simulation and vendor-specific TIA Portal / PLCSIM validation** — planned (later-stage work).

#### E3S2: PLCopen XML export
* **[E3S2T1] Create export module mapping PLC_AST to interoperable PLCopen XML** — planned.
* **[E3S2T2] Validate generated PLCopen XML** — planned.
  * Check XML schema conformance, required element completeness, traceability preservation, and readability by standard PLC engineering tools.

#### E3S3: Component tests and validation framework
* **[E3S3T1] Consolidate deterministic grounding-check patterns into a reusable validation framework** — planned.
  * Reuse and extend the grounding checks from E2S2 (Gherkin scenario grounding) and E2S3 Approach C (equipment/scenario grounding, authoritative field protection) as shared validation helpers.
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
* **[E1S0T2] Create the initial repository documentation**
* **[E1S0T3] Add root ignore rules**
* **[E1S0T4] Initial Repository Scaffold**

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

#### E2S3: AST/JSON intermediate representation
* **[E2S3T1]** Create the JSON schema for the AST that connects requirements, scenarios, and code blocks.
  * Approach A — LLM direct: single structured `with_structured_output(PLC_AST)` call over the combined requirement + Gherkin text (complete).
  * Approach B — deterministic gherkin-official construction: zero-LLM src/ast_gen_B.py using rule-based text matching (complete).
  * Approach C — RPC/function calling: LLM triggers structured builder calls for sequence/interlock semantic mappings; Python performs deterministic device construction, grounding checks, Pydantic validation, provenance stamping, and final assembly (complete).
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
  * E2S4T3 — Implement LD IR generator: added deterministic AST-to-LD-IR renderer with sanitized variable names, controlled action-to-coil mapping, sequence networks, safety interlock networks, contacts, coils, priority, traceability links, and unsupported-condition notes. Verified against signal_light_demo and sample_control AST outputs.
  * Known limitation: current LD IR is a structural MVP, not graphical LD or PLCopen XML. It represents only simple positive AND conditions as serial normally-open contacts and does not yet support graphical layout, parallel branches, timers, analogue thresholds, runtime validation, or vendor-specific PLCopen XML export.
* **[E2S4T4] Add LLM Direct Structured Text generator**
  * E2S4T4 — Add LLM Direct ST generator: added `src/st_gen_llm_direct.py`, a separate `llm_direct` AST-to-ST renderer with local/API backend support, backend-specific output suffixes, PLC_AST input validation, Markdown-fence cleanup, and light ST structure checks. Generated API and local comparison outputs for signal_light_demo and sample_control.
  * Comparison: deterministic Python ST remains the most reproducible baseline; API LLM Direct is the cleaner MVP LLM draft and follows sequence-before-safety ordering more closely; local LLM Direct is slower and more speculative, with higher syntax/semantic risk.
  * Verification recorded: `py_compile`, both API runs, both local runs, and `git diff --check` completed during implementation; `git diff --check` reported line-ending warnings only.
  * Known limitation: generated ST remains MVP draft output. MATIEC syntax checking, OpenPLC validation, runtime simulation, and vendor-specific validation remain deferred to EPIC-3 (E3S1 Output artifact verification) or later.
* **[E2S4T5] Add LLM Direct LD IR generator**
  * E2S4T5 — Add LLM Direct LD IR generator: added `src/ld_ir_gen_llm_direct.py`, a separate `llm_direct` AST-to-LD-IR JSON renderer with local/API backend support, backend-specific output suffixes, PLC_AST input validation, JSON cleanup/parsing, LDProgram schema validation, and light LD structure checks.
* **[E2S4T6] Add Hybrid Structured Text generator**
  * E2S4T6 — Add Hybrid ST generator: added `src/st_hybrid_schemas.py` (structured code-intent contracts) and `src/st_gen_hybrid.py`. Per-item LLM tool calls (`suggest_sequence_intent` / `suggest_interlock_intent`) return structured code intent for complex logic; Python validates grounding against the AST device list and renders final ST deterministically: timers as TON function blocks (`TON_<step>_<n>` declared in VAR), analogue thresholds as REAL comparisons (measured device declared `REAL`), colour states and sequence-state notes as review comments.
  * Backend-arg normalization: flattened tool args (e.g. `'SL-301: green'`, `'tank level sensor reaches 80'`, bare `'5'`) are parsed deterministically by Python before Pydantic validation, following the E2S3 Approach C principle that Python owns structure and grounding.
  * Local backend hardening (Gemma 4 E2B): E2B returns backend-flattened tool args (compact keyed mappings like `{'SL-301': 'green'}`), sometimes drops comparison operators on analogue thresholds, and can emit condition text as colour-state entries. Parser normalization now accepts compact dict mappings; the sequence prompt requires comparison operators; unparseable colour-state entries degrade to review notes while grounding failures still abort. Verified `--backend local` on both example AST files.
  * Verification: `py_compile`; API runs on both example AST files — `signal_light_demo_api_AST_C_st_hybrid_api.st` (3 variables, 2 blocks; colour intents green/red captured) and `sample_control_api_AST_C_st_hybrid_api.st` (6 variables, 6 blocks; `tank_level_sensor : REAL`, `TON_4_1 : TON` with `PT := T#5s`) — with structural checks; `tests/test_st_hybrid_gen.py` (11 tests) and existing LD tests pass; `git diff --check` clean. Local backend (Gemma 4 E2B) verified on both example AST files after hardening.
* **[E2S4T7] Add Hybrid LD IR generator**
  * E2S4T7 — Add Hybrid LD IR generator: added `src/ld_ir_gen_hybrid.py`, reusing the E2S4T6 intent pipeline (`_collect_intents`, grounding, backend-arg normalization) and the deterministic LD baseline logic from `src/ld_ir_gen.py`. Python renders analogue intents as `LDContact` entries with `operator`/`threshold`, timer intents as `LDNetwork.timer_duration_seconds`/`timer_description` metadata, and colour/state intents as review notes, replacing the baseline `TODO_UNSUPPORTED_CONDITION` placeholders for timer and analogue conditions.
  * Contract extension: `src/plc_code_schemas.py` `LDContact` gained optional `operator`/`threshold`; `LDNetwork` gained optional `timer_duration_seconds`/`timer_description`; all default `None`, so deterministic and LLM-direct outputs are unchanged.
  * Verification: `py_compile`; API runs on both example AST files — `signal_light_demo_api_AST_C_ld_hybrid_api.json` (2 networks; colour notes) and `sample_control_api_AST_C_ld_hybrid_api.json` (8 networks; SEQ-3 comparison contact `>= 80.0`, SEQ-4 timer `5s`, interlocks split per target coil) — with `validate_ld_structure` passing; `tests/test_ld_ir_gen_hybrid.py` (5 tests) and the full suite (24 tests) pass; `git diff --check` clean. Local backend inference skipped for manual verification.
  * Prompt refinement: sequence networks must appear before interlock networks despite higher logical safety priority; multi-target interlocks must split into one network per target coil; contact/coil variables must be IEC-compatible; unsupported timer/analogue/sequence-state logic must remain notes plus valid placeholder variables.
  * Retry handling: API gets one validation-feedback retry; local gets two validation-feedback retries and uses `json_schema` response format to keep larger LD IR JSON structurally valid.
  * Troubleshooting result: local Gemma E4B initially failed on `sample_control` due to ordering, variable naming, and weak interlock coil issues; prompt hardening plus retry feedback now saves an 8-network valid JSON artifact.
  * Verification recorded: `py_compile`, both API runs, both local runs, existing LD IR unit tests, and `git diff --check` completed. API and local backends generated `signal_light_demo` and `sample_control` LD Direct outputs.
  * Known limitation: generated LD IR remains MVP draft output. API output is useful for comparison, while local output remains more model-dependent; graphical LD, PLCopen XML, MATIEC/OpenPLC validation, runtime simulation, and vendor-specific validation remain deferred to EPIC-3 (E3S1 Output artifact verification) or later.
