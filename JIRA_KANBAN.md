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
  * Approach C — RPC/function calling: LLM triggers structured AST builder functions rather than emitting free-form JSON (planned).

#### E2S4: IEC 61131-3 ST and LD generation
* **[E2S4T1]** Develop generation logic targeting Structured Text and Ladder Diagram from the AST.

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
  * Approach C — RPC/function calling: LLM triggers structured AST builder functions rather than emitting free-form JSON (planned).

