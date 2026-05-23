# API Reference

QA Lens exposes a FastAPI application. The same API powers the React UI.

## Swagger / OpenAPI

Start the server:

```bash
qalens serve --db ./qalens.db
```

Open Swagger UI:

```text
http://127.0.0.1:8080/api/docs
```

Open ReDoc:

```text
http://127.0.0.1:8080/api/redoc
```

OpenAPI JSON:

```text
http://127.0.0.1:8080/openapi.json
```

Use `/api/docs` as the Swagger-style interactive API page.

## Authentication

Authentication depends on server configuration.

Local default:

- No API authentication.
- Intended for localhost use only.

Token auth:

```bash
export QALENS_AUTH_TOKEN="strong-random-token"
qalens serve --db ./qalens.db
```

Requests:

```bash
curl -H "Authorization: Bearer strong-random-token" \
  http://127.0.0.1:8080/api/runs
```

GitHub OAuth auth is browser-oriented. Settings endpoints require admin access when auth is enabled.

## Endpoint Groups

### Health and Auth

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Server health and version. |
| `GET` | `/api/auth/status` | Current auth mode and session status. |
| `POST` | `/auth/logout` | End browser session. |

### Runs and Test Data

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/runs` | List runs. |
| `GET` | `/api/runs/{run_id}` | Get one run. |
| `GET` | `/api/runs/{run_id}/tests` | Get tests for a run. |
| `GET` | `/api/runs/{run_id}/incidents` | Get incidents affecting a run. |

Common query parameter:

```text
project=ProjectName
```

Example:

```bash
curl "http://127.0.0.1:8080/api/runs?project=ShopNow"
```

### Analysis

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/stability` | Stability snapshot and pass-rate health. |
| `GET` | `/api/stability/flaky` | Flaky test data. |
| `GET` | `/api/stability/trends` | Trend direction and history. |
| `GET` | `/api/failure-groups` | Failure clusters and grouped incidents. |
| `GET` | `/api/risk` | Risk-ranked tests. |
| `GET` | `/api/owner-stats` | Owner-level statistics. |
| `GET` | `/api/decision-summary` | Action Brief, executive summary, trend intelligence, and fix-first actions. |

Example:

```bash
curl "http://127.0.0.1:8080/api/decision-summary?project=ShopNow"
```

### Failure Group Links

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/failure-groups/{fingerprint}/bug-links` | Attach an external bug link to a failure group. |
| `DELETE` | `/api/failure-groups/{fingerprint}/bug-links/{link_id}` | Remove a bug link. |

### Evidence

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/evidence/test/{canonical_name}` | Evidence for a canonical test. |
| `GET` | `/api/evidence/run/{run_id}` | Evidence for a run. |

Evidence endpoints are useful for chat result workspaces and drill-down panels.

### Comparison

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/compare/history` | History data for a target. |
| `POST` | `/api/compare/custom` | Custom comparison request. |
| `GET` | `/api/compare/runs` | Compare runs. |
| `GET` | `/api/compare/facets` | Available compare facets. |
| `POST` | `/api/compare/owners` | Compare owners. |
| `POST` | `/api/compare/suites` | Compare suites. |
| `GET` | `/api/compare/breakdown` | Breakdown-style comparison. |

### Chat and LLM

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/ask` | Ask a natural-language question. |
| `GET` | `/api/llm/info` | Current LLM provider and model info. |

Example:

```bash
curl -X POST "http://127.0.0.1:8080/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"What broke in the latest run?","project":null}'
```

The chat API may return:

- `answer`
- `sources`
- `follow_ups`
- `result`
- `uiHints`

When `result` is present, the UI can open a structured workspace.

### Settings

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/settings` | Runtime paths, LLM config, artifacts, and security settings. |
| `PATCH` | `/api/settings/llm` | Update editable LLM settings. |

Settings endpoints require admin access when authentication is enabled.

### Reports and Export

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/report/export` | Export deterministic HTML, Markdown, or JSON report. |

Example:

```bash
curl "http://127.0.0.1:8080/api/report/export?format=html" \
  -o qalens-report.html
```

Supported formats:

```text
html
markdown
md
json
```

### UI Support

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/homepage-cards` | Suggested questions/cards for the UI. |

## API Stability

QA Lens is currently beta software. The CLI and documented product behavior should be treated as more stable than internal UI API response shapes.

For integrations:

- Prefer CLI commands for CI workflows.
- Use `/api/report/export` for generated artifacts.
- Use `/api/docs` to inspect current request and response schemas.
- Pin a QA Lens version when building API clients.

