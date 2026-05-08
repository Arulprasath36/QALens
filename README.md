# QARA — Quality Analysis & Root Automation

> QARA turns static automation test reports into triage-ready intelligence.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

---

## What is QARA?

**QARA (Quality Analysis & Root Automation)** is an open-source Python CLI and library that reads existing automation test HTML reports — such as **Extent Reports** and **Allure Reports** — extracts structured execution data, and generates explainable root-cause insights for QA engineers and development teams.

> QARA stands for Quality Analysis & Root Automation. The project's goal is turning raw automation reports into actionable understanding.

QARA is **not** a test reporting framework. It is an intelligence layer *on top of* your existing reports.

---

## Why QARA?

Modern test suites produce hundreds or thousands of results per run. Tools like Extent Reports and Allure provide excellent visualizations of pass/fail status, logs, screenshots, and stack traces — but they stop there.

**The gaps QARA fills:**

| Problem | What QARA Does |
|---|---|
| Hours spent manually triaging failures | Automates root-cause classification |
| "Is this flaky or a real bug?" | Produces explainable flaky scoring |
| "Is infra to blame or the product?" | Categorizes failures into actionable buckets |
| "We keep seeing the same failure cluster" | Groups failures by normalized signature |
| "What do I tell the engineering lead?" | Generates executive and engineering summaries |

---

## How QARA differs from Extent Reports and Allure

| Feature | Extent / Allure | QARA |
|---|---|---|
| Test execution reporting | ✅ Core purpose | ❌ Not a reporter |
| Pass/fail/skip status | ✅ | ✅ Reads from reports |
| Logs, screenshots, traces | ✅ | ✅ Extracts and indexes |
| Root-cause classification | ❌ | ✅ |
| Flaky detection | ❌ | ✅ |
| Failure clustering | ❌ | ✅ |
| Executive/engineering summary | ❌ | ✅ |
| CI triage automation | Limited | ✅ |
| Local, no cloud required | ✅ | ✅ |
| Plugin-extensible analysis | ❌ | ✅ |

---

## v1 Scope

**Supported report formats:**
- Extent Report HTML (v4, v5)
- Allure Report HTML (v2)

**Insight categories produced:**

| Category | What it means |
|---|---|
| `likely_flaky` | Intermittent failure, passes on retry, timing-dependent |
| `likely_environment_issue` | Grid/browser/DNS/auth infra failure affecting setup |
| `likely_test_script_issue` | Stale locator, bad selector, test harness error |
| `likely_product_defect` | Stable, reproducible business-assertion failure |
| `likely_test_data_issue` | Missing entity, duplicate key, invalid data state |
| `unknown` | Insufficient signals for confident classification |

**Outputs produced:**
- Normalized JSON (canonical internal representation)
- Markdown summary report
- Failure cluster report
- Console-formatted triage summary

**v1 non-goals:**
- No SaaS backend or cloud connectivity
- No deep-learning models
- No hosted dashboard
- No replacement of Extent or Allure

---

## Local Setup And Run Guide

This section is for someone setting up QARA from this repository on a local
machine.

### 1. Prerequisites

Install:

- Python 3.10 or newer
- Node.js 18 or newer, only needed for frontend development or building from source
- npm, bundled with Node.js
- Git

If you use `nvm`, the frontend includes an `.nvmrc`:

```bash
cd frontend
nvm use
cd ..
```

### 2. Clone The Repository

```bash
git clone https://github.com/Arulprasath36/QARA.git
cd QARA
```

### 3. Create A Python Virtual Environment

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### 4. Install QARA For Local Development

```bash
pip install -e ".[dev]"
```

This installs the Python package in editable mode and registers the `qara`
command.

Verify:

```bash
qara --help
qara --version
```

### 5. Install Frontend Dependencies

The packaged Python wheel ships with built frontend assets, but source
development requires installing frontend dependencies:

```bash
cd frontend
npm ci
cd ..
```

### 6. Verify The Local Setup

Backend tests:

```bash
pytest
```

Frontend checks:

```bash
cd frontend
npm run typecheck
npm test
npm run build
cd ..
```

Useful full build command from the repo root:

```bash
make build-ui
```

`make build-ui` compiles the React app into `src/qara/server/static/`, which is
what `qara serve` uses when serving the built UI from Python.

### 7. Try QARA With Sample Reports

The repo includes parser fixtures under `tests/fixtures/`.

Detect a report format:

```bash
qara detect tests/fixtures/allure_sample
qara detect tests/fixtures/extent_sample
```

