# AutoPLC Agent

AutoPLC Agent is a GenAI agent platform intended to bridge Information
Technology (IT) and Operational Technology (OT) workflows. The project aims to
turn natural-language control requirements into structured, reviewable
artifacts and ultimately generate IEC 61131-3 PLC programs.

> **Project status:** `E1S0 - [Step 0] Environments and GitHub Initialization`
> is complete. The architecture and delivery roadmap are documented here, but
> the agent pipeline has not yet been implemented.

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
- An LLM provider API key once model integration is implemented

### Local Setup

```bash
git clone <repository-url>
cd AutoPLC-Agent

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

`requirements.txt` is currently empty because application dependencies have not
yet been selected.

### Environment Variables

Store local credentials in a root `.env` file. `.env` files are ignored by
Git; commit only a sanitized `.env.example` when configuration variables are
introduced.

Example future configuration:

```dotenv
LLM_PROVIDER=
LLM_API_KEY=
LLM_MODEL=
```

### Running the Project

There is no application entry point yet. Add the run command here when the
first executable agent workflow is implemented.

## 📦 Project Structure

```text
AutoPLC-Agent/
├── .agents/          # Local agent configuration
├── .codex/           # Local Codex configuration
├── data/             # Local or generated datasets and artifacts (Git-ignored)
├── notebooks/        # Experiments, evaluations, and prototypes
├── src/              # Application source code
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
| Runtime | Python 3.10+ | Planned |
| AI integration | LLM provider API | To be selected |
| Requirements format | BDD / Gherkin syntax | Planned |
| Intermediate representation | AST / JSON | Planned |
| PLC languages | IEC 61131-3 Structured Text and Ladder Diagram | Planned |
| Interchange format | PLCopen XML | Planned |
| Experimentation | Jupyter notebooks | Planned |

No third-party runtime libraries are currently declared.

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

Task titles and status are maintained in `JIRA_KANBAN.md`.

### EPIC-1: Infrastructure & Environment Setup

#### E1S0: [Step 0] Environments and GitHub Initialization

- [x] **E1S0T1 - Environments and GitHub Initialization**
- [x] **E1S0T2 - Create the initial repository documentation**
- [x] **E1S0T3 - Add root ignore rules**
- [x] **E1S0T4 - Initial Repository Scaffold**

## 👥 Contributors

| Task ID | Contribution |
| --- | --- |
| E1S0T2 | Created the initial project overview, feature, workflow, setup, structure, and technology stack documentation |
| E1S0T3 | Added repository hygiene documentation for virtual environments, Python caches, `.env` files, and local `data/` |

## 📜 Branch History

- **main** (`E1S0T1`, `E1S0T2`, `E1S0T3`, `E1S0T4`): Environments and
  GitHub initialization, initial documentation, root ignore rules, and
  repository scaffold.
