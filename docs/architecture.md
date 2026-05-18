# QaLens Architecture

> QaLens — Quality Assurance + Lens

---

## Overview

QaLens is structured as a **pipeline** with clearly separated concerns:

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
│   Parser    │  (parsers/)
│             │  Extent, Allure, JUnit, TestNG, Playwright, Cypress
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
│  Database   │  (db/)
│             │  SQLite via schema.py — runs, tests, failures, artifacts
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Server    │  (server/)
│             │  FastAPI — REST API + packaged React UI
└─────────────┘
```

CLI outputs (JSON, Markdown, console) are produced directly from `AnalysisSummary`
without going through the database, for one-shot commands like `qalens summarize`
and `qalens clusters`.

---

## Key Design Decisions

### 1. Normalize First, Analyze Second

Parsers **only extract**. They produce a `TestRun` canonical model and stop.
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

### 3. Local-First, Opt-In External

Core analysis, ingestion, and the web UI run entirely on the local machine with
no telemetry. External network calls are opt-in only:
- **GitHub OAuth** — optional team authentication (`QALENS_AUTH_MODE=github`)
- **Cloud LLM providers** — require explicit `allow_external = true` in config

### 4. Plugin Architecture

Each major layer has a defined abstract base or protocol:
- `BaseParser` — for custom report parsers
- Categorization rules — additive, pluggable functions
- Output writers — implement `BaseWriter`

---

## Module Map

### `src/qalens/parsers/`

| Module | Responsibility |
|--------|---------------|
| `detector.py` | Identifies report type from path/file signatures |
| `extent.py` | Extracts data from Extent HTML reports (v4, v5) |
| `allure.py` | Extracts data from Allure HTML reports (v2) |
| `junit.py` | Parses JUnit-compatible XML (`testsuite` / `testsuites`) |
| `testng.py` | Parses TestNG XML (`testng-results.xml`) |
| `playwright.py` | Parses Playwright JSON reports and JSON-backed HTML folders |
| `cypress.py` | Parses Cypress/Mocha JSON and Mochawesome-style output |

### `src/qalens/models/`

| Module | Key Types |
|--------|-----------|
| `run.py` | `TestRun`, `RunMetadata` |
| `test_case.py` | `TestCaseResult`, `StepResult` |
| `failure.py` | `FailureInfo` |
| `insight.py` | `Insight`, `FailureCluster`, `AnalysisSummary` |
| `attachment.py` | `Attachment` |
| `warnings.py` | `ExtractionWarning` |

### `src/qalens/analyzers/`

| Module | Responsibility |
|--------|---------------|
| `signatures.py` | Stack trace normalization, signature generation |
| `categorizer.py` | Rule-based failure categorization |
| `clustering.py` | Deterministic + optional fuzzy failure grouping |
| `flaky.py` | Flaky scoring with historical context |
| `summarizer.py` | Executive / engineering / QA summaries |
| `incidents.py` | Cross-run incident tracking and trend detection |

### `src/qalens/db/`

| Module | Responsibility |
|--------|---------------|
| `schema.py` | SQLite schema, table definitions, default DB path |

### `src/qalens/artifacts/`

| Module | Responsibility |
|--------|---------------|
| `config.py` | Artifact ingestion policy (mode, caps, compression settings) |
| `storage.py` | Image byte storage, SHA-256 deduplication, `ArtifactStore` interface |

### `src/qalens/llm/`

| Module | Responsibility |
|--------|---------------|
| `config.py` | LLM provider config, `config.toml` load/save, provider defaults |
| `prompts.py` | Prompt builders for each LLM feature |
| `client.py` | LLM routing and provider client abstraction |
| `deterministic_answers.py` | Rule-based answers that bypass the LLM |

### `src/qalens/server/`

| Module | Responsibility |
|--------|---------------|
| `app.py` | FastAPI app factory, middleware (CSP, auth), health + auth endpoints |
| `auth.py` | Auth modes (none / token / GitHub OAuth), session signing, admin access |
| `routes_runs.py` | Run listing, test results, failure detail |
| `routes_analysis.py` | Failure categorization and cluster API |
| `routes_evidence.py` | Screenshot and artifact evidence API |
| `routes_llm.py` | LLM-powered chat and question-answering |
| `routes_compare.py` | Run comparison and history API |
| `routes_settings.py` | Runtime settings read/write (admin only) |
| `routes_report.py` | Shareable HTML/Markdown/JSON report export |
| `static/` | Compiled React + Vite frontend assets |

### `src/qalens/reports/`

| Module | Responsibility |
|--------|---------------|
| Report generators | Produce standalone HTML, Markdown, and JSON exports |

### `src/qalens/ownership.py`

Owner mapping — resolves test/suite/feature/tag patterns to team names from
a `owners.toml` file provided at ingestion time.

### `src/qalens/api/`

| Module | Responsibility |
|--------|---------------|
| `library.py` | Public Python API: `QaLensClient` |

### `src/qalens/utils/`

| Module | Responsibility |
|--------|---------------|
| `fs.py` | File system helpers (find, resolve, walk) |
| `text.py` | Text cleaning and regex utilities |
| `hashing.py` | Stable hash/fingerprint generation |

---

## Authentication

QaLens supports three auth modes configured via environment variables:

| Mode | Env vars | How it works |
|------|----------|-------------|
| `none` | — | No login required; intended for localhost |
| `token` | `QALENS_AUTH_TOKEN` | Bearer token sent in `Authorization` header; stored in browser session storage |
| `github` | `QALENS_AUTH_MODE`, `QALENS_GITHUB_CLIENT_ID`, `QALENS_GITHUB_CLIENT_SECRET`, `QALENS_SESSION_SECRET` | GitHub OAuth flow; session signed with HMAC-SHA256 and stored in an HttpOnly cookie |

Admin access to the Settings panel is controlled separately by
`QALENS_ADMIN_GITHUB_USERS`. OAuth state is stored server-side (in-process dict
with 10-minute TTL) to avoid cookie-domain mismatches in local development.

---

## Data Flow in Detail

```
Parser
  → extracts raw HTML/JSON/XML
  → builds TestCaseResult objects for each test
  → attaches StepResult, FailureInfo, Attachment lists
  → emits ExtractionWarning for missing/malformed fields
  → wraps everything in TestRun