Extract normalized JSON:

```bash
qara extract tests/fixtures/allure_sample --out extracted.json
```

Ingest a report into the local SQLite database:

```bash
qara ingest tests/fixtures/allure_sample
```

The sample Allure fixture may print a warning about a missing screenshot
attachment. That is expected for this fixture and does not block ingestion.

By default QARA stores data in `~/.qara/qara.db`. You can use a project-local
database instead:

```bash
qara ingest tests/fixtures/allure_sample --db ./qara.db
```

Analyze ingested runs:

```bash
qara analyze --db ./qara.db
```

Generate a one-off summary directly from a report:

```bash
qara summarize tests/fixtures/allure_sample --format markdown --out summary.md
```

View failure clusters directly from a report:

```bash
qara clusters tests/fixtures/allure_sample
```

### 8. Demo Dataset: ShopNow E-Commerce

For a richer demo, the repo includes a synthetic 50-run Allure-style dataset:

```text
tmp_test_data/ShopNow_E-Commerce/
```

Each `run_###/` folder is a separate report run. The SQLite files in that
folder are intentionally ignored; recreate the database locally by ingesting
the report folders.

Create a demo database:

```bash
rm -f ./shopnow-demo.db
for report in tmp_test_data/ShopNow_E-Commerce/run_*; do
  qara ingest "$report" --db ./shopnow-demo.db
done
```

Analyze the full run history:

```bash
qara analyze --db ./shopnow-demo.db
```

Open the demo in the web UI:

```bash
qara serve --db ./shopnow-demo.db
```

### 9. Run The Web UI

First ingest at least one report:

```bash
qara ingest tests/fixtures/allure_sample --db ./qara.db
```

Then start the local server:

```bash
qara serve --db ./qara.db
```

The UI runs at:

```text
http://127.0.0.1:8080
```

For frontend development, run the Python API server and Vite dev server in two
terminals.

Terminal 1:

```bash
qara serve --db ./qara.db --no-open
```

Terminal 2:

```bash
cd frontend
npm run dev
```

Open:

```text
http://localhost:3000
```

The Vite dev server proxies `/api/*` requests to `http://localhost:8080`.

### 10. Optional LLM Setup

QARA works without an LLM for ingestion, parsing, summaries, and deterministic
analysis. LLM-powered chat uses `~/.qara/config.toml`.

Create the default config:

```bash
qara llm-config --init
qara llm-config --show
```

The default provider is local Ollama. Cloud providers require an explicit
opt-in because report data may include test names, stack traces, hostnames, and
other sensitive details:

```toml
[llm]
provider = "openai"
allow_external = true
```

You can also set:

```bash
export QARA_ALLOW_EXTERNAL_LLM=1
```

Ask a question after ingesting runs:

```bash
qara ask "What broke in the latest run?" --db ./qara.db
```

### 11. Common Local Commands

| Task | Command |
|---|---|
| Install Python package | `pip install -e ".[dev]"` |
| Install frontend deps | `cd frontend && npm ci` |
| Run backend tests | `pytest` |
| Run frontend tests | `cd frontend && npm test` |
| Type-check frontend | `cd frontend && npm run typecheck` |
| Build frontend assets | `make build-ui` |
| Serve local UI | `qara serve --db ./qara.db` |
| Serve ShopNow demo | `qara serve --db ./shopnow-demo.db` |
| Build package | `make build` |

---

## Example CLI Output

```
QARA — Quality Analysis & Root Automation
====================================
Report:   allure-report/  [allure]
Run date: 2026-03-06T08:14:33Z
Tests:    312  |  Passed: 241  |  Failed: 58  |  Skipped: 13

Failure Summary
---------------
  likely_flaky             18  (31%)
  likely_environment_issue  9  (16%)
  likely_test_script_issue 11  (19%)
  likely_product_defect    14  (24%)
  likely_test_data_issue    4   (7%)
  unknown                   2   (3%)

Top Failure Clusters
--------------------
  [CLUSTER-1] NullPointerException in CheckoutService  (12 tests)
  [CLUSTER-2] WebDriverException: session not created  (9 tests)
  [CLUSTER-3] AssertionError: expected status 200, got 503  (7 tests)

Recommended Actions
-------------------
  → 14 product defects require developer triage (CLUSTER-1, CLUSTER-3)
  → 9 environment failures suggest grid/infra investigation
  → 18 flaky tests are candidates for retry-policy review
```

---

## Design Principles

