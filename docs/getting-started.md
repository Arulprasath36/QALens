# Getting Started

This guide walks through the shortest path from a clean machine to a working QA Lens dashboard with sample data.

## What You Need

For normal use from PyPI:

- Python 3.10 or newer
- A terminal
- A browser

You do **not** need Node.js when installing the published package because the web UI is bundled into the Python wheel.

For Docker use:

- A running Docker engine, such as Docker Desktop or Colima on macOS
- The Docker Compose plugin only if you use the Compose commands
- A browser

For development from source:

- Python 3.10 or newer
- Node.js 18 or newer
- npm
- Git

## 1. Install QA Lens

From PyPI:

```bash
pip install qalens
```

Verify the CLI:

```bash
qalens --version
qalens --help
```

From source:

```bash
git clone https://github.com/Arulprasath36/QALens.git
cd QALens

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
make build-ui
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Docker alternative

If you prefer not to install Python locally:

```bash
docker volume create qalens-data
docker run --rm \
  -v qalens-data:/data \
  -v "$PWD/tests/fixtures/allure_sample:/reports/input:ro" \
  arulprasath36/qalens:latest \
  ingest /reports/input --db /data/qalens.db
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  arulprasath36/qalens:latest
```

This command assumes you are in a cloned repository so `tests/fixtures/allure_sample` exists. For your own report, replace that host path with its location.
The public Docker Hub repository is [arulprasath36/qalens](https://hub.docker.com/r/arulprasath36/qalens).

## 2. Ingest a Sample Report

From a source checkout, QA Lens includes fixtures under `tests/fixtures/`.

```bash
qalens ingest tests/fixtures/allure_sample --db ./qalens.db
```

If you installed from PyPI and do not have the repository fixtures, use your own report:

```bash
qalens ingest path/to/report --db ./qalens.db
```

The `--db ./qalens.db` option stores data in a local SQLite file in the current directory. If you omit `--db`, QA Lens uses `~/.qalens/qalens.db`.

## 3. Start the Web UI

```bash
qalens serve --db ./qalens.db
```

Open:

```text
http://127.0.0.1:8080
```

The default server binds to localhost. Do not expose it publicly without authentication.

## 4. Ask Basic Questions

In the web UI, open the chat panel and ask:

```text
What broke in the latest run?
```

Other useful first questions:

```text
Which tests failed in the latest run?
Which tests are flaky?
Which tests are most risky?
Which suite has the lowest pass rate?
In the last 10 runs, which run had the highest and lowest pass percentage?
```

Many questions are answered deterministically from SQLite. An LLM is optional.

You can also ask from the CLI:

```bash
qalens ask "What broke in the latest run?" --db ./qalens.db
```

## 5. Export a Report

Generate a standalone HTML report:

```bash
qalens report --db ./qalens.db --out qalens-report.html
```

Generate Markdown:

```bash
qalens report --db ./qalens.db --format markdown --out qalens-report.md
```

Generate JSON:

```bash
qalens report --db ./qalens.db --format json --out qalens-report.json
```

## First-Run Checklist

Use this checklist when validating a new installation:

- `qalens --version` works.
- `qalens ingest ... --db ./qalens.db` creates or updates the database.
- `qalens serve --db ./qalens.db` starts without errors.
- The browser opens the dashboard.
- Runs appear on the Runs page.
- Chat answers at least one deterministic question.
- Report export writes an HTML, Markdown, or JSON file.

## What To Do Next

- Read [Ingesting Reports](ingesting-reports.md) before connecting real CI artifacts.
- Read [UI Guide](ui-guide.md) to understand Action Brief, Incidents, Analysis, and Risk.
- Read [Chat and LLMs](chat-and-llm.md) before enabling local or cloud LLMs.
- Read [Security and Deployment](security-and-deployment.md) before sharing QA Lens beyond localhost.
