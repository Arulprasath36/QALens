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

## Quickstart

### Install

```bash
pip install qara-insights
```

Or from source:

```bash
git clone https://github.com/your-org/qara.git
cd qara
pip install -e ".[dev]"
```

### Detect what kind of report you have

```bash
qara detect ./reports/my-report
```

### Extract normalized data from a report

```bash
qara extract ./reports/allure-report --out extracted.json
```

### Analyze and classify failures

```bash
qara analyze ./reports/allure-report --history ./history --out analysis.json
```

### Generate a Markdown summary

```bash
qara summarize ./reports/extent-report --format markdown --out summary.md
```

### View failure clusters

```bash
qara clusters ./reports/allure-report
```

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

Image bytes are **never stored in the SQLite database**. The `artifacts` table holds metadata and a `file://` URI pointing to the artifact store directory. This keeps the database small and query-fast while still allowing analysis layers to reference screenshots by their stable SHA-256 content hash. S3/MinIO backends can be added by implementing the `ArtifactStore` interface in `src/ari/artifacts/storage.py`.

---

## Project Architecture

```
src/qara/
├── parsers/      # Report-specific HTML/JSON extractors
├── models/       # Canonical Pydantic data models
├── analyzers/    # Heuristic + optional ML analysis
├── outputs/      # JSON, Markdown, console writers
├── utils/        # Text normalization, hashing, FS utilities
├── artifacts/    # Artifact ingestion policy, storage, compression
└── api/          # Public Python library surface
```

See [docs/architecture.md](docs/architecture.md) for the full design.

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
