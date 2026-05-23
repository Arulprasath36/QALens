# Troubleshooting

This page lists common QA Lens setup, ingestion, UI, chat, and API issues.

## `qalens: command not found`

The CLI is not installed in the active Python environment.

Check:

```bash
which python
python -m pip show qalens
which qalens
```

Fix:

```bash
python -m pip install qalens
```

For source installs:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

## UI Starts But Looks Empty

Most likely no reports have been ingested into the database being served.

Check:

```bash
qalens ingest path/to/report --db ./qalens.db
qalens serve --db ./qalens.db
```

Make sure the same database path is used for ingestion and serving.

## Report Format Not Detected

Run:

```bash
qalens detect path/to/report --verbose
```

Possible causes:

- Wrong folder selected.
- Report generation incomplete.
- HTML report does not include expected JSON data.
- XML is not JUnit/TestNG-compatible.
- File extension is unsupported.

Try extraction:

```bash
qalens extract path/to/report --out normalized.json
```

## Duplicate Run Was Skipped

QA Lens skips an already-ingested run by default.

Use:

```bash
qalens ingest path/to/report --db ./qalens.db --force
```

## Web UI Assets Missing From Source Install

Run:

```bash
make build-ui
```

Then restart:

```bash
qalens serve --db ./qalens.db
```

## Chat Shows `API 500`

Check the backend terminal logs first. The frontend may show a compact API status if the backend fails.

Common causes:

- Backend not restarted after code changes.
- Wrong or missing database path.
- Invalid config file.
- A bug in a specific chat route.

Validate the API:

```bash
curl http://127.0.0.1:8080/api/health
```

Try a deterministic question:

```bash
curl -X POST http://127.0.0.1:8080/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What broke in the latest run?","project":null}'
```

## Chat Says It Could Not Reach The LLM

Deterministic answers still work. LLM-assisted narration needs a configured and reachable provider.

Check Settings or:

```bash
qalens llm-config
```

For Ollama:

```bash
ollama list
curl http://localhost:11434/v1/models
```

For LM Studio:

- Start the local server.
- Confirm the endpoint, usually `http://localhost:1234/v1`.

## Local LLM Is Enabled But Answers Still Look Deterministic

This is expected for factual questions.

QA Lens intentionally uses deterministic code first for:

- Counts.
- Rankings.
- Pass-rate questions.
- Latest run summaries.
- Failure tables.
- Risk and trend workspaces.

The LLM is used when narration, flexible interpretation, or general explanation is needed.

## Save Button In Settings Is Disabled

Settings are locked by default.

Click **Edit**, change a value, then **Save**.

Save should remain disabled when no field has changed.

## LLM Toggle Turns Off After Saving

Restart the backend if the UI and backend are on different builds.

Then check:

```bash
curl http://127.0.0.1:8080/api/settings
```

Look for:

```json
{
  "llm": {
    "enabled": true
  }
}
```

## Swagger Page Not Found

Start the server:

```bash
qalens serve --db ./qalens.db
```

Open:

```text
http://127.0.0.1:8080/api/docs
```

QA Lens exposes one human-facing API documentation page. If it appears unstyled, restart the backend so the latest Content Security Policy is active.

## Port Already In Use

Use another port:

```bash
qalens serve --db ./qalens.db --port 8090
```

## Permission Error Writing Database

Use a writable path:

```bash
qalens ingest path/to/report --db ./qalens.db
```

Avoid protected system directories.

## Public Server Warning

QA Lens is intended to bind to localhost by default.

If you bind publicly, enable authentication and use a trusted reverse proxy.
