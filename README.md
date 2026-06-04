# AutoPLC Agent

AutoPLC Agent is a GenAI agent platform intended to bridge Information
Technology (IT) and Operational Technology (OT) workflows. The project aims to
turn natural-language control requirements into structured, reviewable
artifacts and ultimately generate IEC 61131-3 PLC programs.

> **Project status:** `E1S2 - [Phase 2] Connection of the API from Windows to
> WSL` is complete. WSL can connect to the Windows-hosted LM Studio
> OpenAI-compatible API, but the core agent pipeline has not yet been
> implemented.

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

The intended platform uses large language models (LLMs) to:

1. Interpret natural-language automation requirements.
2. Express expected behavior as BDD scenarios using Gherkin syntax.
3. Convert validated scenarios into a structured AST/JSON intermediate
   representation.
4. Generate standard IEC 61131-3 code, initially Structured Text (ST) and
   Ladder Diagram (LD).
5. Export interoperable PLCopen XML for downstream engineering tools.

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
- **PLCopen XML export** for exchanging generated program structures with
  compatible PLC engineering environments.
- **Validation-oriented workflow** that keeps generated artifacts inspectable
  and supports future linting, simulation, and human approval gates.
- **Notebook workspace** for experimentation, prompt evaluation, and prototype
  development.
- **Local LM Studio connectivity test** that discovers the Windows host from
  the WSL default gateway and verifies an OpenAI-compatible chat completion.

## 🧭 Workflow and Architecture

The planned artifact pipeline is:

```text
Natural-Language Requirement
            |
            v
    BDD / Gherkin Scenarios
            |
            v
      AST / JSON Model
            |
            +------------------+
            |                  |
            v                  v
 IEC 61131-3 ST / LD      PLCopen XML
            |                  |
            +--------+---------+
                     v
          Engineer Review and Validation
```

The AST/JSON representation is the central contract in this design. It should
allow each generated output to be traced back to an explicit requirement and
make it possible to add deterministic validation around LLM-generated content.

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or newer
- `pip` and Python virtual environment support
- WSL2 Ubuntu with the `ip` command available
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

Root `.env` files are ignored by Git, but the project does not currently load
them automatically.

### Verify LM Studio Connectivity

Start the LM Studio local server on Windows, load a model, then run:

```bash
source venv/bin/activate
python src/test_llm.py
```

The script lists available models, selects the first loaded model, requests a
brief IEC 61131-3 Structured Text hello-world example, and prints the response.

## 📦 Project Structure

```text
AutoPLC-Agent/
├── .agents/          # Local agent configuration
├── .codex/           # Local Codex configuration
├── data/             # Local or generated datasets and artifacts (Git-ignored)
├── notebooks/        # Experiments, evaluations, and prototypes
├── src/
│   └── test_llm.py   # WSL-to-LM Studio API connectivity test
├── .gitignore        # Repository ignore rules
├── JIRA_KANBAN.md    # Jira-style Epic, Story, and Task tracker
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
| AI integration | OpenAI Python SDK v1.x | In use |
| WSL networking | Dynamic default gateway discovery | Implemented |
| Requirements format | BDD / Gherkin syntax | Planned |
| Intermediate representation | AST / JSON | Planned |
| PLC languages | IEC 61131-3 Structured Text and Ladder Diagram | Planned |
| Interchange format | PLCopen XML | Planned |
| Experimentation | Jupyter notebooks | Planned |

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
- [x] **E1S1T2 - Identify and pull appropriate local LLM models for testing
  natural language understanding**

#### E1S2: [Phase 2] Connection of the API from Windows to WSL

- [x] **E1S2T1 - Configure WSL network settings to access the Windows host LM
  Studio API server**
- [x] **E1S2T2 - Create a test script to verify API connectivity from within
  WSL**

## 👥 Contributors

| Task ID | Contribution |
| --- | --- |
| E1S0T2 | Created the initial project overview, feature, workflow, setup, structure, and technology stack documentation |
| E1S0T3 | Added repository hygiene documentation for virtual environments, Python caches, `.env` files, and local `data/` |
| E1S2T1 | Installed the OpenAI SDK in the project venv and established dynamic WSL-to-Windows LM Studio addressing |
| E1S2T2 | Added and verified `src/test_llm.py` for LM Studio chat completion connectivity |

## 📜 Branch History

- **main** (`E1S0T1`, `E1S0T2`, `E1S0T3`, `E1S0T4`): Environments and
  GitHub initialization, initial documentation, root ignore rules, and
  repository scaffold.
- **main** (`E1S2T1`, `E1S2T2`): WSL-to-Windows LM Studio API configuration
  and connectivity test.