- **Local-first** — No network calls, no API keys, no telemetry.
- **Explainable over magical** — Every insight includes category, confidence, explanation, and evidence.
- **Normalize first, analyze second** — Parsers are strictly decoupled from analyzers.
- **Plugin-extensible** — Add custom parsers, rules, or output writers without forking.
- **Production-quality** — Typed, tested, documented, and maintainable.

## Security Defaults

QARA treats reports as untrusted input. Ingestion validates supported report
file types, bounds screenshot bytes, rejects SVG artifacts, validates raster
images by magic bytes, and redacts common secrets before report-derived text is
sent to an LLM.

LLM features default to local providers. Cloud providers require an explicit
opt-in with `allow_external = true` in the QARA LLM config or
`QARA_ALLOW_EXTERNAL_LLM=1`.

For networked deployments, review [SECURITY.md](SECURITY.md) and
[PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md). `qara serve` has no built-in
authentication and should be exposed only behind an authenticated reverse proxy.

---

## Using QARA as a Python Library

```python
from qara.api.library import QARAClient

client = QARAClient()

# Detect report type
report_type = client.detect_report("./reports/allure-report")

# Extract normalized run
run = client.extract_report("./reports/allure-report")

# Analyze failures
analysis = client.analyze_report(run)

# Generate summary
summary = client.summarize_report(analysis, fmt="markdown")
print(summary)
```

---

## Artifact Ingestion

QARA can capture screenshot artifacts from test reports at three levels of detail, controlled by the `--artifact-mode` flag when running `qara ingest`.

QARA is **text-first**. Screenshots are optional supporting evidence. The default mode stores only metadata — no image bytes — keeping the database small and portable.

### The 3 Modes

| Mode | DB records written | Image bytes stored | Summary |
|---|---|---|---|
| `text-only` | None | No | Ingest all textual failure data (name, status, error, stack trace, logs, step names). Artifact references detected during parsing are discarded. |
| `metadata-only` *(default)* | Yes | No | Everything in `text-only` **plus** a lightweight `artifacts` row per selected screenshot: SHA-256 hash, MIME type, file size, image dimensions (parsed from header without Pillow), step name, sequence number, `is_primary` flag. Safe for all environments. |
| `full` | Yes | Yes | Everything in `metadata-only` **plus** image bytes written to the configured artifact store directory. Optional compression/resizing (requires Pillow) and SHA-256 deduplication are applied before storage. |

### Defaults

| Option | Default |
|---|---|
| `--artifact-mode` | `metadata-only` |
| `--max-screenshots-per-failure` | `2` |
| `--compress-images` | `true` (requires Pillow; silently skipped if absent) |
| `--max-image-width` | `1600 px` |
| `--jpeg-quality` | `80` |
| `--generate-thumbnails` | `false` (reserved) |
| `--dedupe-images` | `true` |

### Screenshot selection (when cap > available)

When a failed test has more screenshots than the cap allows, QARA applies a priority ranking before truncation:

1. Screenshots from **failed or broken steps** (`is_from_failed_step=True`) — most likely to show the root cause.
2. Screenshots with the **highest sequence number** among the remainder — nearest to the exception.
3. First and last screenshot as a last-resort fallback.

### Screenshot sources in Extent Reports

QARA extracts screenshots from three locations in an Extent HTML report:

| Source | Description |
|---|---|
| Test-level `details` | Embedded `data:image/...;base64,...` URIs from `addScreenCaptureFromBase64String()` at the test level. |
| Step-level `details` | Embedded screenshots attached to individual test steps. These carry `step_name` and are marked `is_from_failed_step=true` when the step failed. Step-level refs are given higher sequence numbers so they are preferred by the priority selector. |
| Test-level `media` | File-path references (relative to report root) or embedded data URIs in the `media` array. Resolved against the report directory at parse time. |

### CLI flags

```
--artifact-mode [text-only|metadata-only|full]
                          Artifact ingestion tier  [default: metadata-only]
--max-screenshots-per-failure INT
                          Hard cap on screenshots per failed test  [default: 2]
--compress-images / --no-compress-images
                          Resize & re-encode images before storage (requires Pillow)  [default: compress]
--max-image-width INT     Maximum image width in pixels after resizing  [default: 1600]
--jpeg-quality INT        JPEG/WebP quality 1–95  [default: 80]
--dedupe-images / --no-dedupe-images
                          Skip storing identical images (SHA-256 match)  [default: dedupe]
--artifact-storage-dir PATH
                          Directory for stored image files (full mode only;
                          defaults to a sibling 'artifacts/' folder next to the DB)
```

