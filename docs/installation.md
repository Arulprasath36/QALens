# Installation

QA Lens can be installed from PyPI, run in Docker, or installed from source for development.

## Install From PyPI

```bash
pip install qalens
```

This installs:

- The `qalens` CLI.
- The FastAPI backend.
- The bundled React web UI.
- The report parsers and deterministic analyzers.

No Node.js is required for PyPI users.

Verify:

```bash
qalens --version
qalens --help
```

## Run With Docker

Use Docker when you want an isolated installation with no local Python or Node.js setup.

Requirements:

- Docker Engine or Docker Desktop.
- A browser.

Pull and start the published image:

```bash
docker volume create qalens-data
docker run --rm \
  -p 127.0.0.1:8080:8080 \
  -v qalens-data:/data \
  ghcr.io/arulprasath36/qalens:latest
```

Open `http://127.0.0.1:8080`.

The named volume stores:

```text
/data/qalens.db
/data/config.toml
```

From a source checkout, build and run the current code:

```bash
docker compose up --build
```

See [Docker](docker.md) for ingestion commands, upgrades, authentication, and deployment notes.

## Install From Source

Use this when developing QA Lens or testing unreleased changes.

```bash
git clone https://github.com/Arulprasath36/QALens.git
cd QALens

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
make build-ui
```

`make build-ui` compiles the React app into the backend static directory. It is required when serving the UI from a source checkout.

## Python Requirements

QA Lens supports Python 3.10 and newer.

Core dependencies include:

- FastAPI and Uvicorn for the web server.
- Typer and Rich for the CLI.
- Pydantic for data models.
- BeautifulSoup and lxml for HTML/XML parsing.
- defusedxml for safer XML parsing.
- httpx for optional LLM provider calls.
- SQLite through the Python standard library.

## Node Requirements For Development

Frontend development requires:

- Node.js 18 or newer.
- npm.

Install frontend dependencies:

```bash
cd frontend
npm install
```

Run frontend type checking:

```bash
npm run typecheck
```

Build the frontend:

```bash
npm run build
```

From the repository root, `make build-ui` is the normal build entrypoint.

## Database Location

Default database:

```text
~/.qalens/qalens.db
```

Recommended explicit local database for demos and CI artifacts:

```bash
qalens ingest path/to/report --db ./qalens.db
qalens serve --db ./qalens.db
```

QA Lens uses SQLite. You do not need PostgreSQL, MySQL, Redis, or any external database.

## Configuration Location

Default LLM configuration:

```text
~/.qalens/config.toml
```

Configure interactively:

```bash
qalens llm-config
```

Or use the Settings page in the UI.

## Optional LLM Requirements

QA Lens does not require an LLM for core analysis.

Optional local providers:

- Ollama
- LM Studio
- Any OpenAI-compatible localhost endpoint

Optional cloud providers:

- OpenAI
- Azure OpenAI
- Anthropic
- Gemini
- Custom OpenAI-compatible endpoint

Cloud providers require explicit opt-in. See [Chat and LLMs](chat-and-llm.md).

## Common Install Problems

### `qalens: command not found`

The package is not installed in the active environment, or the virtual environment is not activated.

Check:

```bash
which python
which qalens
python -m pip show qalens
```

### UI assets missing from source install

Run:

```bash
make build-ui
```

### Python dependency conflicts

Create a clean virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install qalens
```
