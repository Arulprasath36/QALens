# QaLens — Quality Assurance + Lens

> QaLens turns static automation test reports into triage-ready intelligence.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

---

## What is QaLens?

**QaLens (Quality Assurance + Lens)** is an open-source Python CLI and library that reads existing automation test HTML reports — such as **Extent Reports** and **Allure Reports** — extracts structured execution data, and generates explainable root-cause insights for QA engineers and development teams.

> QaLens stands for Quality Assurance + Lens. The project's goal is turning raw automation reports into actionable understanding.

QaLens is **not** a test reporting framework. It is an intelligence layer *on top of* your existing reports.

---

## Why QaLens?

Modern test suites produce hundreds or thousands of results per run. Tools like Extent Reports and Allure provide excellent visualizations of pass/fail status, logs, screenshots, and stack traces — but they stop there.

**The gaps QaLens fills:**

| Problem | What QaLens Does |
|---|---|
| Hours spent manually triaging failures | Automates root-cause classification |
| "Is this flaky or a real bug?" | Produces explainable flaky scoring |
| "Is infra to blame or the product?" | Categorizes failures into actionable buckets |
| "We keep seeing the same failure cluster" | Groups failures by normalized signature |
| "What do I tell the engineering lead?" | Generates executive and engineering summaries |

---

## How QaLens differs from Extent Reports and Allure

| Feature | Extent / Allure | QaLens |
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
- JUnit-compatible XML (`testsuite` / `testsuites`)
- TestNG XML (`testng-results.xml`)
- Playwright JSON reports and JSON-backed HTML report folders
- Cypress/Mocha JSON reports, including Mochawesome-style output

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
- Decision-first web dashboard with Runs, Incidents, Analysis, Risk, Compare, Chat, and Settings views
- Deterministic shareable HTML/Markdown/JSON reports

**Web UI highlights:**

| View | What it helps answer |
|---|---|
| Runs | What changed in the latest run, what should be fixed first, and which failures need inspection |
| Incidents | Which shared failure signatures are recurring, new, worsening, persisting, or recovering |
| Analysis | Whether suite health is improving or declining across the selected run window |
| Risk | Which tests are most likely to fail or flip in the next run, with explainable risk signals |
| Compare | How runs, owners, modules, or suites differ across a selected window |
| Chat | Ask evidence-backed questions over ingested QaLens data; LLM features are optional |
| Settings | Inspect runtime paths, database status, auth mode, and safe LLM configuration |

---

## Local Setup And Run Guide

This section is for someone setting up QaLens from this repository on a local
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
git clone https://github.com/Arulprasath36/QaLens.git
cd QaLens
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

### 4. Install QaLens For Local Development

```bash
pip install -e ".[dev]"
```

This installs the Python package in editable mode and registers the `qalens`
command.

Verify:

```bash
qalens --help
qalens --version
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

`make build-ui` compiles the React app into `src/qalens/server/static/`, which is
what `qalens serve` uses when serving the built UI from Python.

### 7. Try QaLens With Sample Reports

The repo includes parser fixtures under `tests/fixtures/`.

Detect a report format:

```bash
qalens detect tests/fixtures/allure_sample
qalens detect tests/fixtures/extent_sample
```

Extract normalized JSON:

```bash
qalens extract tests/fixtures/allure_sample --out extracted.json
```

Ingest a report into the local SQLite database:

```bash
qalens ingest tests/fixtures/allure_sample
```

The sample Allure fixture may print a warning about a missing screenshot
attachment. That is expected for this fixture and does not block ingestion.

By default QaLens stores data in `~/.qalens/qalens.db`. You can use a project-local
database instead:

```bash
qalens ingest tests/fixtures/allure_sample --db ./qalens.db
```

If your report does not include owner metadata, provide an owner mapping file
during ingestion:

```bash
qalens ingest tests/fixtures/allure_sample --db ./qalens.db --owner-map owners.toml
```

Example `owners.toml`:

```toml
[[owners]]
owner = "Authentication Team"
suites = ["Authentication*"]
tags = ["auth", "login"]

[[owners]]
owner = "Checkout Team"
features = ["Checkout", "Payments"]
tests = ["testPayPal*", "testCreditCardPayment()"]

