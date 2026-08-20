# AutoPLC Agent

AutoPLC Agent is a GenAI agent platform intended to bridge Information
Technology (IT) and Operational Technology (OT) workflows. The project aims to
turn natural-language control requirements into structured, reviewable
artifacts and ultimately generate IEC 61131-3 PLC programs.

> **Project status:** `E2S1 - E2S4` of the core pipeline are complete:
> natural-language requirements are parsed into `SystemRequirement` JSON
> (`src/req_parser.py`), converted to Gherkin `.feature` files
> (`src/gherkin_gen.py`), assembled into validated `PLC_AST` JSON through three
> approaches A/B/C (`src/ast_gen_A/B/C.py`), and rendered to IEC 61131-3
> Structured Text and Ladder Diagram IR drafts by three generation strategies
> — deterministic (`st_gen.py`, `ld_ir_gen.py`), LLM Direct
> (`st_gen_llm_direct.py`, `ld_ir_gen_llm_direct.py`), and hybrid
> (`st_gen_hybrid.py`, `ld_ir_gen_hybrid.py`), the last two verified on both
> the `api` and `local` (Gemma 4 E2B) backends. Two parallel RAG prototypes over
> a Siemens manual (LlamaIndex and LangChain) remain in place. Remaining work is
> tracked under `EPIC-3` in `JIRA_KANBAN.md`: output-artifact verification,
> PLCopen XML export, and component-test consolidation.

## Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Workflow and Architecture](#-workflow-and-architecture)
- [Getting Started](#-getting-started)
- [Project Structure](#-project-structure)
- [Technology Stack](#-technology-stack)
- [Development Principles](#-development-principles)
- [Task Completion Status](#-task-completion-status)
- [Contributors](#-contributors)
- [Branch History](#-branch-history)

## 🎯 Overview

Industrial automation projects often start with requirements written in
natural language and end with vendor tools, PLC code, and machine-specific
configuration. AutoPLC Agent is designed to make the steps between those points
more structured, traceable, and suitable for human review.

The implemented pipeline uses large language models (LLMs) at the parsing,
Gherkin, AST, and code-drafting stages, with deterministic Python validation
and rendering at every step:

1. **Parse** natural-language automation requirements into a validated
   `SystemRequirement` JSON (E2S1, `src/req_parser.py`).
2. **Express** expected behavior as BDD scenarios in Gherkin `.feature` syntax
   (E2S2, `src/gherkin_gen.py`).
3. **Assemble** validated scenarios into a structured `PLC_AST` JSON
   intermediate representation (E2S3, three approaches in
   `src/ast_gen_A/B/C.py`).
4. **Generate** standard IEC 61131-3 drafts — Structured Text (ST) and Ladder
   Diagram (LD) IR — via deterministic, LLM Direct, and hybrid generators
   (E2S4).
5. **Export** interoperable PLCopen XML for downstream engineering tools
   (planned, EPIC-3 E3S2).

The platform is intended to assist engineers, not replace safety review,
simulation, commissioning, or compliance processes. Generated control logic
must be validated before use on physical equipment.

## ✨ Features

The following capabilities define the planned product scope:

- **Natural-language requirements intake** for describing control sequences,
  equipment behavior, alarms, interlocks, and operating modes.

- **BDD requirement generation** using Gherkin `Feature`, `Scenario`,
  `Given`, `When`, and `Then` constructs.

- **Traceable intermediate representation** using AST/JSON to connect source
  requirements, scenarios, code blocks, variables, and generated outputs.

- **IEC 61131-3 code generation** targeting Structured Text and Ladder Diagram.

- **Natural-language requirement parser** (`src/req_parser.py`) that extracts
  equipment, control sequences, and safety interlocks from a free-form `.txt`
  requirement into a validated `SystemRequirement` Pydantic schema, using
  LangChain `with_structured_output` against either a local LM Studio
  (`--backend local`) or a Gemini cloud (`--backend api`) backend, writing the
  result to a backend-tagged `data/parsed/<name>_parsed_<backend>.json` file.

- **Gherkin generation pipeline** (`src/gherkin_gen.py`) that converts a parsed
  `SystemRequirement` JSON file into a standard Gherkin `.feature` file. It maps
  each `ControlSequence` step and each `Interlock` into its own
  `GherkinScenario` via a per-item `with_structured_output` call (defined in
  `src/gherkin_schemas.py`), isolating failures so one bad item is skipped with
  a warning rather than aborting the file. A deterministic, non-LLM renderer
  then formats the assembled `GherkinFeature` into syntactically correct
  `Given/When/Then` output, written to a backend-tagged
  `data/gherkin/<name>_<backend>.feature` file.

- **AST generation pipeline — Approach A (LLM direct)** (`src/ast_gen_A.py`)
  that reads a `SystemRequirement` JSON file (E2S1 output) and a Gherkin
  `.feature` file (E2S2 output) and produces a `PLC_AST` JSON file under
  `data/ast/` via a single LLM ``with_structured_output`` call. It reuses the
  `--backend {local,api}` flag from `req_parser.py` and writes to a
  backend-tagged `data/ast/<stem>_<backend>.json` file.

- **AST generation pipeline — Approach B (deterministic)** (`src/ast_gen_B.py`)
  that builds the same `PLC_AST` structure using the ``gherkin-official``
  library to parse the `.feature` file and pure-Python text matching to
  cross-reference Gherkin scenarios with requirement steps — **zero LLM
  involvement**. It accepts two positional arguments (`req_file`,
  `feature_file`) with no `--backend` flag and writes to
  `data/ast/<stem>_AST_B.json`.

- **AST generation pipeline — Approach C (RPC/function calling)**
  (`src/ast_gen_C.py`, with builders in `src/ast_builders.py`) that binds the
  LLM to per-item builder tools. Device nodes, verbatim source fields, IDs,
  grounding checks, Pydantic validation, and final assembly remain deterministic
  Python operations. Run it with `python -m src.ast_gen_C <parsed.json>
  <feature.feature> --backend {local,api}`; output is
  `data/ast/<stem>_<backend>_AST_C.json`.

- **ST/LD output contracts** (`src/plc_code_schemas.py`) defining the
  `STProgram`/`STBlock` and `LDProgram`/`LDNetwork`/`LDContact`/`LDCoil`
  structures consumed by the ST and LD generators.

- **Deterministic Structured Text draft generation** (`src/st_gen.py`) from
  validated `PLC_AST` JSON, producing BOOL declarations, sequence `IF` blocks,
  safety interlock override blocks, and traceability comments under
  `data/plc/st/*.st`.

- **LLM Direct Structured Text draft generation** (`src/st_gen_llm_direct.py`)
  from validated `PLC_AST` JSON, producing backend-specific comparison outputs
  with `_st_llm_direct_api.st` and `_st_llm_direct_local.st` suffixes.

- **Hybrid Structured Text draft generation** (`src/st_gen_hybrid.py`) from
  validated `PLC_AST` JSON: the LLM returns structured code intent for complex
  logic (timers, analogue thresholds, colour states) through function calls and
  Python renders the final Structured Text deterministically, including TON
  function-block calls and REAL comparisons, writing `_st_hybrid_api.st` and
  `_st_hybrid_local.st` outputs.

- **Deterministic Ladder Diagram IR draft generation** (`src/ld_ir_gen.py`)
  from validated `PLC_AST` JSON, producing network-based LD IR JSON (contacts,
  coils, priority, traceability links) under `data/plc/ld/*.json`.

- **LLM Direct Ladder Diagram IR draft generation**
  (`src/ld_ir_gen_llm_direct.py`) from validated `PLC_AST` JSON, producing
  backend-specific comparison outputs with `_ld_llm_direct_api.json` and
  `_ld_llm_direct_local.json` suffixes where the backend completes.

- **Hybrid Ladder Diagram IR draft generation** (`src/ld_ir_gen_hybrid.py`)
  from validated `PLC_AST` JSON: the LLM supplies structured code intent and
  Python renders the LD IR deterministically, producing analogue comparison
  contacts (`operator`/`threshold` fields), network-level timer metadata, and
  colour-state review notes, writing `_ld_hybrid_api.json` and
  `_ld_hybrid_local.json` outputs.

- **PLCopen XML export** (planned, EPIC-3 E3S2) for exchanging generated
  program structures with compatible PLC engineering environments.

- **Validation-oriented workflow** that keeps generated artifacts inspectable
  and supports future linting, simulation, and human approval gates.

- **Local LM Studio connectivity test** that discovers the Windows host from
  the WSL default gateway and verifies an OpenAI-compatible chat completion.

- **Local Weaviate vector database** deployed through Docker Compose with
  persistent storage and REST/gRPC access.

- **Prototype RAG pipeline (LlamaIndex)** using LlamaIndex to ingest
  `data/siemens_manual.txt`, store HuggingFace embeddings in Weaviate, query
  the `SiemensManual` vector index, and answer through LM Studio.

- **Prototype RAG pipeline (LangChain)** using LangChain to ingest the same
  manual into a separate `LangChainSiemens` Weaviate index and query it through
  LM Studio, enabling a direct framework comparison.

- **Notebook workspace** for experimentation, prompt evaluation, and prototype
  development.

## 🧭 Workflow and Architecture

The implemented artifact pipeline is:

```text
Natural-Language Requirement (.txt)
            |
            v
  Parsed SystemRequirement JSON      (src/req_parser.py)
            |
            v
   BDD / Gherkin Scenarios (.feature)  (src/gherkin_gen.py)
            |
            v
        PLC_AST JSON                  (src/ast_gen_A/B/C.py)
            |
            +------------------+
            |                  |
            v                  v
  IEC 61131-3 ST / LD IR    PLCopen XML (planned, E3S2)
            |                  |
            +--------+---------+
                     v
       Engineer Review and Validation
```

Each stage produces a validated, backend-tagged artifact under `data/`
(`parsed/` -> `gherkin/` -> `ast/` -> `plc/st` and `plc/ld`). The `PLC_AST`
representation is the central contract in this design: it allows every
generated output to be traced back to an explicit requirement and makes it
possible to add deterministic validation around LLM-generated content. Each
downstream generator (`st_gen*`, `ld_ir_gen*`) consumes the validated `PLC_AST`
directly, so no stage re-reads free-form text.

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or newer
- `pip` and Python virtual environment support
- WSL2 Ubuntu with the `ip` command available
- Docker Engine and Docker Compose v2 available in WSL
- LM Studio running on the Windows host with a chat-capable model loaded
- LM Studio local server listening on port `1234` and allowing WSL connections

### Local Setup

```bash
git clone <repository-url>
cd AutoPLC-Agent

python3 -m venv venv
source venv/bin/activate

python -m pip install -r requirements.txt
```

Always install dependencies inside the project virtual environment. The
repository currently uses the official OpenAI Python SDK v1.x to communicate
with LM Studio's OpenAI-compatible API.

### Environment Variables

The connectivity script supports an optional base URL override:

```bash
export LM_STUDIO_BASE_URL="http://172.24.32.1:1234/v1"
```

If `LM_STUDIO_BASE_URL` is not set, the script dynamically reads the WSL
default gateway using `ip route show default` and constructs
`http://<gateway-ip>:1234/v1`. This avoids hard-coding an address that may
change after a reboot.

The requirement parser also accepts a `--backend {local,api}` argument,
defaulting to `local` (LM Studio). The `api` backend is intended for demo
scenarios where local inference is too slow:

- `api` calls `gemini-3.1-flash-lite` through Google's OpenAI-compatible endpoint
  (`https://generativelanguage.googleapis.com/v1beta/openai/`) and requires the
  `GEMINI_API_KEY` environment variable. The Gemini 3.1 series supports
  `response_format` `json_schema` natively, so this backend uses the same
  default `with_structured_output(SystemRequirement)` binding as the local
  backend with no extra prompt engineering.

The key can be exported in the shell, or placed in a project-root `.env` file
(the convention for `req_parser.py`):

```bash
# .env
GEMINI_API_KEY=your-api-key-here
```

`src/req_parser.py` loads `.env` automatically at startup via `python-dotenv`.
An already-exported shell environment variable takes priority over the `.env`
value (`override=False`). Root `.env` files are ignored by Git, so the real key
is never committed.

### Verify LM Studio Connectivity

Start the LM Studio local server on Windows, load a model, then run:

```bash
source venv/bin/activate
python src/test_llm.py
```

The script lists available models, selects the first loaded model, requests a
brief IEC 61131-3 Structured Text hello-world example, and prints the response.

### Run Weaviate

Start the local Weaviate vector database and verify its metadata endpoint:

```bash
docker compose up -d
curl http://localhost:8080/v1/meta
```

Weaviate exposes its REST API on port `8080`, its gRPC API on port `50051`,
and stores data in the `weaviate_data` Docker volume.

### Run the RAG Prototype

Ingest the Siemens manual into Weaviate:

```bash
source venv/bin/activate
# Ensure local ignored data/siemens_manual.txt exists before running ingestion.
python src/ingest.py
```

Query the indexed manual through LM Studio:

```bash
python src/query.py "What is the default cycle time of the cyclic interrupt OB (Main [OB35])?"
```

The query script dynamically resolves the Windows host from the WSL default
gateway, uses the currently loaded LM Studio model, retrieves source chunks
from the `SiemensManual` Weaviate index, and prints both the answer and source
nodes. The verified answer for the example query is `100000 μs`.

### Run the LangChain RAG Prototype

Ingest the Siemens manual into a separate Weaviate index using LangChain:

```bash
source venv/bin/activate
# Ensure local ignored data/siemens_manual.txt exists before running ingestion.
python src/lc_ingest.py
```

Query the `LangChainSiemens` index through LM Studio:

```bash
python src/lc_query.py "What is the default cycle time of the cyclic interrupt OB (Main [OB35])?"
```

The LangChain query script uses the same dynamic gateway resolution and
HuggingFace embeddings as the LlamaIndex variant, allowing a direct side-by-side
comparison of both frameworks over identical data and questions.

### Run the Requirement Parser

Parse a natural-language requirement into a structured `SystemRequirement` JSON:

```bash
source venv/bin/activate
python -m src.req_parser data/requirements/sample_control.txt
```

The parser writes its output to `data/parsed/` (creating the directory if
needed) and prints extraction statistics. By default it uses the local LM Studio
backend. To use the Gemini cloud API instead (for demos where local inference is
too slow), set `GEMINI_API_KEY` and pass `--backend api`:

```bash
python -m src.req_parser data/requirements/sample_control.txt --backend api
```

Output filenames are tagged by backend — `<name>_parsed_local.json` for `local`
and `<name>_parsed_api.json` for the cloud `api` backend — so local and cloud
extractions for the same input file coexist and can be diffed to compare
extraction quality. Rerunning the same backend overwrites only that backend's
own file.

### Run the Gherkin Generator

Convert a parsed `SystemRequirement` JSON file (the output of the requirement
parser above, **not** a raw `.txt` requirement) into a Gherkin `.feature` file:

```bash
source venv/bin/activate
python -m src.gherkin_gen data/parsed/sample_control_parsed_local.json
```

The generator makes one structured-output call per control-sequence step and
per interlock, assembles the resulting scenarios into a `GherkinFeature`, and
writes a `.feature` file to `data/gherkin/` (creating the directory if needed).
Like the parser, it accepts `--backend {local,api}` (default `local`); pass
`--backend api` with `GEMINI_API_KEY` set to generate through the Gemini cloud
API:

```bash
python -m src.gherkin_gen data/parsed/sample_control_parsed_local.json --backend api
```

The output filename's backend suffix reflects the `--backend` actually used for
generation, not the backend tagged on the input JSON. For example, the command
above reads a `_parsed_local.json` input but, generating with `--backend api`,
writes `data/gherkin/sample_control_api.feature` — so local and cloud Gherkin
runs over the same requirement coexist and can be diffed.

### Run the Structured Text Generator

Convert a validated `PLC_AST` JSON file into a deterministic MVP Structured Text
draft:

```bash
source venv/bin/activate
python -m src.st_gen data/ast/signal_light_demo_api_AST_C.json
python -m src.st_gen data/ast/sample_control_api_AST_C.json
```

The generator builds an `STProgram` contract object, renders BOOL declarations,
sequence `IF` blocks, safety interlock override blocks, and traceability
comments, then writes `.st` files to `data/plc/st/`. Generated ST is a draft
and requires engineer review before any PLC use.

Two additional approaches exist for comparison (see
[Task Completion Status](#-task-completion-status) for details and
verification records):

```bash
# LLM Direct ST (backend comparison)
python -m src.st_gen_llm_direct data/ast/signal_light_demo_api_AST_C.json --backend api
python -m src.st_gen_llm_direct data/ast/signal_light_demo_api_AST_C.json --backend local

# Hybrid ST (LLM suggests intent, Python renders deterministically)
python -m src.st_gen_hybrid data/ast/signal_light_demo_api_AST_C.json --backend api
python -m src.st_gen_hybrid data/ast/signal_light_demo_api_AST_C.json --backend local
```

LLM Direct outputs use `_st_llm_direct_api.st` / `_st_llm_direct_local.st`
suffixes; hybrid outputs use `_st_hybrid_api.st` / `_st_hybrid_local.st`. All
generated ST is a draft and requires engineer review before any PLC use.
MATIEC/OpenPLC/runtime validation is not performed yet.

### Run the Ladder Diagram IR Generators

Generate deterministic LD IR JSON from a validated `PLC_AST` file:

```bash
python -m src.ld_ir_gen data/ast/signal_light_demo_api_AST_C.json
python -m src.ld_ir_gen data/ast/sample_control_api_AST_C.json
```

Deterministic LD IR output uses `<stem>_ld.json` under `data/plc/ld/`.

To compare LLM-direct LD IR generation, run:

```bash
python -m src.ld_ir_gen_llm_direct data/ast/signal_light_demo_api_AST_C.json --backend api
python -m src.ld_ir_gen_llm_direct data/ast/signal_light_demo_api_AST_C.json --backend local
python -m src.ld_ir_gen_llm_direct data/ast/sample_control_api_AST_C.json --backend api
python -m src.ld_ir_gen_llm_direct data/ast/sample_control_api_AST_C.json --backend local
```

LLM Direct LD IR outputs use `_ld_llm_direct_api.json` and
`_ld_llm_direct_local.json` suffixes; the wrapper validates the output against
`LDProgram` (unique network IDs, required coils, allowed contact/coil types,
traceability, sequence-before-interlock ordering) and writes only validated
JSON, with validation-feedback retries for the local backend.

The hybrid LD IR generator reuses the hybrid ST intent pipeline:

```bash
# Hybrid LD IR (LLM suggests intent, Python renders deterministically)
python -m src.ld_ir_gen_hybrid data/ast/signal_light_demo_api_AST_C.json --backend api
python -m src.ld_ir_gen_hybrid data/ast/signal_light_demo_api_AST_C.json --backend local
```

Hybrid outputs use `_ld_hybrid_api.json` / `_ld_hybrid_local.json` suffixes and
pass the same `validate_ld_structure` checks as the deterministic baseline.
See [Task Completion Status](#-task-completion-status) for verification records
and troubleshooting notes.

## 📦 Project Structure

```text
AutoPLC-Agent/
├── data/
│   ├── requirements/ # Input natural-language requirement .txt files
│   ├── parsed/       # Structured SystemRequirement JSON output
│   ├── gherkin/      # Generated Gherkin .feature output
│   ├── ast/          # Generated PLC_AST JSON output
│   ├── plc/
│   │   ├── st/       # Generated Structured Text draft output
│   │   └── ld/       # Generated Ladder Diagram IR JSON output
│   └── siemens_manual.txt # Local ignored Siemens PLC text for RAG testing
├── notebooks/        # Experiments, evaluations, and prototypes
├── src/
│   ├── ast_builders.py      # Deterministic AST builder helpers for Approach C
│   ├── ast_gen_A.py         # LLM-direct SystemRequirement + Gherkin to PLC_AST
│   ├── ast_gen_B.py         # Deterministic SystemRequirement + Gherkin to PLC_AST
│   ├── ast_gen_C.py         # RPC/function-calling SystemRequirement + Gherkin to PLC_AST
│   ├── ast_schemas.py       # Pydantic PLC_AST schemas
│   ├── gherkin_gen.py       # SystemRequirement JSON to Gherkin .feature generator
│   ├── gherkin_schemas.py   # Pydantic GherkinScenario/GherkinFeature schemas
│   ├── ingest.py            # LlamaIndex ingestion into Weaviate (SiemensManual index)
│   ├── lc_ingest.py         # LangChain ingestion into Weaviate (LangChainSiemens index)
│   ├── lc_query.py          # LangChain RAG query over Weaviate and LM Studio
│   ├── ld_ir_gen.py         # Deterministic PLC_AST to LD IR JSON generator
│   ├── ld_ir_gen_hybrid.py  # Hybrid PLC_AST to LD IR JSON generator
│   ├── ld_ir_gen_llm_direct.py # LLM-direct PLC_AST to LD IR JSON generator
│   ├── plc_code_schemas.py  # Pydantic ST/LD output contracts
│   ├── query.py             # LlamaIndex RAG query over Weaviate and LM Studio
│   ├── req_parser.py        # Natural-language requirement parser to structured JSON
│   ├── schemas.py           # Pydantic SystemRequirement structured-output schemas
│   ├── st_gen.py            # Deterministic PLC_AST to Structured Text draft generator
│   ├── st_gen_hybrid.py     # Hybrid PLC_AST to Structured Text draft generator
│   ├── st_gen_llm_direct.py # LLM-direct PLC_AST to Structured Text draft generator
│   ├── st_hybrid_schemas.py # Pydantic hybrid code-intent schemas
│   └── test_llm.py          # WSL-to-LM Studio API connectivity test
├── tests/            # unittest suites for the ST/LD generators
├── .gitignore        # Repository ignore rules
├── docker-compose.yml # Local Weaviate service definition
├── JIRA_KANBAN.md    # Jira-style Epic, Story, and Task tracker
├── LICENSE           # MIT license
├── README.md         # Project overview and development record
└── requirements.txt  # Python dependencies
```

As implementation progresses, `src/` should be organized around clear
boundaries such as requirements parsing, BDD generation, intermediate models,
IEC 61131-3 generation, PLCopen XML export, and validation.

## 💻 Technology Stack

| Area | Technology | Status |
| --- | --- | --- |
| Runtime | Python 3.10+ | In use |
| Local LLM engine | LM Studio OpenAI-compatible API | Connected |
| Cloud LLM engine (demo) | Gemini API (`gemini-3.1-flash-lite`) | Optional `--backend api` |
| AI integration | OpenAI Python SDK v1.x | In use |
| WSL networking | Dynamic default gateway discovery | Implemented |
| Vector database | Weaviate 1.24.4 | Deployed |
| Container runtime | Docker Engine and Docker Compose v2 | In use |
| RAG framework | LlamaIndex | Prototype implemented |
| RAG framework | LangChain + LCEL | Prototype implemented |
| Embeddings | HuggingFace `BAAI/bge-small-en-v1.5` | In use |
| Structured extraction | Pydantic + LangChain `with_structured_output` | In use |
| Requirements format | BDD / Gherkin syntax | Implemented (`src/gherkin_gen.py`) |
| Intermediate representation | AST / JSON | Implemented (`PLC_AST`) |
| PLC languages | IEC 61131-3 Structured Text and Ladder Diagram | ST draft generator and LD IR generator MVP implemented |
| Interchange format | PLCopen XML | Planned |
| Experimentation | Jupyter notebooks | `explore_gherkin_ast.ipynb` |

Dependency versions, including the OpenAI SDK and its transitive dependencies,
are pinned in `requirements.txt`.

## 🛡️ Development Principles

- Keep requirements, generated scenarios, intermediate models, and PLC outputs
  traceable to one another.
- Prefer structured schemas and parsers over free-form text transformations.
- Validate generated artifacts before exposing them to downstream tooling.
- Keep secrets, virtual environments, caches, and local data out of version
  control.
- Treat generated PLC logic as a draft that requires engineer review, testing,
  and safety validation.

## ✅ Task Completion Status

Task titles are based on `JIRA_KANBAN.md`; completed work is recorded below.

### EPIC-1: Infrastructure & Environment Setup

#### E1S0: [Step 0] Environments and GitHub Initialization

- [x] **E1S0T1 - Environments and GitHub Initialization**
- [x] **E1S0T2 - Create the initial repository documentation**
- [x] **E1S0T3 - Add root ignore rules**
- [x] **E1S0T4 - Initial Repository Scaffold**

#### E1S1: [Phase 1] LM Studio deployment and models pulling

- [x] **E1S1T1 - Download and install LM Studio**
- [x] **E1S1T2 - Identify and pull appropriate local LLM models for testing natural language understanding**

#### E1S2: [Phase 2] Connection of the API from Windows to WSL

- [x] **E1S2T1 - Configure WSL network settings to access the Windows host LM Studio API server**
- [x] **E1S2T2 - Create a test script to verify API connectivity from within WSL**

#### E1S3: [Phase 3] Deployment Weaviate vector DB (Docker in WSL)

- [x] **E1S3T1 - Verify Docker installation in the WSL environment**
- [x] **E1S3T2 - Create `docker-compose.yml` for Weaviate vector database**
- [x] **E1S3T3 - Deploy Weaviate instance and verify its running status and API accessibility**

#### E1S4: [Phase 4] Build RAG pipeline and evaluation of frameworks

- [x] **E1S4T1 - Build a prototype RAG pipeline connecting the LLM to the Weaviate DB using LlamaIndex**
- [x] **E1S4T2 - Build a prototype RAG pipeline connecting the LLM to the Weaviate DB using LangChain**
- [ ] **E1S4T3 - Document the findings and finalize framework selection**

### EPIC-2: Core Agent Pipeline

#### E2S1: Natural-language requirement ingestion

- [x] **E2S1T1 - Develop the parser and input interface for control sequences, equipment behavior, and interlocks**

`src/req_parser.py` implements all six specified components (file I/O, dynamic
WSL-to-LM Studio LLM initialization, system prompting, structured Pydantic
binding, chain execution, and JSON output handling). It was locally verified
against `data/requirements/sample_control.txt` (LM Studio + `gemma-4-E4B`,
600 s timeout), successfully extracting 4 equipment items, 2 interlocks, and 5
sequence steps, with output written to `data/parsed/sample_control_parsed.json`.
The script also supports a `--backend {local,api}` argument (default
`local`); the `api` backend targets `gemini-3.1-flash-lite` via the Google
cloud API (requires `GEMINI_API_KEY`) for demos where local inference is too
slow.

##### Core Extraction Logic — Verification Results

Local verification confirmed the pipeline runs end to end, but it is **not** a
clean pass. The findings below are recorded for follow-up.

**Verified correct:**

- All interlocks were extracted accurately, matching both safety constraints in
  the source text with no fabricated conditions or actions.
- Sequence steps were extracted in the correct logical order matching the source
  narrative, with no hallucinated steps.
- No equipment, interlocks, or steps were invented that are absent from the
  source text (no fabrication in the populated fields).

**Known issues:**

- **Equipment omission:** the "Emergency Stop button" mentioned in the source
  text's safety constraints was NOT included in `equipment_list`, even though it
  is referenced inside an interlock condition. The equipment list is therefore
  incomplete relative to the schema's instruction to capture "all distinct
  equipment items mentioned anywhere in the requirement."
- **Field misuse in `Equipment`:** engineering tags (e.g. "EV-101") were
  embedded inside the `type` field (e.g. "Valve/Actuator (EV-101)") instead of
  the `name` field as the schema intends, leaving `name` and `type`
  inconsistently populated across equipment items.
- **Formatting inconsistency in `ControlSequence.description`:** several steps
  contain embedded `\n\t` line breaks and inline sub-labels (e.g. "Action:",
  "Condition:") rather than a single coherent natural-language sentence as the
  schema field description specifies.

**Planned follow-up:**

- Strengthen the system prompt to explicitly require that (a) every piece of
  equipment mentioned anywhere in the text — including equipment referenced only
  inside interlock conditions — must appear in `equipment_list`, and (b) the
  `name` field must use the engineering tag when present, with the `type` field
  holding only the normalized category.
- Constrain `ControlSequence.description` to a single-line, plain-sentence format
  with no embedded line breaks or labels, to keep the field reliably parseable
  downstream.

##### Local vs. Cloud Extraction Comparison

The same input (`sample_control.txt`) was parsed with both backends — local LM
Studio and the cloud `gemini-3.1-flash-lite` via the `api` backend (run at
the time
as `--backend gemini`, since renamed to `--backend api` with no functional
change). Both runs extracted all interlocks and sequence steps correctly with no
fabricated content. The cloud run improved on every local-run issue logged in
Verification Results above:

| Issue (see Verification Results above) | Local | Cloud (`api`) |
|---|---|---|
| Equipment completeness | 4/5 items (Emergency Stop omitted) | 5/5 items |
| `name`/`type` field convention | Tag embedded in `type` | Tag in `name`, clean category in `type` |
| `description` formatting | Embedded `\n\t` and inline labels | Single-line plain sentences |
| Interlock condition phrasing | States the prohibition as the condition | States the triggering event as the condition |

Note: both runs share one schema limitation (not attributable to either
backend) — `ControlSequence` has no separate field for a step's triggering
condition, so trigger info is folded into the description; a potential future
schema enhancement, not an extraction defect.

#### E2S2: BDD/Gherkin generation and validation

- [x] **E2S2T1 - Prompt engineering to convert requirements into Gherkin `Feature`, `Scenario`, `Given`, `When`, `Then` syntax**

`src/gherkin_schemas.py` defines the `GherkinScenario` and `GherkinFeature`
Pydantic schemas, and `src/gherkin_gen.py` implements the generation pipeline:
it reads a parsed `SystemRequirement` JSON file, makes one
`with_structured_output(GherkinScenario)` call per control-sequence step and per
interlock (mapping step descriptions and interlock condition/action into
`Given/When/Then`), and stamps each scenario with its `source_step_id` or verbatim
`source_interlock_condition` for traceability. Per-item generation isolates
failures — a single failed item is skipped with a warning instead of aborting the
file. A separate, deterministic non-LLM renderer guarantees syntactically correct
`.feature` output regardless of model quality, and one additional LLM call
generates the feature title and description before the `GherkinFeature` is
assembled in Python. Output is written to a backend-tagged
`data/gherkin/<name>_<backend>.feature` file, where the suffix reflects the
`--backend` used for generation. The pipeline was locally verified end to end
against both backends (LM Studio `local` and Gemini `api`), producing valid
`.feature` files for the `signal_light_demo` requirement.

**Verification Results & Enhancements:**

- **Backend & Rate Limiting:** Migrated the `api` backend to `gemini-3.1-flash-lite` for higher free-tier limits and added a `--call-delay` argument to prevent rate-limit exhaustion during multi-call runs.
- **Hallucination Prevention (Fixed):** Replaced case-by-case prompt patching with deterministic Python checks to reliably catch LLM fabrication. Added `flag_unsupported_given()` to strip `given` entries that lack grounding in the source text, and added checks to filter empty fields before rendering. These checks successfully caught and removed hallucinated placeholders from the `local` backend.
- **Scenario Naming (Deferred):** The `local` backend occasionally hallucinates ungrounded `GherkinScenario.name` fields (e.g., mislabeling an interlock). The planned fix is to extend the same grounding-check pattern to the `name` field rather than relying on further prompt tuning.

#### E2S3: AST/JSON intermediate representation

- [x] **E2S3T1 - Create the JSON schema for the AST that connects requirements, scenarios, and code blocks**

E2S3T1 has been delivered through **three independent approaches** (A, B, and
C), retaining one shared `PLC_AST` schema.

`src/ast_schemas.py` defines the `DeviceNode`, `SequenceStepNode`,
`InterlockNode`, and `PLC_AST` Pydantic schemas with full
`Field(description=...)` coverage.

**Approach A** (`src/ast_gen_A.py`) — a single `with_structured_output(PLC_AST)`
LLM call over the combined `SystemRequirement` JSON and raw Gherkin `.feature`
text — post-stamping `source_requirement_file` and `source_gherkin_file`
deterministically after the call (the same provenance pattern used for
`source_step_id` in E2S2). The pipeline was locally verified end to end against
both backends (LM Studio `local` and Gemini `api`), producing valid `PLC_AST`
files for the `signal_light_demo` and `sample_control` requirements.

**Approach B** (`src/ast_gen_B.py`) — a fully deterministic, **zero-LLM**
pipeline that uses the `gherkin-official` library to parse the `.feature`
file and rule-based text matching (Dice coefficient over tokenized scenario
steps) to cross-reference Gherkin scenarios with requirement steps. It accepts
two positional arguments (`req_file`, `feature_file`) with no `--backend`
flag and writes to `data/ast/<stem>_AST_B.json`. The pipeline was verified
end to end against both available datasets with 100 % scenario-matching
accuracy.

##### Approach A — Verification Results

**Verified correct:**

- Both backends produced valid `PLC_AST` objects with correct `node_id`
  prefixes (`DEV-`/`SEQ-`/`ILK-`) on the first run.
- `action` fields in `SequenceStepNode` contained the verbatim
  `ControlSequence` descriptions — no paraphrasing was observed on either
  backend.
- `affected_devices` in `InterlockNode` contained only real equipment names
  from the source `equipment_list` on both backends.
- `source_requirement_file` and `source_gherkin_file` were correctly stamped as
  absolute paths by the script, confirming the post-call stamping logic worked
  as intended.
- Cross-stage traceability was confirmed: `source_scenario` fields correctly
  linked AST nodes back to real `GherkinScenario` names from the corresponding
  `.feature` file on both backends — the first complete
  requirement→scenario→AST chain in the project.

**Known issues / observations:**

- **Optional field divergence:** the optional `condition` field in
  `SequenceStepNode` showed a backend divergence — the `api` backend extracted
  the triggering condition from the action description ("the operator presses
  the start pushbutton") while the `local` backend left it `null`. Both are
  schema-valid; this continues the pattern observed in E2S2 where the `api`
  backend fills optional fields more readily than the `local` backend.
- **`node_id` spacing (deferred):** `node_id` values for multi-word device
  names contain spaces (e.g. `"DEV-start pushbutton"`), which is valid for the
  AST but will conflict with IEC 61131-3 variable naming rules at E2S4. Deferred
  technical debt: add a `sanitize_node_id()` function at E2S4 rather than now.
- **`feature_title` differs between backends:** this reflects the title from
  each backend's own `.feature` file and is correct behaviour, not a defect.

##### Approach B — Verification Results

**Verified correct:**

- Both available datasets (`signal_light_demo` and `sample_control`) generated
  valid `PLC_AST` objects with no validation errors on the first run.
- `feature_title`, `devices`, `node_id`, `step_id`, `action`, `condition`,
  and `source_scenario` fields all matched Approach A outputs exactly on
  identical input.
- Scenario cross-referencing achieved **100 % accuracy**: every
  `ControlSequence` step and every `Interlock` was correctly matched to its
  corresponding Gherkin scenario via Dice-coefficient token matching.
- `source_requirement_file` and `source_gherkin_file` were correctly stamped
  as resolved absolute paths.
- `action` fields contain verbatim `ControlSequence.description` text
  (no paraphrasing by construction — no LLM is involved).
- `affected_devices` in `InterlockNode` accurately lists all equipment names
  referenced in interlock conditions and actions.

**Known differences from Approach A (LLM-based):**

These are **deliberate, documented trade-offs** between the two approaches,
not bugs. They motivate the design of Approach C.

1. **`affected_devices` ordering (cosmetic):** Approach A orders devices
   based on LLM reasoning (condition-then-action or semantic priority).
   Approach B returns devices in the deterministic order they appear in the
   source `equipment_list`. In practice the two orderings are semantically
   equivalent: the same set of devices is identified. Example — for the
   interlock ``"Emergency Stop button is pressed → SL-301 must immediately
   switch to red"``:
   - **Approach A:** ``["Emergency Stop button", "SL-301"]``
   - **Approach B:** ``["SL-301", "Emergency Stop button"]``
   - *Impact:* ordered as in `equipment_list`; functionally identical.

2. **`target_device` selection (semantic):** Approach A uses LLM semantic
   reasoning to identify which device is the **target** of the action vs.
   which is the **trigger**. Approach B naively picks the first equipment
   name from `equipment_list` that appears as a substring in the
   description text. Example — for the step description ``"When the
   operator presses the start pushbutton, SL-301 must turn green."``:
   - **Approach A:** ``"SL-301"`` — correctly identifies SL-301 as the
     target device (the thing being acted on).
   - **Approach B:** ``"start pushbutton"`` — picks the first match from
     `equipment_list`, which is listed first in the source.
   - *Impact:* Approach B's result is schema-valid but semantically less
     precise. This limitation is the strongest argument for **Approach C**
     (RPC/function calling), where an LLM would reason *about* the mapping
     into deterministic structures rather than emitting free-form JSON or
     relying on naive string matching.

**Follow-up (Approach C only):**

- **Approach C** (`src/ast_gen_C.py`): RPC/function calling — the LLM triggers
  structured builder calls rather than emitting the complete AST. Python
  rejects unsupported calls and rejects targets, affected devices, or scenario
  links that are not grounded in the two input artifacts. This preserves the
  semantic target-device advantage of Approach A while reducing the model's
  ability to corrupt AST structure or traceability.

##### Approach C — Verification Results and trade-offs

The builder/tool-call path was verified with structured mock tool responses on
both `signal_light_demo` and `sample_control` inputs (local and API artifacts),
including device counts, verbatim source fields, node IDs, scenario-name
grounding, affected-device grounding, and final `PLC_AST` validation. A live
backend run additionally requires LM Studio for `local` or `GEMINI_API_KEY` for
`api`.

**Local verification fixes:**

- **LM Studio tool-calling compatibility:** local LM Studio rejected object-style
  `tool_choice`, so `_invoke_tool()` now uses `tool_choice="required"` for
  `local`, while `api` keeps `tool_choice=expected_name`. `_tool_call()` still
  validates the returned builder name.
- **Authoritative field protection:** local `sample_control` paraphrased step
  3's `action`, causing `Function call changed authoritative sequence text for
  step 3`. Python now overwrites source-owned fields before builder validation:
  sequence `step_id`, `action`, `source_step_id`; interlock `index`,
  `condition`, `forced_action`, `priority`.

`affected_devices` is deterministic in Approach C: all equipment mentioned in
the interlock condition or forced action, preserving `equipment_list` order and
avoiding partial-name matches such as `EV-101` matching `EV-1012`.

**`signal_light_demo` comparison**

| Output | Result summary |
| --- | --- |
| A API | Valid; correctly selects `SL-301`; good condition and scenario links. |
| B | Valid and deterministic; incorrectly selects `start pushbutton` as `target_device`. |
| C API | Best result; correctly selects `SL-301`, concise condition, deterministic `affected_devices`. |
| A local | Valid; selects `SL-301`, but condition/scenario wording depends on local model output. |
| C local | Runs successfully; structurally valid, but local semantic mapping is weaker (`target_device`, `condition`, or `source_scenario` may be null). |

**`sample_control` comparison**

| Output | Result summary |
| --- | --- |
| A API | Valid; strong semantic output, but full AST is generated directly by the LLM. |
| B | Valid and deterministic; stable target devices and scenario links, but some conditions are more mechanical. |
| C API | Best result; correct targets, cleaner conditions, deterministic `affected_devices`, Python-controlled assembly. |
| A local | Valid but model-dependent; some conditions are short or less precise. |
| C local | Runs successfully after fixes; deterministic fields are stable, but local semantic mapping can still be weaker than API. |

Conclusion: Approach C API is the preferred engineering design because it
combines LLM semantic mapping with deterministic Python validation, grounding,
provenance stamping, and AST assembly; local model quality remains the main
limitation for local verification.

#### E2S4: IEC 61131-3 ST and LD generation

- [x] **E2S4T1 - Define ST/LD output contracts**
- [x] **E2S4T2 - Implement deterministic Structured Text generator**
- [x] **E2S4T3 - Implement LD IR generator**
- [x] **E2S4T4 - Add LLM Direct Structured Text generator**
- [x] **E2S4T5 - Add LLM Direct LD IR generator**
- [x] **E2S4T6 - Add Hybrid Structured Text generator**
- [x] **E2S4T7 - Add Hybrid LD IR generator**

`src/plc_code_schemas.py` defines the initial schema-only contracts for future
PLC code generation. ST output is represented by `STProgram` and `STBlock`; LD
output is represented by `LDProgram`, `LDNetwork`, `LDContact`, and `LDCoil`.
E2S4T2 adds `src/st_gen.py`, a deterministic MVP ST generator from `PLC_AST`.
It renders BOOL declarations, sequence `IF` blocks, interlock override blocks,
and traceability comments, with output written to `data/plc/st/*.st`.
Generated ST is a draft and requires engineer review.

E2S4T4 adds `src/st_gen_llm_direct.py`, a separate `llm_direct` ST generation
approach. It validates `PLC_AST` input, asks the selected backend to directly
produce plain Structured Text, performs light structural checks, and writes
backend-specific outputs using `_st_llm_direct_api.st` or
`_st_llm_direct_local.st`. Both API and local backend runs completed for the
two current example AST files. These outputs are comparison artifacts for model
capability, prompt-following, backend reliability, and engineering constraint
evaluation; they do not replace the deterministic Python ST generator.

E2S4T6 adds `src/st_gen_hybrid.py`, a hybrid ST generation approach that
combines the deterministic baseline renderer with per-item LLM function calls
returning *structured code intent* instead of final code. The LLM suggests
complex logic (timers/delays, analogue thresholds, colour states,
sequence-state notes) through `suggest_sequence_intent` /
`suggest_interlock_intent` tools; Python validates grounding against the AST
device list and renders the final ST deterministically — TON function-block
calls for timers, REAL comparisons for analogue conditions (the measured
device is declared `REAL`), and colour-state review comments. Backend-flattened
tool args (for example `'SL-301: green'` or a bare `'5'` duration) are
normalized deterministically by Python before Pydantic validation. Writes
`_st_hybrid_api.st` / `_st_hybrid_local.st` outputs.
Local-backend hardening: Gemma 4 E2B returns backend-flattened tool args
(compact keyed mappings such as `{'SL-301': 'green'}`), can drop comparison
operators on analogue thresholds, and occasionally emits condition text as
colour-state entries. Python normalization now accepts compact dict mappings,
the sequence prompt requires comparison operators, and unparseable colour-state
entries degrade to review notes (grounding failures still abort). Both example
ASTs verified with `--backend local`; E2B semantic quality matched the API
backend (same REAL comparison and TON rendering), with drift limited to
output-format discipline.

E2S4T7 adds `src/ld_ir_gen_hybrid.py`, the hybrid LD IR counterpart that
reuses the E2S4T6 intent pipeline. Python renders analogue intents as
`LDContact` entries carrying `operator`/`threshold` fields, timer intents as
network-level `timer_duration_seconds`/`timer_description` metadata, and
colour/state intents as review notes — replacing the deterministic baseline's
`TODO_UNSUPPORTED_CONDITION` placeholders for timer and analogue conditions.
`src/plc_code_schemas.py` gained optional `operator`/`threshold` on
`LDContact` and timer fields on `LDNetwork`; all default to `None`, keeping
existing deterministic and LLM-direct outputs unchanged.
Verified with `--backend local` (Gemma 4 E2B) on both example ASTs: IR
structure identical to the API backend across all 10 networks. The E2S4T6
local-backend hardening applies unchanged here because LD reuses
`_collect_intents`, and it demonstrably fired: 6 unparseable colour-state
entries from ILK-1/ILK-2 degraded to review notes instead of aborting.

E2S4T3 adds `src/ld_ir_gen.py`, a deterministic AST-to-LD-IR generator. It
outputs structured LD JSON under `data/plc/ld/*.json`. LD IR represents
sequence and interlock logic as networks with contacts, coils, priority, and
traceability links. It supports basic controlled action-to-coil mapping:
positive actions such as open, start, on, energize, activate, and run map to
set coils; negative/deactivation actions such as close, stop, off,
de-energize, deactivate, and reset map to reset coils. Interlock forced actions
use the same deterministic classifier. Matching is case-insensitive and
boundary-safe; ambiguous or negated action text falls back to a normal coil.
This is not graphical LD and not PLCopen XML yet. Generated LD IR is an MVP
draft and requires engineer review.

The current regenerated LD IR examples are:
`signal_light_demo_api_AST_C_ld.json` with 2 networks, and
`sample_control_api_AST_C_ld.json` with 8 networks. Sequence networks appear
before safety interlock networks. Multi-target interlocks are split into one
coil per network.

E2S4T5 adds `src/ld_ir_gen_llm_direct.py`, a separate `llm_direct` LD IR
generation approach. It validates `PLC_AST` input, asks the selected backend to
directly produce LD IR JSON, validates the result against `LDProgram`, performs
light structural checks, and writes backend-specific outputs using
`_ld_llm_direct_api.json` or `_ld_llm_direct_local.json`. API and local backend
generation completed for both current example AST files. The LD Direct prompt
explicitly requires sequence networks before interlock networks, separates
logical safety priority from JSON array order, splits multi-target interlocks
into one network per target coil, uses IEC-compatible variable names, and
records unsupported timer/analogue/sequence-state logic in notes. Local backend
generation now uses `json_schema` response format plus validation-feedback
retries to produce valid LD Direct JSON for both examples. The local Gemma E4B
backend initially failed on `sample_control` due to ordering, variable naming,
and weak interlock coil issues; after prompt hardening and retry feedback it
now saves an 8-network valid JSON artifact.

Known MVP limitations: The generated ST and LD IR files are draft outputs for
review. In `signal_light_demo`, the BOOL-only model cannot fully represent
green/red signal-light states. In `sample_control`, some steps remain
structurally incomplete because sequence state, timer logic, analogue
conditions, parallel LD branches, graphical layout, and vendor-specific
PLCopen XML export are not yet supported. LD contacts currently represent only
simple positive AND conditions as serial normally-open contacts. OR,
negation, timers, durations, and analogue/numeric comparisons are marked with
explicit `notes` metadata rather than silently approximated. These are
deferred to later E2S4 refinement and verification tasks, not blockers for
E2S4T3. LLM Direct ST outputs can also vary by backend: the API output followed
the requested sequence-before-interlock ordering more closely in the current
run, while local output showed prompt-following weaknesses such as reordered
safety logic and more speculative state/timer structure. These are comparison
findings, not completed validation. LLM Direct LD IR API output is a useful
comparison draft and now splits `sample_control` multi-target interlocks into
one network per target coil. Current local outputs for `signal_light_demo` and
`sample_control` passed validation and were saved, but local generation remains
more model-dependent and should be reviewed carefully before downstream use.

##### Cross-Approach Comparison

Three generation approaches now coexist for both output types, compared below
across approach, technical characteristics, implementation, and observed
behaviour on the two example ASTs (`signal_light_demo` — 2 networks/simple
BOOL logic; `sample_control` — 8 networks/timers + analogue + multi-target
interlocks).

| Approach | Technical characteristics | Implementation | `signal_light_demo` (ST / LD) | `sample_control` (ST / LD) |
|---|---|---|---|---|
| **Deterministic** (E2S4T2/T3) | No LLM, fully reproducible; correct within capability, but timers/analogue/colour cannot be rendered | Rule engine: AST traversal -> variable map -> template rendering (`st_gen.py` / `ld_ir_gen.py`); unsupported logic marked with `notes` / `TODO_UNSUPPORTED_CONDITION` | ST: 3 vars, 2 blocks, complete BOOL logic; LD: 2 networks, plain contacts | ST: 5 vars, BOOL-only draft, no timer/analogue logic; LD: 8 networks but 2 `TODO_UNSUPPORTED_CONDITION` placeholders (timer + analogue) |
| **LLM Direct** (E2S4T4/T5) | LLM generates the final code/IR directly; no rendering middle layer; output quality depends on model discipline; not reproducible across backends | Single prompt -> full program -> Markdown-fence cleanup -> light structural checks (LD: JSON cleanup + validation retries); per-backend output suffixes | ST: api 1.1 KB / local 2.3 KB; local adds `ELSIF` + `= TRUE` style and free-form naming; LD: 2 networks, passes validation | ST: api 7 vars / local 9 vars (5.0 KB, most verbose); LD: 8 networks, multi-target interlocks split, but model-chosen naming (`DEV_` prefix) and network IDs (`ILK-1..4`) |
| **Hybrid** (E2S4T6/T7) | Semantics from LLM, structure from Python: LLM returns structured intent only; language-agnostic intent pipeline shared by ST and LD | Per-item tool calls (`suggest_sequence_intent` / `suggest_interlock_intent`) -> arg normalization (str/list/compact dict) -> grounding checks -> deterministic rendering (TON blocks, REAL comparisons, colour notes); intent graded by semantic load (code-bearing aborts, comment-bearing degrades) | ST: 3 vars, 2 blocks, colour intents green/red as review notes; LD: 2 networks, colour notes; api/local structurally identical | ST: 6 vars, 5 IF blocks, REAL comparison + TON block rendered; LD: 8 networks, analogue contact `>= 80` + timer `5s` metadata; api/local structurally identical (10/10 networks); local-only: 1 (ST) / 6 (LD) degraded colour-state review notes from E2B |

**Backend observations:** the `api` backend (Gemini `3.1-flash-lite`) is
consistently stable and format-disciplined across all three approaches. The
`local` backend (LM Studio, Gemma 4 E2B) delivers equal *semantic* quality but
shows format drift: LLM Direct local output is markedly more verbose with
free-form naming, while Hybrid local output reproduces the API structure
exactly (see the E2S4T6 local-backend hardening note above). Direct outputs are
comparison artifacts only; Hybrid is the recommended default because it keeps
LLM capability (timers, analogue, colour) inside a deterministic, reviewable
rendering pipeline.

Next verification work moves to EPIC-3 `E3S1 - Output artifact verification`,
including pytest-based structure checks, MATIEC syntax/compile investigation,
and OpenPLC Editor / Runtime validation exploration.

Both hybrid generators are now implemented (`E2S4T6` Structured Text and
`E2S4T7` LD IR): the LLM converts complex actions (timers, analogue
thresholds, sequence state, colour states) into structured code intent, and
Python renders the final code deterministically.

### EPIC-3: Validation & Export

#### E3S1: Output artifact verification

- [x] **E3S1T1 - Add pytest structural checks for parsed `SystemRequirement` artifacts**

E3S1T1 adds `tests/test_parsed_requirements.py`, a fully offline, deterministic
structural-verification suite over `data/parsed/*_parsed_*.json`. Each artifact
is deserialized into the `SystemRequirement` Pydantic model and checked for:
non-empty equipment / sequence / interlock fields, monotonic continuous
`step_id`, and grounding of device tags referenced in interlock/sequence text
back to the `equipment_list` (matching a device's `name` or `type` to remain
valid for the `local` backend, which historically embeds engineering tags in
`type`). 6 tests pass; the full suite is now 36 tests.

- [x] **E3S1T2 - Add pytest structural checks for Gherkin `.feature` artifacts**

E3S1T2 adds `tests/test_gherkin_features.py`, a fully offline suite that parses
`data/gherkin/*.feature` with the standard `gherkin-official` parser and checks
generated feature: valid Gherkin syntax, a non-empty feature title with at
least one scenario, valid Given/When/Then/And step keywords with a `When` +
`Then` per scenario, and scenario coverage of the paired
`data/parsed/*_parsed_*.json` items (sequence steps + interlocks). 7 tests pass
(one `expectedFailure` for the known E2S2 `local` coverage gap on
`sample_control`); the full suite is now 43 tests.

**Traceability boundary:** `.feature` text does not carry the
`source_step_id` / `source_interlock_condition` fields (they live on the
in-memory `GherkinScenario` model and are not emitted by the renderer), so
per-scenario traceability cannot be asserted from the `.feature` artifact. It
requires a generator-side change that persists the traceability JSON and is
tracked separately.

- [x] **E3S1T3 - Add pytest structural checks for `PLC_AST` artifacts**

E3S1T3 adds `tests/test_ast_validation.py`, a fully offline suite over every
`data/ast/*.json`. Each artifact deserializes into `PLC_AST` and is checked
for: non-empty devices with continuous `step_id`, interlocks with non-empty
condition / forced_action / affected_devices and `priority >= 1`, provenance
stamps (`source_step_id` / `source_interlock_condition`) with
`source_requirement_file` / `source_gherkin_file` resolving to real input
files, and grounding — each `device.source_equipment` maps verbatim into the
source parsed `equipment_list`, and device tags referenced in sequence /
interlock text resolve to a known device. 8 tests pass; the full suite is now
51 tests.

- [x] **E3S1T4 - Add pytest structural checks for generated ST artifacts**

E3S1T4 adds `tests/test_st_validation.py`, a fully offline suite over
`data/plc/st/*.st` with a two-tier check. A basic contract applies to all ST
files (`PROGRAM`/`END_PROGRAM` wrapper, non-empty executable logic, no Markdown
fences); strict checks apply to the Python-rendered deterministic + hybrid
outputs (`VAR`/`END_VAR`, balanced `IF`/`END_IF`, traceability comments,
`Sequence Logic` + `Safety Interlocks` headers, and interlock-override after
the sequence). LLM Direct output is validated to the basic contract only — it
is a raw LLM draft by convention, and strict ST conformance is deferred to the
MATIEC compiler check (E3S1T7). 10 tests pass; the full suite is now 61 tests.

- [x] **E3S1T5 - Add pytest structural checks for generated LD IR artifacts**

E3S1T5 adds `tests/test_ld_ir_validation.py`, a fully offline suite over
`data/plc/ld/*.json`. Common checks apply to all LD IR files: `LDProgram`
schema validity, unique network IDs, legal contact/coil types, a non-empty coil
per network, sequence-before-interlock ordering, and a `source_ast_node_id`
stamp per network. Python-rendered outputs (deterministic + hybrid) add
`priority >= 1` and per-network step/interlock traceability; LLM Direct
(comparison draft) uses the common contract plus non-negative priority and
`source_ast_node_id`. Note: some `sample_control` sequence networks are
legitimate 0-contact coil-only rungs, so contact count is not enforced. 10
tests pass; the full suite is now 71 tests.

Remaining E3S1 work: hybrid structural checks (E3S1T6), MATIEC investigation
(E3S1T7), OpenPLC compile + open-source runtime simulation (E3S1T8), and a TIA
Portal / PLCSIM documentation-only feasibility study (E3S1T9).

#### E3S2: PLCopen XML export

- [ ] **E3S2T1 - Create export module mapping PLC_AST to interoperable PLCopen XML** (planned).
- [ ] **E3S2T2 - Validate generated PLCopen XML** (planned).

#### E3S3: Component tests and validation framework

- [ ] **E3S3T1 - Build a two-tier validation framework** (planned).
- [ ] **E3S3T2 - Add unit tests for parsers and generators** (planned).
- [ ] **E3S3T3 - Add negative / failure-path test cases** (planned).

## 👥 Contributors

| Task ID | Contribution |
| --- | --- |
| E1S0T2 | Created the initial project overview, feature, workflow, setup, structure, and technology stack documentation |
| E1S0T3 | Added repository hygiene documentation for virtual environments, Python caches, `.env` files, and local `data/` |
| E1S2T1 | Installed the OpenAI SDK in the project venv and established dynamic WSL-to-Windows LM Studio addressing |
| E1S2T2 | Added and verified `src/test_llm.py` for LM Studio chat completion connectivity |
| E1S3T1 | Verified Docker Engine and Docker Compose v2 in WSL |
| E1S3T2 | Added the pinned Weaviate Docker Compose service with persistent storage |
| E1S3T3 | Started Weaviate and verified the local metadata API |
| E1S4T1 | Added LlamaIndex ingestion and query scripts for the Siemens manual RAG prototype |
| E1S4T2 | Added LangChain ingestion (`lc_ingest.py`) and query (`lc_query.py`) scripts targeting a separate `LangChainSiemens` Weaviate index for framework comparison |
| E2S1 | Implemented `src/req_parser.py` (all six components) and locally verified structured extraction against `sample_control.txt`; documented known issues (Emergency Stop omitted from `equipment_list`, engineering tags placed in `type` instead of `name`, and embedded line breaks/labels in `ControlSequence.description`) for prompt follow-up |
| E2S2T1 | Added `src/gherkin_schemas.py` (`GherkinScenario`/`GherkinFeature`) and the `src/gherkin_gen.py` per-item Gherkin generation pipeline with failure isolation and a deterministic `.feature` renderer; locally verified end to end against both `local` and `api` backends |
| E2S3T1 (Approach A) | Added `src/ast_schemas.py` (`DeviceNode`/`SequenceStepNode`/`InterlockNode`/`PLC_AST`) and the `src/ast_gen_A.py` single-call LLM-direct AST generation pipeline with deterministic provenance stamping; verified cross-stage requirement→scenario→AST traceability against both `local` and `api` backends |
| E2S3T1 (Approach B) | Added `src/ast_gen_B.py` deterministic zero-LLM AST generation pipeline using `gherkin-official` parsing and rule-based Dice-coefficient scenario matching; verified 100 % cross-referencing accuracy across both datasets |
| E2S3T1 (Approach C) | Added `src/ast_builders.py` deterministic validated builders and `src/ast_gen_C.py` RPC/function-calling AST generation with equipment/scenario grounding checks; verified API/local compatibility fixes and deterministic `affected_devices` completion against `signal_light_demo` and `sample_control` |
| E2S4T1 | Defined lightweight Pydantic output contracts for Structured Text blocks and Ladder Diagram intermediate networks in `src/plc_code_schemas.py`; generation logic deferred |
| E2S4T2 | Added `src/st_gen.py`, a deterministic `PLC_AST` to Structured Text draft renderer with sanitized variable names, BOOL declarations, sequence `IF` blocks, safety interlock overrides, and traceability comments; verified against `signal_light_demo` and `sample_control` AST outputs |
| E2S4T3 | Added `src/ld_ir_gen.py`, a deterministic `PLC_AST` to LD IR renderer with sanitized variable names, controlled action-to-coil mapping, sequence networks, safety interlock networks, contacts, coils, priority, traceability links, and unsupported-condition notes; verified against `signal_light_demo` and `sample_control` AST outputs |
| E2S4T4 | Added `src/st_gen_llm_direct.py`, a separate `llm_direct` `PLC_AST` to Structured Text draft generator with local/API backend support, Markdown-fence cleanup, basic ST structure validation, and backend-specific output suffixes; generated comparison outputs for `signal_light_demo` and `sample_control` |
| E2S4T5 | Added `src/ld_ir_gen_llm_direct.py`, a separate `llm_direct` `PLC_AST` to LD IR JSON generator with local/API backend support, JSON cleanup/parsing, `LDProgram` validation, light LD structure checks, validation-feedback retries, schema-guided local JSON output, and backend-specific output suffixes; generated API and local comparison outputs for `signal_light_demo` and `sample_control` |
| E2S4T6 | Added `src/st_hybrid_schemas.py` (structured code-intent contracts) and `src/st_gen_hybrid.py`, a hybrid `PLC_AST` to Structured Text generator where the LLM supplies code intent (timers, analogue thresholds, colour states) via function calls and Python renders final ST deterministically (TON blocks, REAL comparisons), with grounding checks and backend-arg normalization; verified on both examples with the `api` and `local` (Gemma 4 E2B) backends, with local runs driving hardening (compact keyed-mapping normalization, colour-state degrade-to-note) plus `tests/test_st_hybrid_gen.py` |
| E2S4T7 | Added `src/ld_ir_gen_hybrid.py`, a hybrid `PLC_AST` to LD IR generator reusing the E2S4T6 intent pipeline; extended `src/plc_code_schemas.py` with optional analogue-contact (`operator`/`threshold`) and timer-network fields; Python renders analogue contacts, timer metadata, and colour/state notes deterministically; verified on both examples with the `api` and `local` (Gemma 4 E2B) backends — local runs confirmed the E2S4T6 hardening applies unchanged (6 unparseable colour-state entries degraded to notes) plus `tests/test_ld_ir_gen_hybrid.py` |

## 📜 Branch History

- **main** (`E1S0T1`, `E1S0T2`, `E1S0T3`, `E1S0T4`): Environments and
  GitHub initialization, initial documentation, root ignore rules, and
  repository scaffold.
- **main** (`E1S2T1`, `E1S2T2`): WSL-to-Windows LM Studio API configuration
  and connectivity test.
- **main** (`E1S3T1`, `E1S3T2`, `E1S3T3`): Docker verification, Weaviate
  Compose configuration, and local API deployment.
- **main** (`E1S4T1`): LlamaIndex Siemens manual ingestion and query pipeline
  over Weaviate and LM Studio.
- **main** (`E1S4T2`): LangChain ingestion and LCEL-based query pipeline over
  Weaviate and LM Studio for LlamaIndex comparison.
- **feature/epic2-agent** (`E2S1`): Pydantic `SystemRequirement` schemas and the
  `src/req_parser.py` natural-language requirement parser with structured JSON
  output, locally verified against `sample_control.txt`.
- **feature/epic2-agent** (`E2S2T1`): Pydantic `GherkinScenario`/`GherkinFeature`
  schemas and the `src/gherkin_gen.py` per-item Gherkin generation pipeline that
  converts parsed `SystemRequirement` JSON into a `.feature` file, locally
  verified against both the `local` and `api` backends.
- **feature/epic2-agent** (`E2S3T1` Approach A): Pydantic
  `DeviceNode`/`SequenceStepNode`/`InterlockNode`/`PLC_AST` schemas and the
  `src/ast_gen_A.py` single-call LLM-direct AST generation pipeline that folds a
  parsed `SystemRequirement` JSON and a Gherkin `.feature` file into a `PLC_AST`
  JSON, establishing the first complete requirement→scenario→AST traceability
  chain, locally verified against both the `local` and `api` backends.
- **feature/epic2-agent** (`E2S3T1` Approach B): `src/ast_gen_B.py` fully
  deterministic, zero-LLM AST generation pipeline using the `gherkin-official`
  library and rule-based Dice-coefficient text matching; verified against both
  datasets with 100 % scenario-cross-referencing accuracy.
- **feature/epic2-agent** (`E2S3T1` Approach C): `src/ast_builders.py` and
  `src/ast_gen_C.py` RPC/function-calling AST generation with backend-specific
  tool-choice handling, Python-owned authoritative fields, deterministic
  `affected_devices`, grounding checks, and validated AST assembly.
- **feature/epic2-agent** (`E2S4T1`): `src/plc_code_schemas.py` schema-only
  output contracts for future IEC 61131-3 Structured Text and Ladder Diagram
  generation.
- **feature/epic2-agent** (`E2S4T2`): `src/st_gen.py` deterministic
  `PLC_AST` to Structured Text draft generation, writing review-required
  `.st` output to `data/plc/st/`.
- **feature/epic2-agent** (`E2S4T3`): `src/ld_ir_gen.py` deterministic
  `PLC_AST` to LD IR JSON generation, writing review-required structured
  outputs to `data/plc/ld/`.
- **feature/epic2-agent** (`E2S4T4`): `src/st_gen_llm_direct.py` separate
  `llm_direct` ST draft generation for local/API backend comparison, writing
  `_st_llm_direct_api.st` and `_st_llm_direct_local.st` outputs.
- **feature/epic2-agent** (`E2S4T5`): `src/ld_ir_gen_llm_direct.py` separate
  `llm_direct` LD IR JSON generation for backend comparison, writing
  `_ld_llm_direct_api.json` and `_ld_llm_direct_local.json` outputs where
  generation completes.
