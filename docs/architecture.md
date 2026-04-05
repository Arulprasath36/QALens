# QARA Architecture

> QARA — Quality Analysis & Root Automation  
> "Qara" is named after the Tamil word "Ari" (அறி), meaning "know".

---

## Overview

QARA is structured as a **pipeline** with clearly separated concerns:

```
Report on disk
     │
     ▼
┌─────────────┐
│  Detection  │  (parsers/detector.py)
│             │  Identifies report type from file/folder signatures
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Parser    │  (parsers/extent.py | parsers/allure.py)
│             │  Extracts raw data → Canonical models
└──────┬──────┘
       │  models.TestRun (normalized)
       ▼
┌─────────────┐
│  Analyzers  │  (analyzers/)
│             │  Signatures → Categorization → Clustering → Flaky → Summary
└──────┬──────┘
       │  models.AnalysisSummary
       ▼
┌─────────────┐
│   Outputs   │  (outputs/)
│             │  JSON │ Markdown │ Console
└─────────────┘
```

---

## Key Design Decisions

### 1. Normalize First, Analyze Second

Parsers **only extract**. They produce a `TestRun` Canonical model and stop.  
Analyzers **only analyze**. They receive a `TestRun` and produce `AnalysisSummary`.  
These concerns are strictly separated so that:

- A new parser does not require changes to any analyzer.
- Analyzers are testable against hand-crafted `TestRun` objects.
- The same analyzers work across all report formats.

### 2. Explainability is Non-Negotiable

Every `Insight` must include:
- `category` — the classification
- `confidence` — a float in [0, 1]
- `explanation` — a human-readable reason
- `evidence` — a list of concrete signals that drove the classification

There are no black-box verdicts.

### 3. Local-First

QARA makes no network calls. It reads from the local filesystem only. This is a design constraint, not an omission.

### 4. Plugin Architecture

Each major layer has a defined abstract base or protocol:
- `BaseParser` — for custom report parsers
- Categorization rules — additive, pluggable functions
- Output writers — implement `BaseWriter`

---

## Module Map

### `src/qara/parsers/`

| Module | Responsibility |
|--------|---------------|
| `base.py` | `BaseParser` abstract class / Protocol |
| `detector.py` | Identifies report type from path |
| `extent.py` | Extracts data from Extent HTML reports |
| `allure.py` | Extracts data from Allure HTML reports |

### `src/qara/models/`

| Module | Key Types |
|--------|-----------|
| `run.py` | `TestRun`, `RunMetadata` |
| `test_case.py` | `TestCaseResult`, `StepResult` |
| `failure.py` | `FailureInfo` |
| `insight.py` | `Insight`, `FailureCluster`, `AnalysisSummary` |
| `attachment.py` | `Attachment` |
| `warnings.py` | `ExtractionWarning` |

### `src/qara/analyzers/`

| Module | Responsibility |
|--------|---------------|
| `signatures.py` | Stack trace normalization, signature generation |
| `categorizer.py` | Rule-based failure categorization |
| `clustering.py` | Deterministic + optional fuzzy failure grouping |
| `flaky.py` | Flaky scoring with historical context |
| `summarizer.py` | Executive / engineering / QA summaries |

### `src/qara/outputs/`

| Module | Responsibility |
|--------|---------------|
| `json_writer.py` | Writes normalized JSON |
| `markdown_writer.py` | Writes Markdown summary |
| `console_writer.py` | Rich-formatted console output |

### `src/qara/utils/`

| Module | Responsibility |
|--------|---------------|
| `fs.py` | File system helpers (find, resolve, walk) |
| `text.py` | Text cleaning and regex utilities |
| `hashing.py` | Stable hash/fingerprint generation |

### `src/qara/api/`

| Module | Responsibility |
|--------|---------------|
| `library.py` | Public Python API: `QARAClient` |

---

## Data Flow in Detail

```
Parser
  → extracts raw HTML/JSON
  → builds TestCaseResult objects for each test
  → attaches StepResult, FailureInfo, Attachment lists
  → emits ExtractionWarning for missing/malformed fields
  → wraps everything in TestRun

Analyzers (sequential pipeline)
  1. SignatureEngine
       → for each failed TestCaseResult, normalize the stack trace
       → generate a stable failure_signature
  2. Categorizer
       → evaluate each failure against heuristic rules
       → assign Insight(category, confidence, explanation, evidence)
  3. ClusterEngine
       → group failures by signature (deterministic)
       → optionally refine with TF-IDF proximity
       → produce FailureCluster list
  4. FlakyScorer
       → compare with historical runs if available
       → compute flaky_score per test
  5. Summarizer
       → aggregate statistics
       → produce AnalysisSummary

Outputs
  → consume AnalysisSummary + TestRun
  → write JSON, Markdown, or formatted console
```

---

## Extension Points

See [plugin-guide.md](plugin-guide.md) for details on:
- Adding a parser for a new report format
- Adding custom categorization rules
- Adding a custom output writer
- Adding an optional ML enricher (future)

---

## Dependency Graph

```
cli.py          → api/library.py
api/library.py  → parsers/ + analyzers/ + outputs/
parsers/        → models/ + utils/
analyzers/      → models/ + utils/
outputs/        → models/
models/         → pydantic (external)
```

No circular dependencies are permitted. `models/` must not import from `parsers/`, `analyzers/`, or `outputs/`.