[[owners]]
owner = "Search Team"
test_regex = ["Search.*Filter"]
```

Mapping rules can match `tests`, `canonical_tests`, `test_regex`, `suites`,
`features`, `stories`, and `tags`. Existing owner labels from the report are
preserved by default; use `--override-owners` when the mapping file should be
authoritative.

Analyze ingested runs:

```bash
qalens analyze --db ./qalens.db
```

Compare run history from the CLI:

```bash
qalens compare --db ./qalens.db --by runs --window 10
qalens compare --db ./qalens.db --by owners --window 10
qalens compare --db ./qalens.db --by modules --window 10
qalens compare --db ./qalens.db --by suites --window 10
```

Use explicit runs when you want a fixed comparison range:

```bash
qalens compare --db ./qalens.db --by runs --run-id RUN_A --run-id RUN_B
```

Useful filters:

| Option | Purpose |
|---|---|
| `--latest-failed` | Only show tests failing in the latest selected run |
| `--changed` | Only show tests whose latest status changed from the previous run |
| `--format json` | Print machine-readable output for CI scripts |
| `--limit 50` | Cap rows printed to the terminal |

Inspect one target over time:

```bash
qalens history test "testCreditCardPayment()" --db ./qalens.db
qalens history owner "Checkout Team" --db ./qalens.db
qalens history suite "Payments" --db ./qalens.db
qalens history module "checkout-module" --db ./qalens.db
qalens history failure FINGERPRINT --db ./qalens.db
```

`qalens history` is useful when you already know the test, owner, suite/module,
or failure fingerprint and want its timeline across recent runs. Use
`--window 50` for a longer history, `--project TEXT` to scope the lookup, and
`--format json` for automation.

Generate a one-off summary directly from a report:

```bash
qalens summarize tests/fixtures/allure_sample --format markdown --out summary.md
```

View failure clusters directly from a report:

```bash
qalens clusters tests/fixtures/allure_sample
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
  qalens ingest "$report" --db ./shopnow-demo.db
done
```

Analyze the full run history:

```bash
qalens analyze --db ./shopnow-demo.db
```

Export a shareable report:

```bash
qalens report --db ./shopnow-demo.db --out qalens-report.html
qalens report --db ./shopnow-demo.db --format markdown --out qalens-report.md
```

Open the demo in the web UI:

```bash
qalens serve --db ./shopnow-demo.db
```

### 9. Run The Web UI

If you haven't ingested any reports yet (step 7), ingest at least one so the
UI has something to show:

```bash
qalens ingest tests/fixtures/allure_sample --db ./qalens.db
```

Start the local server:

```bash
qalens serve --db ./qalens.db
```

The UI runs at:

```text
http://127.0.0.1:8080
```

For frontend development, run the Python API server and Vite dev server in two
terminals.

Terminal 1:

```bash
qalens serve --db ./qalens.db --no-open
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

The UI includes a **Settings** screen. Use it to verify which SQLite database
the running server is using, inspect the active `config.toml` path, and update
safe LLM provider settings without editing TOML by hand. Artifact defaults,
security boundaries, and owner-mapping status are shown there as read-only
runtime context.

By default, `qalens serve` is intended for localhost and does not require a login.
For shared team usage, QaLens supports two optional auth modes.

For quick private sharing, require an admin token:

```bash
export QALENS_AUTH_TOKEN="replace-with-a-long-random-token"
qalens serve --db ./qalens.db --host 0.0.0.0 --allow-public-bind
```

You can also pass the token for a single server session:

```bash
qalens serve --db ./qalens.db --auth-token "replace-with-a-long-random-token"
```

When auth is enabled, the browser prompts for the token and QaLens sends it as a
Bearer token on API requests. The token is kept in browser session storage.

For stronger team sign-in, use GitHub OAuth:

```bash
export QALENS_AUTH_MODE=github
export QALENS_GITHUB_CLIENT_ID="github-oauth-client-id"
export QALENS_GITHUB_CLIENT_SECRET="github-oauth-client-secret"
export QALENS_SESSION_SECRET="$(openssl rand -base64 32)"   # keep stable across restarts
export QALENS_ALLOWED_GITHUB_USERS="your-github-login,teammate-login"
# optional org allowlist — any member of the org is granted access:
export QALENS_ALLOWED_GITHUB_ORGS="your-org"
# optional admin list — only these logins can access the Settings panel:
export QALENS_ADMIN_GITHUB_USERS="your-github-login"

qalens serve --db ./qalens.db
```

**Creating the GitHub OAuth App:**

