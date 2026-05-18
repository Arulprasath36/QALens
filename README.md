# QA Lens

> Turn existing test automation reports into local, explainable triage intelligence.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PyPI](https://img.shields.io/badge/pypi-qalens-blue.svg)](https://pypi.org/project/qalens/)

<p align="center">
  <img src="docs/assets/qa-lens-dashboard.png" alt="QA Lens dashboard" width="720">
</p>

---

## What is QA Lens?

QA Lens reads the HTML or XML reports your test framework already produces, stores the results in a local SQLite database, and helps answer questions your report viewer does not:

- What failed in the latest run, and why?
- Which failures are related and share the same root cause?
- Which tests are flaky — and is the flakiness getting worse?
- Which tests are highest risk of failing in the next run?
- Is the suite trending healthier or degrading over time?
- What should the team look at first?

**QA Lens is not a test runner.** It does not replace Allure, Extent, Playwright, Cypress, JUnit, or TestNG. It is an analysis and intelligence layer on top of those reports.

---

## Why QA Lens?

Modern test suites produce hundreds or thousands of results per run. Existing report tools show pass/fail status, logs, screenshots, and stack traces — and stop there.

| Problem | What QA Lens does |
|---|---|
| Hours spent manually triaging failures | Automates failure classification and root-cause grouping |
| "Is this flaky or a real bug?" | Scores flakiness across multiple runs using history |
| "Is infra to blame or the product?" | Categories: environment, test script, product defect, test data |
| "We keep seeing the same failure pattern" | Groups failures by normalized signature across runs |
| "What do I tell the engineering lead?" | Generates concise decision summaries and priority actions |
| "Is the suite getting better or worse?" | Tracks trends, pass rates, and test stability over time |

---

## Key Features

- **CLI:** `qalens` — ingest, analyze, compare, ask, report
- **Web UI:** runs, incidents, analysis trends, risk, comparison, LLM chat, settings
- **Deterministic analysis** — failure classification, clustering, risk scoring, and many answers require no LLM
- **SQLite-backed run history** — lightweight, portable, no separate database server
- **Owner mapping** — assign tests to teams; track failure rates per owner
- **Multi-format parsing** — Allure, Extent, JUnit, TestNG, Playwright, Cypress/Mocha
- **Shareable reports** — standalone HTML, Markdown, and JSON export
- **Optional LLM chat** — local (Ollama) or cloud providers, explicitly opt-in
- **Optional auth** — token or GitHub OAuth; off by default for local use

---

## Supported Report Formats

| Format | Supported input |
|---|---|
| Allure | HTML report folders with JSON data (v2) |
| Extent | HTML reports (v4, v5) |
| JUnit | `testsuite` / `testsuites` XML |
| TestNG | `testng-results.xml` |
| Playwright | JSON reports and JSON-backed HTML report folders |
| Cypress / Mocha | JSON reports, including Mochawesome-style output |

---

## Installation

### From PyPI (recommended)

```bash
pip install qalens
```

This installs the `qalens` CLI with the web UI already bundled. No Node.js required.

Verify:

```bash
qalens --version
qalens --help
```

### From source

Required: Python 3.10+, Node.js 18+, npm, Git.

```bash
git clone https://github.com/Arulprasath36/QALens.git
cd QALens

python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .\.venv\Scripts\Activate.ps1    # Windows PowerShell

pip install -e .

# Build the web UI (required when installing from source)
make build-ui
```

For development (adds pytest, ruff, mypy):

```bash
pip install -e ".[dev]"
```

Verify:

```bash
qalens --version
qalens --help
```

---

## Quick Start

### 1 — Ingest a sample report

QA Lens ships with sample fixtures for every supported format:

```bash
qalens ingest tests/fixtures/allure_sample --db ./qalens.db
```

Or ingest your own report:

```bash
qalens ingest path/to/your-allure-report --db ./qalens.db
```

### 2 — Start the web UI

```bash
qalens serve --db ./qalens.db
```

Open `http://127.0.0.1:8080` in your browser.

### 3 — Ask a question

```bash
qalens ask "What broke in the latest run?" --db ./qalens.db
qalens ask "Which tests are flaky?" --db ./qalens.db
```

Many questions are answered deterministically from the database — no LLM required.

---

## CLI Reference

### Detect report format

```bash
qalens detect path/to/report
```

### Extract normalized JSON (no database)

```bash
qalens extract path/to/report --out extracted.json
```

### Ingest a report into the database

```bash
qalens ingest path/to/report --db ./qalens.db
qalens ingest path/to/report --db ./qalens.db --owner-map owners.toml
```

If you haven't ingested any reports yet, ingest at least one so the UI has something to show.

### Analyze stored runs

```bash
qalens analyze --db ./qalens.db
```

### Compare run history

```bash
qalens compare --db ./qalens.db --by runs --window 10
qalens compare --db ./qalens.db --by owners --window 10
qalens compare --db ./qalens.db --by suites --window 10
qalens compare --db ./qalens.db --by modules --window 10
```

Use `--run-id RUN_A --run-id RUN_B` for an explicit range.

### Inspect one target over time

```bash
qalens history test "testCreditCardPayment()" --db ./qalens.db
qalens history owner "Checkout Team" --db ./qalens.db
qalens history suite "Payments" --db ./qalens.db
qalens history failure FINGERPRINT --db ./qalens.db
```

### Generate a standalone report

```bash
qalens report --db ./qalens.db --out report.html
qalens report --db ./qalens.db --format markdown --out report.md
qalens report --db ./qalens.db --format json --out report.json
```

### One-off summary (no database)

```bash
qalens summarize path/to/report --format markdown --out summary.md
qalens clusters path/to/report
```

---

## Demo Dataset

The repo includes a synthetic 53-run ShopNow E-Commerce dataset:

```text
tmp_test_data/ShopNow_E-Commerce/run_001/ … run_053/
```

Build a demo database:

```bash
for report in tmp_test_data/ShopNow_E-Commerce/run_*; do
  qalens ingest "$report" --db ./shopnow-demo.db
done
```

Explore it:

```bash
qalens serve --db ./shopnow-demo.db
qalens analyze --db ./shopnow-demo.db
qalens report --db ./shopnow-demo.db --out shopnow-report.html
```

---

## Web UI

Start the server:

```bash
qalens serve                        # uses ~/.qalens/qalens.db by default
qalens serve --db ./qalens.db       # project-local database
qalens serve --port 9090            # custom port (default: 8080)
```

| Tab | What it shows |
|---|---|
| Runs | Latest run results, decision brief, fix-first actions, and per-test details |
| Incidents | Recurring failure signatures and root-cause clusters |
| Analysis | Suite health trends, pass-rate chart, owner load, active clusters |
| Risk | Tests most likely to fail or flip in the next run |
| Compare | Side-by-side comparison of runs, owners, suites, or modules |
| Chat | Ask questions — answered deterministically or via LLM |
| Settings | Runtime paths, LLM config, authentication status (admin only) |

### Frontend development mode

Run the API and Vite dev server in two terminals for hot-reload:

```bash
# Terminal 1
qalens serve --db ./qalens.db --no-open

# Terminal 2
cd frontend && npm run dev
```

Open `http://localhost:3000` — API requests are proxied to port 8080.

---

## Deterministic vs LLM-Assisted

QA Lens works without an LLM for all of the following:

- Ingesting reports and storing results
- Failure classification (environment / test script / product defect / test data / flaky / unknown)
- Failure clustering by normalized signature
- Run comparison and regression detection
- Risk tier scoring
- Flakiness signals
- Shareable report export
- Trend analysis and suite health in the web UI
- Many factual `qalens ask` questions

LLM-assisted answers are useful for open-ended questions and explanations. They require a configured provider and are always opt-in.

---

## LLM Setup (Optional)

QA Lens does not ship or install any LLM. It connects to one you provide.

Create the config file:

```bash
qalens llm-config --init
qalens llm-config --show
```

The default config points to a locally-running [Ollama](https://ollama.com) instance, which you install and run separately. If Ollama is not running, LLM-assisted chat is unavailable — all other features remain fully functional.

LLM settings can also be changed in the web UI under **Settings → LLM** without editing the config file.

### Cloud providers (opt-in)

Cloud providers send report data (test names, stack traces, error messages) to an external service. Enable them explicitly only after reviewing what data may leave your machine.

**Via the Settings page** (easiest): open the web UI → Settings → choose a provider → enable **Allow external LLM**.

**Via `~/.qalens/config.toml`:**

```toml
[llm]
provider = "openai"
allow_external = true
```

**Via environment variable:**

```bash
export QALENS_ALLOW_EXTERNAL_LLM=1
```

---

## Authentication

By default, `qalens serve` binds to `127.0.0.1` and requires no login.

### Token-based access

```bash
export QALENS_AUTH_TOKEN="replace-with-a-long-random-token"
qalens serve --db ./qalens.db --host 0.0.0.0 --allow-public-bind
```

Or for a single session:

```bash
qalens serve --db ./qalens.db --auth-token "replace-with-a-long-random-token"
```

### GitHub OAuth

```bash
export QALENS_AUTH_MODE=github
export QALENS_GITHUB_CLIENT_ID="your-client-id"
export QALENS_GITHUB_CLIENT_SECRET="your-client-secret"
export QALENS_SESSION_SECRET="$(openssl rand -base64 32)"   # keep stable across restarts
export QALENS_ALLOWED_GITHUB_USERS="your-github-login,teammate"
export QALENS_ALLOWED_GITHUB_ORGS="your-org"               # optional: grant whole org
export QALENS_ADMIN_GITHUB_USERS="your-github-login"        # optional: restrict Settings tab

qalens serve --db ./qalens.db
```

**Creating the GitHub OAuth App:**

1. Go to [github.com/settings/developers](https://github.com/settings/developers)
2. Click **OAuth Apps → New OAuth App**
3. Fill in:

   | Field | Value |
   |---|---|
   | Application name | `QA Lens` |
   | Homepage URL | `http://localhost:8080` |
   | Authorization callback URL | `http://localhost:8080/auth/github/callback` |

4. Click **Register application**
5. Copy the **Client ID** → `QALENS_GITHUB_CLIENT_ID`
6. Click **Generate a new client secret** → copy immediately (shown once) → `QALENS_GITHUB_CLIENT_SECRET`

For production, replace `http://localhost:8080` with your HTTPS URL in both fields, or set `QALENS_GITHUB_CALLBACK_URL` explicitly.

**Sessions and sign-out:** Sessions last 8 hours. Use the same `QALENS_SESSION_SECRET` across server restarts to avoid invalidating active sessions. Users sign out via the **Sign out** button at the bottom of the sidebar.

**Admin access:** By default every authenticated GitHub user can access the Settings panel. Set `QALENS_ADMIN_GITHUB_USERS` to a comma-separated list of logins to restrict it. Non-admin users see all analysis views; the Settings tab is hidden and the settings API returns 403.

For networked deployments, use HTTPS and review [SECURITY.md](SECURITY.md) and [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md).

---

## Database

Default location:

```text
~/.qalens/qalens.db
```

Use a project-local database with `--db`:

```bash
qalens ingest path/to/report --db ./qalens.db
qalens serve --db ./qalens.db
```

The database is a standard SQLite file. Back it up by copying the file. The web UI, history, comparison, trends, and report export all read from it.

---

## Owner Mapping

If reports do not include team ownership, provide a mapping at ingestion:

```bash
qalens ingest path/to/report --db ./qalens.db --owner-map owners.toml
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

Rules match on `tests`, `canonical_tests`, `test_regex`, `suites`, `features`, `stories`, and `tags`. Existing owner labels from the report are preserved unless you pass `--override-owners`.

---

## Screenshot and Artifact Handling

QA Lens is text-first. Screenshots are optional supporting evidence.

| Mode | What is stored |
|---|---|
| `text-only` | Test names, statuses, errors, and stack traces only |
| `metadata-only` *(default)* | Plus screenshot hashes, dimensions, MIME types, and references — no image bytes |
| `full` | Plus image bytes in a configurable artifact directory |

```bash
qalens ingest ./report --artifact-mode text-only
qalens ingest ./report --artifact-mode full --artifact-storage-dir ~/.qalens/artifacts
```

Image bytes are never stored in the SQLite database.

---

## Security Defaults

QA Lens treats reports as untrusted input:

- Report file type validation
- Raster image validation by magic bytes (not filename extension)
- SVG artifact rejection
- Common secret redaction before LLM submission
- No telemetry or outbound calls by default
- Cloud LLM providers disabled unless explicitly allowed

See [SECURITY.md](SECURITY.md) for the full security policy and vulnerability reporting instructions.

---

## Python API

```python
from qalens.api.library import QALensClient

client = QALensClient()

report_type = client.detect_report("./reports/allure-report")
run = client.extract_report("./reports/allure-report")
analysis = client.analyze_report(run)

summary = client.summarize_report(analysis, fmt="markdown")
print(summary)
```

---

## Repository Structure

```text
QALens/
├── src/qalens/              # Python package
│   ├── api/                 # Public Python API (QALensClient)
│   ├── analyzers/           # Classification, clustering, flaky, risk, decision
│   ├── artifacts/           # Screenshot policy and artifact storage
│   ├── cli/                 # CLI commands (ingest, serve, compare, …)
│   ├── db/                  # SQLite schema and repository layer
│   ├── llm/                 # LLM config, prompts, client
│   ├── parsers/             # Allure, Extent, JUnit, TestNG, Playwright, Cypress
│   ├── reports/             # HTML/Markdown/JSON report builders
│   ├── server/              # FastAPI app, routes, auth, static UI
│   └── utils/               # Filesystem and text helpers
├── frontend/                # React + Vite web UI source
├── tests/                   # Python test suite
│   └── fixtures/            # Sample reports for all supported formats
├── docs/                    # Architecture and design documentation
├── tmp_test_data/           # Synthetic ShopNow demo dataset
├── Makefile                 # Build shortcuts
├── pyproject.toml           # Python package metadata
├── SECURITY.md              # Security policy
└── PRODUCTION_CHECKLIST.md  # Network deployment checklist
```

### Build commands

| Command | What it does |
|---|---|
| `make build-ui` | Compile React app into `src/qalens/server/static/` |
| `make build` | `build-ui` + build the Python wheel |
| `make check-package` | Build distributions and run `twine check` |
| `make release-test` | Build, check, and publish to TestPyPI |
| `make release` | Build, check, and publish to PyPI |

### Publishing to PyPI

The package name is `qalens`; the CLI command is also `qalens`.

Recommended release flow:

```bash
# 1. Make sure the version in src/qalens/version.py is final.

# 2. Run local verification.
pytest
cd frontend && npm test -- --run && npm audit --audit-level=high && cd ..
pip-audit --desc
bandit -r src/ -ll -x src/qalens/server/static/

# 3. Build and validate distributions.
make check-package

# 4. Publish to TestPyPI first.
make release-test

# 5. Install from TestPyPI in a clean environment and smoke test.
python -m venv /tmp/qalens-smoke
source /tmp/qalens-smoke/bin/activate
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ qalens
qalens --help

# 6. Publish to PyPI.
make release
```

For GitHub-based publishing, use the `Publish Python package` workflow and configure PyPI/TestPyPI Trusted Publishing for the matching GitHub environments.

---

## Limitations

- QA Lens does not execute tests.
- Single-run data is sufficient for basic failure summaries. Trends, risk scoring, and flakiness detection improve with more ingested runs.
- LLM-assisted answers require a configured provider. Deterministic answers do not.
- Parser accuracy depends on the data exported by the report tool. Reports that omit stack traces or error types reduce classification confidence.
- The web server is local-first. Do not expose it publicly without authentication, HTTPS, and network controls.
- Repository-wide strict `ruff` / `mypy` / `bandit` cleanup is in progress.

---

## Roadmap

Near-term:

- More real-world report fixtures and edge-case coverage
- CI quality gate cleanup (ruff, mypy, bandit)
- Screenshots and demo video
- More export formats and CI integration examples

See [docs/roadmap.md](docs/roadmap.md).

---

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first.

Local checks:

```bash
pytest
cd frontend && npm run typecheck && npm test
```

---

## License

[Apache 2.0](LICENSE)
