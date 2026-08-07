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
* **[E2S4T4] Output verification** — planned.
  * Add pytest tests for generated `.st` file structure.
  * Check required ST sections, variable declarations, traceability comments, and interlock override placement.
  * Investigate MATIEC for IEC 61131-3 ST syntax / compile checking.
  * Investigate OpenPLC Editor / Runtime for compiling and validating generated PLC logic.
  * Keep runtime simulation and vendor-specific Siemens TIA Portal / PLCSIM validation as later-stage work.
* **[E2S4T5] Add LLM Direct Structured Text generator** — complete.
  * Added `src/st_gen_llm_direct.py` as a separate `llm_direct` approach, not a replacement for deterministic `src/st_gen.py`.
  * Supports `--backend api` and `--backend local`, writing `_st_llm_direct_api.st` and `_st_llm_direct_local.st` outputs for comparison.
  * Performs PLC_AST input validation, Markdown-fence cleanup, and light ST structure checks before saving generated text.
  * Current comparison: deterministic Python ST is most stable and conservative; API LLM Direct output is cleaner and more conservative than local; local LLM Direct output is useful for cross-backend comparison but slower, more speculative, and less stable.
* **[E2S4T6] Add LLM Direct LD IR generator** — complete.
  * Added `src/ld_ir_gen_llm_direct.py` as a separate `llm_direct` approach, not a replacement for deterministic `src/ld_ir_gen.py`.
  * Supports `--backend api` and `--backend local`, writing `_ld_llm_direct_api.json` and `_ld_llm_direct_local.json` outputs where generation completes.
  * Performs PLC_AST input validation, JSON cleanup/parsing, LDProgram schema validation, and light LD structure checks before saving generated JSON.
  * Prompt now explicitly distinguishes sequence-first array ordering from safety/interlock logical priority, requires multi-target interlock splitting, enforces IEC-compatible variable naming, and keeps unsupported timer/analogue/sequence-state logic as TODO notes.
  * Added validation-feedback retry handling for JSON parsing, LDProgram schema, or light-validation failures; local uses schema-guided JSON output.
  * Troubleshooting note: local Gemma E4B initially failed on the larger `sample_control` case due to ordering, variable naming, and weak interlock coil issues; prompt hardening plus retry feedback now saves an 8-network valid JSON artifact.
  * API and local backends generated both example LD Direct outputs, including `sample_control_api_AST_C_ld_llm_direct_local.json`.
* Graphical Ladder Diagram rendering, richer ST/LD coverage, PLCopen XML
  mapping, timers, and vendor-specific export remain future tasks.

### EPIC-3: Validation & Export

#### E3S1: PLCopen XML export
* **[E3S1T1]** Create export module to map the generated AST to interoperable PLCopen XML format.

#### E3S2: Automated tests and validation workflows
* **[E3S2T1]** Implement deterministic validation around LLM-generated content.
* **[E3S2T2]** Add unit tests for parsers and generators.

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
  * Deferred: pytest structural checks, MATIEC syntax checking, and OpenPLC Editor / Runtime validation are planned under E2S4T4 Output Verification.
* **[E2S4T3] Implement LD IR generator**
  * E2S4T3 — Implement LD IR generator: added deterministic AST-to-LD-IR renderer with sanitized variable names, controlled action-to-coil mapping, sequence networks, safety interlock networks, contacts, coils, priority, traceability links, and unsupported-condition notes. Verified against signal_light_demo and sample_control AST outputs.
  * Known limitation: current LD IR is a structural MVP, not graphical LD or PLCopen XML. It represents only simple positive AND conditions as serial normally-open contacts and does not yet support graphical layout, parallel branches, timers, analogue thresholds, runtime validation, or vendor-specific PLCopen XML export.
* **[E2S4T5] Add LLM Direct Structured Text generator**
  * E2S4T5 — Add LLM Direct ST generator: added `src/st_gen_llm_direct.py`, a separate `llm_direct` AST-to-ST renderer with local/API backend support, backend-specific output suffixes, PLC_AST input validation, Markdown-fence cleanup, and light ST structure checks. Generated API and local comparison outputs for signal_light_demo and sample_control.
  * Comparison: deterministic Python ST remains the most reproducible baseline; API LLM Direct is the cleaner MVP LLM draft and follows sequence-before-safety ordering more closely; local LLM Direct is slower and more speculative, with higher syntax/semantic risk.
  * Verification recorded: `py_compile`, both API runs, both local runs, and `git diff --check` completed during implementation; `git diff --check` reported line-ending warnings only.
  * Known limitation: generated ST remains MVP draft output. MATIEC syntax checking, OpenPLC validation, runtime simulation, and vendor-specific validation remain deferred to E2S4T4 or later.
* **[E2S4T6] Add LLM Direct LD IR generator**
  * E2S4T6 — Add LLM Direct LD IR generator: added `src/ld_ir_gen_llm_direct.py`, a separate `llm_direct` AST-to-LD-IR JSON renderer with local/API backend support, backend-specific output suffixes, PLC_AST input validation, JSON cleanup/parsing, LDProgram schema validation, and light LD structure checks.
  * Prompt refinement: sequence networks must appear before interlock networks despite higher logical safety priority; multi-target interlocks must split into one network per target coil; contact/coil variables must be IEC-compatible; unsupported timer/analogue/sequence-state logic must remain notes plus valid placeholder variables.
  * Retry handling: API gets one validation-feedback retry; local gets two validation-feedback retries and uses `json_schema` response format to keep larger LD IR JSON structurally valid.
  * Troubleshooting result: local Gemma E4B initially failed on `sample_control` due to ordering, variable naming, and weak interlock coil issues; prompt hardening plus retry feedback now saves an 8-network valid JSON artifact.
  * Verification recorded: `py_compile`, both API runs, both local runs, existing LD IR unit tests, and `git diff --check` completed. API and local backends generated `signal_light_demo` and `sample_control` LD Direct outputs.
  * Known limitation: generated LD IR remains MVP draft output. API output is useful for comparison, while local output remains more model-dependent; graphical LD, PLCopen XML, MATIEC/OpenPLC validation, runtime simulation, and vendor-specific validation remain deferred to E2S4T4 or later.