### Quick start

```bash
# Default: metadata-only — stores hashes and dimensions, no image bytes
qara ingest ./my-extent-report

# Text-only — fastest, smallest DB, no artifact records
qara ingest ./my-extent-report --artifact-mode text-only

# Capture metadata only (explicit)
qara ingest ./my-extent-report --artifact-mode metadata-only

# Store full image bytes with compression (requires Pillow)
qara ingest ./my-extent-report \
  --artifact-mode full \
  --artifact-storage-dir ~/.qara/artifacts \
  --max-screenshots-per-failure 3 \
  --jpeg-quality 75
```

### End-of-run ingestion summary

After every `qara ingest`, QARA prints an artifact summary:

```
Artifact ingestion  (mode: metadata-only)
  Screenshot refs found    : 14
  Selected after cap       : 8
  Artifact records created : 8
  Skipped (bad/missing)    : 1
```

In `full` mode the summary also reports images stored and duplicates skipped.

### Storage note

Image bytes are **never stored in the SQLite database**. The `artifacts` table holds metadata and a `file://` URI pointing to the artifact store directory. This keeps the database small and query-fast while still allowing analysis layers to reference screenshots by their stable SHA-256 content hash. S3/MinIO backends can be added by implementing the `ArtifactStore` interface in `src/qara/artifacts/storage.py`.

---

## Repository Structure

Top-level layout:

```
QARA/
├── src/qara/                 # Python package
├── frontend/                 # React + Vite web UI
├── tests/                    # Python test suite and parser fixtures
├── docs/                     # Design and architecture notes
├── examples/                 # Example normalized data and CI snippets
├── scripts/                  # Local helper scripts for data generation/seeding
├── .github/workflows/        # GitHub Actions CI
├── Makefile                  # Build shortcuts
├── pyproject.toml            # Python package, tooling, and test config
├── hatch_build.py            # Builds frontend assets during package builds
├── SECURITY.md               # Security policy and controls
└── PRODUCTION_CHECKLIST.md   # Networked-deployment checklist
```

Python package layout:

```
src/qara/
├── api/          # Public Python API; QARAClient lives here
├── analyzers/    # Categorization, flaky scoring, clustering, comparison, prediction
├── artifacts/    # Screenshot/artifact policy, image inspection, storage
├── cli/          # Active Typer CLI package for the `qara` command
├── cli.py        # Legacy monolithic CLI kept during CLI migration work
├── db/           # SQLite schema, repository layer, row models
├── llm/          # LLM config, prompt builders, routing, context gathering, client
├── models/       # Canonical Pydantic/domain models for runs, tests, failures
├── parsers/      # Allure and Extent report detection/parsing
├── security.py   # Shared security constants, validation, redaction helpers
├── server/       # FastAPI app, API routes, packaged static UI assets
└── utils/        # Filesystem and text helpers
```

Frontend layout:

```
frontend/
├── src/App.tsx
├── src/main.tsx
├── src/components/           # Shared UI components
├── src/hooks/                # Shared React hooks
├── src/panels/               # Main dashboard panels and chat panel
├── src/panels/chat/          # Chat result workspace, types, markdown sanitizer
├── src/compare-engine/       # Run comparison feature area
├── public/                   # Icons, manifest, static public assets
├── package.json              # Frontend scripts and dependencies
└── vite.config.ts            # Vite build/dev-server config
```

Tests and fixtures:

```
tests/
├── fixtures/allure_sample/   # Sample Allure report fixture
├── fixtures/extent_sample/   # Sample Extent report fixture
└── test_*                    # Backend, parser, analyzer, server, security tests
```

Demo data:

```
tmp_test_data/
└── ShopNow_E-Commerce/       # Synthetic 50-run Allure-style demo dataset
    ├── run_001/
    ├── run_002/
    └── ...
```

Build outputs and local files:

- `src/qara/server/static/` is generated by `npm run build` or `make build-ui`.
- `node_modules/`, `.venv/`, caches, local databases, local reports, and generated
  artifacts are intentionally ignored by git.
- The default local database is `~/.qara/qara.db`.

See [docs/architecture.md](docs/architecture.md) for the deeper system design.

---

## Contributing

Contributions are warmly welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

We especially welcome:
- Additional report format parsers (TestNG, JUnit XML, pytest-html, etc.)
- New heuristic categorization rules
- Improved flaky detection signals
- Documentation and examples

---

## License

[Apache 2.0](LICENSE) — free to use, modify, and distribute.

---

*Built with care for the QA and engineering community.*