Analyzers (sequential pipeline)
  1. SignatureEngine
       → normalize stack traces per failed TestCaseResult
       → generate a stable failure_signature
  2. Categorizer
       → evaluate each failure against heuristic rules
       → assign Insight(category, confidence, explanation, evidence)
  3. ClusterEngine
       → group failures by signature (deterministic)
       → optionally refine with TF-IDF proximity
       → produce FailureCluster list
  4. FlakyScorer
       → compare with historical runs from the DB
       → compute flaky_score per test
  5. Summarizer
       → aggregate statistics
       → produce AnalysisSummary

Persistence (qalens ingest)
  → AnalysisSummary + TestRun written to SQLite via db/schema.py
  → Screenshot artifacts stored separately (metadata-only by default)

Server (qalens serve)
  → FastAPI reads from SQLite on each API request
  → React frontend communicates exclusively via /api/* endpoints
  → Auth middleware validates every request before it reaches a route handler
```

---

## Extension Points

See [plugin-guide.md](plugin-guide.md) for details on:
- Adding a parser for a new report format
- Adding custom categorization rules
- Adding a custom output writer

---

## Dependency Graph

```
cli/            → api/library.py + db/ + server/
api/library.py  → parsers/ + analyzers/ + outputs/
server/         → db/ + auth + llm/ + reports/ + ownership
parsers/        → models/ + utils/
analyzers/      → models/ + utils/
outputs/        → models/
llm/            → db/ + security
models/         → pydantic (external)
```

No circular dependencies are permitted. `models/` must not import from
`parsers/`, `analyzers/`, or `outputs/`.