1. Go to [github.com/settings/developers](https://github.com/settings/developers)
2. Click **OAuth Apps** → **New OAuth App**
3. Fill in the form:

   | Field | Value |
   |---|---|
   | Application name | `QaLens` (or any name) |
   | Homepage URL | `http://localhost:8080` |
   | Authorization callback URL | `http://localhost:8080/auth/github/callback` |

4. Click **Register application**
5. Copy the **Client ID** → set as `QALENS_GITHUB_CLIENT_ID`
6. Click **Generate a new client secret** → copy it immediately (shown once) → set as `QALENS_GITHUB_CLIENT_SECRET`

For non-local deployments, replace `http://localhost:8080` with your deployed
HTTPS URL in both the Homepage URL and Authorization callback URL fields, or set
`QALENS_GITHUB_CALLBACK_URL` explicitly to match the registered callback URL.

**Sessions and sign-out.** Sessions are signed with `QALENS_SESSION_SECRET` and last
8 hours. Use the same secret value across server restarts to avoid invalidating
active sessions. Authenticated users can sign out at any time from the **Sign out**
button at the bottom of the sidebar, which clears the session cookie and returns
them to the login page.

**Admin access.** By default every authenticated GitHub user can access the
Settings panel. Set `QALENS_ADMIN_GITHUB_USERS` to a comma-separated list of
GitHub logins to restrict Settings — including LLM provider configuration — to
those users only. Non-admin users see the same runs, incidents, and analysis
views but the Settings tab is hidden and the settings API returns 403.

### 10. Optional LLM Setup

QaLens works without an LLM for ingestion, parsing, summaries, and deterministic
analysis. LLM-powered chat uses `~/.qalens/config.toml`.

Create the default config:

```bash
qalens llm-config --init
qalens llm-config --show
```

QaLens does not ship any LLM. The default config points to a locally-running
[Ollama](https://ollama.com) instance, which you install and run separately.
If Ollama is not running, LLM-powered chat will not work — all other QaLens
features (ingestion, analysis, summaries, comparison) remain fully functional.

Cloud providers require an explicit opt-in because report data may include test
names, stack traces, hostnames, and other sensitive details. There are three
ways to enable an external provider:

**Via the Settings page** (easiest) — open the web UI, go to **Settings**, choose
a provider, and toggle **Allow external LLM**. Changes are saved to
`~/.qalens/config.toml` immediately. The Settings page is only visible to admin
users when GitHub auth is enabled.

**Via `config.toml`:**

```toml
[llm]
provider = "openai"
allow_external = true
```

**Via environment variable:**

```bash
export QALENS_ALLOW_EXTERNAL_LLM=1
```

Ask a question after ingesting runs:

```bash
qalens ask "What broke in the latest run?" --db ./qalens.db
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
| Serve local UI | `qalens serve --db ./qalens.db` |
| Serve ShopNow demo | `qalens serve --db ./shopnow-demo.db` |
| Export shareable report | `qalens report --db ./qalens.db --out qalens-report.html` |
| Build package | `make build` |

---

## Shareable Report Export

QaLens can export a deterministic, standalone triage report from the SQLite run
history. The report is generated from QaLens's stored analysis data, not by an
LLM, so the numbers stay consistent between CLI, CI, and the web UI.

HTML report:

```bash
qalens report --db ./qalens.db --out qalens-report.html
```

Markdown report:

```bash
qalens report --db ./qalens.db --format markdown --out qalens-report.md
```

JSON payload:

```bash
qalens report --db ./qalens.db --format json --out qalens-report.json
```

Useful options:

| Option | Purpose |
|---|---|
| `--project TEXT` | Restrict the report to one project |
| `--run-id latest` | Report on the latest run, a run id, or a run sequence number |
| `--window 10` | Number of recent runs used for recurring failure groups |
| `--min-runs 2` | Minimum history depth for stability and flaky sections |
| `--limit 10` | Maximum rows per report section |
| `--open` | Open the generated HTML report in your browser |

The HTML export is self-contained and makes no network calls, which makes it
suitable for GitHub Actions artifacts, release handoffs, and team triage notes.

---

## Example CLI Output

```
QaLens — Quality Assurance + Lens
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

- **Local-first** — Core analysis, ingestion, and the web UI run entirely on your machine with no telemetry. GitHub OAuth and cloud LLM providers are optional and opt-in.
- **Explainable over magical** — Every insight includes category, confidence, explanation, and evidence.
- **Normalize first, analyze second** — Parsers are strictly decoupled from analyzers.
- **Plugin-extensible** — Add custom parsers, rules, or output writers without forking.
- **Production-quality** — Typed, tested, documented, and maintainable.

## Security Defaults

QaLens treats reports as untrusted input. Ingestion validates supported report
file types, bounds screenshot bytes, rejects SVG artifacts, validates raster
images by magic bytes, and redacts common secrets before report-derived text is
sent to an LLM.

LLM features default to local providers. Cloud providers require an explicit
opt-in with `allow_external = true` in the QaLens LLM config or
`QALENS_ALLOW_EXTERNAL_LLM=1`.

For networked deployments, review [SECURITY.md](SECURITY.md) and
[PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md). Configure `QALENS_AUTH_TOKEN`
or `qalens serve --auth-token`, use HTTPS, and keep QaLens behind trusted network
controls when exposing it beyond localhost.

---

## Using QaLens as a Python Library

```python
from qalens.api.library import QaLensClient

client = QaLensClient()

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

QaLens can capture screenshot artifacts from test reports at three levels of detail, controlled by the `--artifact-mode` flag when running `qalens ingest`.

QaLens is **text-first**. Screenshots are optional supporting evidence. The default mode stores only metadata — no image bytes — keeping the database small and portable.

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

When a failed test has more screenshots than the cap allows, QaLens applies a priority ranking before truncation:

1. Screenshots from **failed or broken steps** (`is_from_failed_step=True`) — most likely to show the root cause.
2. Screenshots with the **highest sequence number** among the remainder — nearest to the exception.
3. First and last screenshot as a last-resort fallback.

### Screenshot sources in Extent Reports

QaLens extracts screenshots from three locations in an Extent HTML report:

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
qalens ingest ./my-extent-report

# Text-only — fastest, smallest DB, no artifact records
qalens ingest ./my-extent-report --artifact-mode text-only

# Capture metadata only (explicit)
qalens ingest ./my-extent-report --artifact-mode metadata-only

# Store full image bytes with compression (requires Pillow)
qalens ingest ./my-extent-report \
  --artifact-mode full \
  --artifact-storage-dir ~/.qalens/artifacts \
  --max-screenshots-per-failure 3 \
  --jpeg-quality 75
```

### End-of-run ingestion summary

After every `qalens ingest`, QaLens prints an artifact summary:

```
Artifact ingestion  (mode: metadata-only)
  Screenshot refs found    : 14
  Selected after cap       : 8
  Artifact records created : 8
  Skipped (bad/missing)    : 1
```

In `full` mode the summary also reports images stored and duplicates skipped.

### Storage note

Image bytes are **never stored in the SQLite database**. The `artifacts` table holds metadata and a `file://` URI pointing to the artifact store directory. This keeps the database small and query-fast while still allowing analysis layers to reference screenshots by their stable SHA-256 content hash. S3/MinIO backends can be added by implementing the `ArtifactStore` interface in `src/qalens/artifacts/storage.py`.

---

## Repository Structure

Top-level layout:

```
QaLens/
├── src/qalens/                 # Python package
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
src/qalens/
├── api/          # Public Python API; QaLensClient lives here
├── analyzers/    # Categorization, flaky scoring, clustering, comparison, prediction
├── artifacts/    # Screenshot/artifact policy, image inspection, storage
├── cli/          # Active Typer CLI package for the `qalens` command
├── cli.py        # Legacy monolithic CLI kept during CLI migration work
├── db/           # SQLite schema, repository layer, row models
├── llm/          # LLM config, prompt builders, routing, context gathering, client
├── models/       # Canonical Pydantic/domain models for runs, tests, failures
├── parsers/      # Allure, Extent, JUnit, TestNG, Playwright, Cypress parsing
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

- `src/qalens/server/static/` is generated by `npm run build` or `make build-ui`.
- `node_modules/`, `.venv/`, caches, local databases, local reports, and generated
  artifacts are intentionally ignored by git.
- The default local database is `~/.qalens/qalens.db`.

See [docs/architecture.md](docs/architecture.md) for the deeper system design.

---

## Contributing

Contributions are warmly welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

We especially welcome:
- Additional report format parsers (pytest-html and other CI exporters)
- New heuristic categorization rules
- Improved flaky detection signals
- Documentation and examples

---

## License

[Apache 2.0](LICENSE) — free to use, modify, and distribute.

---

*Built with care for the QA and engineering community.*
